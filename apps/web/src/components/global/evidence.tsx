import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App } from "antd";
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { MAX_PAGE_SIZE, api, errorText, type Evidence, type EvidenceInput, type Job, type Page } from "../../api";
import { useJobCreated } from "../../lib/data";
import { reducedMotion } from "../../theme/motion";
import { Icon, type IconName } from "../Icon";

interface EvidenceState {
  items: Evidence[];
  find: (input: EvidenceInput) => Evidence | undefined;
  toggle: (input: EvidenceInput, from?: HTMLElement | null) => void;
  remove: (id: string) => void;
  capsuleRef: React.RefObject<HTMLButtonElement | null>;
  bump: number;
  error: unknown;
}

const Ctx = createContext<EvidenceState | null>(null);
export const useEvidence = () => useContext(Ctx);

type EvKey = Pick<EvidenceInput, "kind" | "ref" | "text" | "source">;
export function sameEvidence(a: EvKey, b: EvKey): boolean {
  if (a.kind !== b.kind) return false;
  if (a.ref.hit_id || b.ref.hit_id) return a.ref.hit_id === b.ref.hit_id;
  if (a.ref.stat_id || b.ref.stat_id) return a.ref.stat_id === b.ref.stat_id && a.ref.row_key === b.ref.row_key;
  return a.text === b.text && a.source === b.source;
}

function flyTo(from: HTMLElement, to: HTMLElement, text: string): Promise<void> {
  if (reducedMotion() || !from.animate) return Promise.resolve();
  const a = from.getBoundingClientRect();
  const b = to.getBoundingClientRect();
  const f = document.createElement("div");
  f.className = "fly";
  f.textContent = text;
  f.style.transform = `translate(${a.left}px, ${a.top}px)`;
  document.body.appendChild(f);
  const dx = b.left + 30 - a.left;
  const dy = b.top + 10 - a.top;
  const anim = f.animate(
    [
      { transform: `translate(${a.left}px, ${a.top}px) scale(1)`, opacity: 1 },
      { transform: `translate(${a.left + dx * 0.55}px, ${a.top + dy * 0.45 - 70}px) scale(.85)`, opacity: 1, offset: 0.55 },
      { transform: `translate(${a.left + dx}px, ${a.top + dy}px) scale(.3)`, opacity: 0.2 },
    ],
    { duration: 650, easing: "cubic-bezier(.45,0,.25,1)" },
  );
  return anim.finished.then(
    () => f.remove(),
    () => f.remove(),
  );
}

export function EvidenceProvider({ projectId, children }: { projectId: string; children: React.ReactNode }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const capsuleRef = useRef<HTMLButtonElement | null>(null);
  const [bump, setBump] = useState(0);
  const key = ["evidence", projectId];
  const list = useQuery({
    queryKey: key,
    queryFn: () => api.get<Page<Evidence>>(`/projects/${projectId}/evidence`, { page_size: MAX_PAGE_SIZE }),
  });
  const items = useMemo(() => list.data?.items ?? [], [list.data]);

  const add = useMutation({
    mutationFn: (input: EvidenceInput) => api.post<Evidence>(`/projects/${projectId}/evidence`, input),
    onSuccess: (ev) => {
      qc.setQueryData<Page<Evidence>>(key, (old) => (old ? { items: [...old.items, ev], total: old.total + 1 } : old));
      setBump((n) => n + 1);
    },
    onError: (e) => message.error(errorText(e)),
  });
  const del = useMutation({
    mutationFn: (id: string) => api.del(`/evidence/${id}`),
    onSuccess: (_, id) => {
      qc.setQueryData<Page<Evidence>>(key, (old) => (old ? { items: old.items.filter((x) => x.id !== id), total: old.total - 1 } : old));
    },
    onError: (e) => message.error(errorText(e)),
  });

  const find = useCallback((input: EvidenceInput) => items.find((e) => sameEvidence(e, input)), [items]);

  const toggle = useCallback(
    (input: EvidenceInput, from?: HTMLElement | null) => {
      const existing = find(input);
      if (existing) {
        del.mutate(existing.id);
        message.info("已移出证据篮");
        return;
      }
      const flight = from && capsuleRef.current ? flyTo(from, capsuleRef.current, input.text) : Promise.resolve();
      add.mutate(input);
      void flight;
    },
    [find, add, del, message],
  );

  const value: EvidenceState = { items, find, toggle, remove: (id) => del.mutate(id), capsuleRef, bump, error: list.error };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Pin to evidence basket. Renders nothing outside an EvidenceProvider. */
export function PinButton({ input, className }: { input: EvidenceInput; className?: string }) {
  const ev = useEvidence();
  const ref = useRef<HTMLButtonElement>(null);
  if (!ev) return null;
  const on = !!ev.find(input);
  return (
    <button
      ref={ref}
      type="button"
      className={`pin-btn ${on ? "on" : ""} ${className ?? ""}`}
      aria-label={on ? "移出证据篮" : "钉住到证据篮"}
      title={on ? "移出证据篮" : "钉住到证据篮"}
      aria-pressed={on}
      onClick={(e) => {
        e.stopPropagation();
        ev.toggle(input, ref.current);
      }}
    >
      <Icon name="pin" />
    </button>
  );
}

const kindIcon: Record<Evidence["kind"], IconName> = { hit: "quote", stat_row: "chart", text: "spark" };

export function EvidenceBasket({ projectId, open, onToggle }: { projectId: string; open: boolean; onToggle: () => void }) {
  const ev = useEvidence();
  const { message } = App.useApp();
  const jobCreated = useJobCreated();
  const exportJob = useMutation({
    mutationFn: (format: "csv" | "xlsx" | "docx") => api.post<Job>(`/projects/${projectId}/evidence/export`, { format }),
    onSuccess: () => {
      jobCreated(projectId);
      message.success(
        <span>
          已创建导出任务，<Link to={`/p/${projectId}/jobs`}>查看任务</Link>
        </span>,
      );
    },
    onError: (e) => message.error(errorText(e)),
  });
  const [clearing, setClearing] = useState(false);
  if (!ev) return null;
  const n = ev.items.length;

  async function clearAll() {
    if (!ev) return;
    setClearing(true);
    try {
      for (const it of ev.items) await api.del(`/evidence/${it.id}`);
    } catch (e) {
      message.error(errorText(e));
    } finally {
      setClearing(false);
    }
  }

  return (
    <div className="dock-item">
      <div className={`dock-panel ${open ? "open" : ""}`} id="ev-panel" role="dialog" aria-label="证据篮">
        <div className="dp-head">
          <Icon name="basket" size={14} />
          <b className="grow">证据篮</b>
          <span className="small muted num">{n} 条</span>
        </div>
        <div className="dp-body">
          {ev.error ? (
            <div className="alert err" style={{ margin: 6 }}>
              {errorText(ev.error)}
            </div>
          ) : n === 0 ? (
            <div className="empty" style={{ padding: "24px 12px" }}>
              <Icon name="pin" />
              <span className="sm">暂无证据，点行尾的钉住图标添加</span>
            </div>
          ) : (
            ev.items.map((it, i) => (
              <div className="ev-item" key={it.id} style={{ animationDelay: `${i * 30}ms` }}>
                <span className="ev-k">
                  <Icon name={kindIcon[it.kind] ?? "quote"} />
                </span>
                <span className="ev-t" title={it.text}>
                  {it.text}
                </span>
                <button className="pin-btn" type="button" aria-label="移出证据篮" onClick={() => ev.remove(it.id)}>
                  <Icon name="x" />
                </button>
                <span className="ev-s" title={it.source}>
                  {it.source}
                  {it.ref.search_query ? ` · ${it.ref.search_query}` : ""}
                </span>
              </div>
            ))
          )}
        </div>
        <div className="dp-foot">
          <button className="btn xs" type="button" disabled={!n || exportJob.isPending} onClick={() => exportJob.mutate("xlsx")}>
            <Icon name="download" size={14} />
            XLSX
          </button>
          <button className="btn xs" type="button" disabled={!n || exportJob.isPending} onClick={() => exportJob.mutate("docx")}>
            <Icon name="download" size={14} />
            DOCX
          </button>
          <div className="grow" />
          <ClearButton disabled={!n || clearing} onConfirm={clearAll} projectId={projectId} />
        </div>
      </div>
      <button
        ref={ev.capsuleRef}
        className="capsule"
        type="button"
        aria-expanded={open}
        aria-controls="ev-panel"
        onClick={onToggle}
      >
        <Icon name="basket" />
        证据篮
        <span className="cnt bump" key={ev.bump}>
          {n}
        </span>
      </button>
    </div>
  );
}

function ClearButton({ disabled, onConfirm, projectId }: { disabled: boolean; onConfirm: () => Promise<void>; projectId: string }) {
  const qc = useQueryClient();
  const [armed, setArmed] = useState(false);
  return (
    <button
      className="btn xs ghost danger"
      type="button"
      disabled={disabled}
      onBlur={() => setArmed(false)}
      onClick={async () => {
        if (!armed) {
          setArmed(true);
          return;
        }
        setArmed(false);
        await onConfirm();
        qc.invalidateQueries({ queryKey: ["evidence", projectId] });
      }}
    >
      {armed ? "确认清空" : "清空"}
    </button>
  );
}
