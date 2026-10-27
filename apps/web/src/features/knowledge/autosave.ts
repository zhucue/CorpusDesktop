import { useCallback, useEffect, useRef, useState } from "react";

export type SaveState = "saved" | "dirty" | "saving" | "error";

/**
 * Debounced save: `change(v)` schedules `save(v)` after `delay` ms of quiet; `flush()` saves now.
 * A pending value is saved on unmount (switching notes keys the editor).
 */
export function useAutosave<T>(save: (v: T) => Promise<unknown>, delay = 1000) {
  const saveRef = useRef(save);
  saveRef.current = save;
  const pending = useRef<{ v: T } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);
  const [state, setState] = useState<SaveState>("saved");
  const [error, setError] = useState<unknown>(null);

  const flush = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const p = pending.current;
    if (!p) return;
    pending.current = null;
    if (alive.current) setState("saving");
    try {
      await saveRef.current(p.v);
      if (alive.current) {
        setError(null);
        setState(pending.current ? "dirty" : "saved");
      }
    } catch (e) {
      // Keep the value so the next change or 保存 retries it.
      if (!pending.current) pending.current = p;
      if (alive.current) {
        setError(e);
        setState("error");
      }
    }
  }, []);

  const change = useCallback(
    (v: T) => {
      pending.current = { v };
      setState("dirty");
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void flush(), delay);
    },
    [delay, flush],
  );

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      void flush();
    };
  }, [flush]);

  return { change, flush, state, error };
}
