import { useCallback, useEffect, useRef, useState } from "react";

export type SaveState = "saved" | "dirty" | "saving" | "error";

/**
 * Debounced save: `change(v)` schedules `save(v)` after `delay` ms of quiet; `flush()` saves now.
 * Saves run one at a time (each starts from the previous one's result, e.g. the note version).
 * A pending value is saved on unmount (switching notes keys the editor). `pause` stops saving: changes stay
 * pending until it is lifted (a save conflict waits for the user).
 */
export function useAutosave<T>(save: (v: T) => Promise<unknown>, delay = 1000, pause = false) {
  const saveRef = useRef(save);
  saveRef.current = save;
  const pauseRef = useRef(pause);
  pauseRef.current = pause;
  const pending = useRef<{ v: T } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const chain = useRef<Promise<void>>(Promise.resolve());
  const alive = useRef(true);
  const [state, setState] = useState<SaveState>("saved");
  const [error, setError] = useState<unknown>(null);

  const saveOnce = useCallback(async () => {
    const p = pending.current;
    if (!p || pauseRef.current) return;
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

  const flush = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    chain.current = chain.current.then(saveOnce);
    return chain.current;
  }, [saveOnce]);

  const change = useCallback(
    (v: T) => {
      pending.current = { v };
      if (!pauseRef.current) setState("dirty");
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void flush(), delay);
    },
    [delay, flush],
  );

  /** Forget unsaved changes (the editor was reset to the server's version). */
  const discard = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    pending.current = null;
    setError(null);
    setState("saved");
  }, []);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      void flush();
    };
  }, [flush]);

  return { change, flush, discard, state, error };
}
