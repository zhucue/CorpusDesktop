import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App } from "antd";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { MAX_PAGE_SIZE, api, errorText, type Evidence, type EvidenceInput, type Job, type Page } from "../../api";
import { knowledgeHref } from "../../features/knowledge/data";
import { EVIDENCE_MIME, NotePicker, basketNoteText, evidenceMarkdown, writeEvidenceToNote, type NoteTarget } from "../../features/knowledge/NotePicker";
import { isActiveJob, quietJobs, useJob, useJobCreated } from "../../lib/data";
import { JobDownloadLink, useJobDownload } from "../../lib/download";
import { cpSlice } from "../annot/spans";
import { reducedMotion } from "../../theme/motion";
import { Tip } from "../common";
import { Icon } from "../Icon";
import { evidenceIcon } from "../iconSets";
import { MethodAppendix } from "./MethodAppendix";

interface EvidenceState {
  items: Evidence[];
  /** Items in the project; more than items.length while only the first pages are loaded. */
  total: number;
  loadMore: () => void;
  loading: boolean;
  find: (input: EvidenceInput) => Evidence | undefined;
  toggle: (input: EvidenceInput, from?: HTMLElement | null) => void;
  remove: (id: string) => void;
  capsuleRef: React.RefObject<HTMLButtonElement | null>;
  bump: number;
  error: unknown;
  /** A mounted pin button's key (pinKey); the provider looks such keys up while the basket is partly loaded. */
  watch: (key: string) => () => void;
}

const Ctx = createContext<EvidenceState | null>(null);
export const useEvidence = () => useContext(Ctx);

type EvKey = Pick<EvidenceInput, "kind" | "ref" | "text" | "source">;

/** The api's key of a hit: hit_id, which is "<document id>:<start_cp>-<end_cp>" (also for items saved without it). */
function hitKey(ref: EvidenceInput["ref"]): string | undefined {
  if (ref.hit_id) return ref.hit_id;
  if (ref.document_id && ref.start_cp != null && ref.end_cp != null) return `${ref.document_id}:${ref.start_cp}-${ref.end_cp}`;
  return undefined;
}

export function sameEvidence(a: EvKey, b: EvKey): boolean {
  if (a.kind !== b.kind) return false;
  if (a.kind === "hit" && (hitKey(a.ref) || hitKey(b.ref))) return hitKey(a.ref) === hitKey(b.ref);
  if (a.ref.hit_id || b.ref.hit_id) return a.ref.hit_id === b.ref.hit_id;
  if (a.ref.stat_id || b.ref.stat_id) return a.ref.stat_id === b.ref.stat_id && a.ref.row_key === b.ref.row_key;
  return a.text === b.text && a.source === b.source;
}

/** Lookup key of a pin (POST /evidence/lookup): hits and stat rows; text items have none. */
export function pinKey(input: EvKey): string | null {
  if (input.kind === "hit") {
    const k = hitKey(input.ref);
    return k ? `h:${k}` : null;
  }
  if (input.kind === "stat_row" && input.ref.stat_id && input.ref.row_key != null) return `s:${JSON.stringify([input.ref.stat_id, input.ref.row_key])}`;
  return null;
}

/** Basket items matching pin keys, in requests of at most 500 keys. */
async function lookupEvidence(projectId: string, keys: string[]): Promise<Evidence[]> {
  const out: Evidence[] = [];
  for (let i = 0; i < keys.length; i += 500) {
    const part = keys.slice(i, i + 500);
    const body = {
      hit_ids: part.filter((k) => k.startsWith("h:")).map((k) => k.slice(2)),
      stat_rows: part.filter((k) => k.startsWith("s:")).map((k) => {
        const [stat_id, row_key] = JSON.parse(k.slice(2)) as [string, string];
        return { stat_id, row_key };
      }),
    };
    out.push(...(await api.post<{ items: Evidence[] }>(`/projects/${projectId}/evidence/lookup`, body)).items);
  }
  return out;
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
  // pages of MAX_PAGE_SIZE loaded so far; 加载更多 raises it and refetches pages 1..n under the same key
  const pages = useRef(1);
  const list = useQuery({
    queryKey: key,
    queryFn: async () => {
      let out: Page<Evidence> = { items: [], total: 0 };
      for (let page = 1; page <= pages.current; page++) {
        const p = await api.get<Page<Evidence>>(`/projects/${projectId}/evidence`, { page, page_size: MAX_PAGE_SIZE });
        const seen = new Set(out.items.map((x) => x.id));
        out = { items: [...out.items, ...p.items.filter((x) => !seen.has(x.id))], total: p.total };
        if (page * MAX_PAGE_SIZE >= p.total) break;
      }
      return out;
    },
  });
  const items = useMemo(() => list.data?.items ?? [], [list.data]);
  const total = list.data?.total ?? 0;

  // Pin buttons of rows whose item may sit beyond the loaded pages: one lookup for the keys mounted at a time.
  const watchCounts = useRef(new Map<string, number>());
  const [watched, setWatched] = useState<string[]>([]);
  const watch = useCallback((k: string) => {
    const m = watchCounts.current;
    const sync = () => {
      const next = [...m.keys()].sort();
      setWatched((old) => (old.length === next.length && old.every((x, i) => x === next[i]) ? old : next));
    };
    m.set(k, (m.get(k) ?? 0) + 1);
    sync();
    return () => {
      const n = (m.get(k) ?? 1) - 1;
      if (n > 0) m.set(k, n);
      else m.delete(k);
      sync();
    };
  }, []);
  const partial = !!list.data && total > items.length;
  const lookup = useQuery({
    queryKey: [...key, "lookup", watched],
    enabled: partial && watched.length > 0,
    placeholderData: keepPreviousData,
    meta: { background: true },
    queryFn: () => lookupEvidence(projectId, watched),
  });
  const found = useMemo(() => (partial ? (lookup.data ?? []) : []), [partial, lookup.data]);
  const loadMore = useCallback(() => {
    pages.current = Math.max(pages.current, Math.ceil(items.length / MAX_PAGE_SIZE)) + 1;
    void qc.invalidateQueries({ queryKey: ["evidence", projectId] });
  }, [items.length, qc, projectId]);

  const add = useMutation({
    mutationFn: (input: EvidenceInput) => api.post<Evidence & { existing?: boolean }>(`/projects/${projectId}/evidence`, input),
    onSuccess: (ev) => {
      // The api returns the existing item when this hit is already in the basket (e.g. added by the assistant,
      // or on a page not loaded yet): it joins the loaded items, the project total stays.
      if (ev.existing) message.info("已在证据篮中");
      qc.setQueryData<Page<Evidence>>(key, (old) =>
        old && !old.items.some((x) => x.id === ev.id) ? { items: [...old.items, ev], total: old.total + (ev.existing ? 0 : 1) } : old,
      );
      setBump((n) => n + 1);
    },
    onError: (e) => message.error(errorText(e)),
  });
  const del = useMutation({
    mutationFn: (id: string) => api.del(`/evidence/${id}`),
    onSuccess: (_, id) => {
      // the item may be one found by lookup, outside the loaded pages: the total drops either way
      qc.setQueryData<Page<Evidence>>(key, (old) => (old ? { items: old.items.filter((x) => x.id !== id), total: Math.max(0, old.total - 1) } : old));
      qc.setQueriesData<Evidence[]>({ queryKey: [...key, "lookup"] }, (old) => old?.filter((x) => x.id !== id));
    },
    onError: (e) => message.error(errorText(e)),
  });

  const find = useCallback((input: EvidenceInput) => items.find((e) => sameEvidence(e, input)) ?? found.find((e) => sameEvidence(e, input)), [items, found]);

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

  const value: EvidenceState = { items, total, loadMore, loading: list.isFetching, find, toggle, remove: (id) => del.mutate(id), capsuleRef, bump, error: list.error, watch };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Pin to evidence basket. Renders nothing outside an EvidenceProvider. label: show 钉住 / 已钉 next to the icon. */
export function PinButton({ input, className, label }: { input: EvidenceInput; className?: string; label?: boolean }) {
  const ev = useEvidence();
  const ref = useRef<HTMLButtonElement>(null);
  const k = pinKey(input);
  const watch = ev?.watch;
  useEffect(() => (watch && k ? watch(k) : undefined), [watch, k]);
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
      {label && <span className="act-l">{on ? "已钉" : "钉住"}</span>}
    </button>
  );
}

/** Basket line for one item: a pinned hit shows its sentence with the match in bold and the aligned translations;
 * a statistics row shows 「项」 method value (QA Q60 / Q76). */
function EvidenceBody({ it }: { it: Evidence }) {
  const r = it.ref;
  if (it.kind === "hit" && r.sentence && r.match) {
    const [a, b] = r.match;
    return (
      <>
        <span className="ev-t" title={r.sentence} style={{ whiteSpace: "normal", display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical" }}>
          {cpSlice(r.sentence, 0, a)}
          <b>{cpSlice(r.sentence, a, b)}</b>
          {cpSlice(r.sentence, b)}
        </span>
        {r.aligned?.map((x, i) => (
          <span key={i} className="ev-s" style={{ fontFamily: "inherit", fontSize: 12, whiteSpace: "normal" }}>
            {x.language.toUpperCase()} · {x.text}
          </span>
        ))}
        <span className="ev-s" title={it.source}>
          {it.source}
          {r.search_query ? ` · ${r.search_query}` : ""}
        </span>
      </>
    );
  }
  if (it.kind === "stat_row") {
    // text "项 · 值", source "方法 · 范围" (features/stats/StatTable rowEvidence)
    const m = /^(.*) · ([^·]+)$/.exec(it.text);
    const [method, ...rest] = it.source.split(" · ");
    return (
      <>
        <span className="ev-t" title={it.text}>
          {m ? (
            <>
              「{m[1]}」 {method} <b className="num">{m[2]}</b>
            </>
          ) : (
            it.text
          )}
        </span>
        <span className="ev-s" title={it.source}>
          {m ? rest.join(" · ") : it.source}
        </span>
      </>
    );
  }
  return (
    <>
      <span className="ev-t" title={it.text}>
        {it.text}
      </span>
      <span />
      <span className="ev-s" title={it.source}>
        {it.source}
        {r.search_query ? ` · ${r.search_query}` : ""}
      </span>
    </>
  );
}

/** Basket export as a background job: toast at the top (the dock sits bottom right), download when done. */
function useBasketExport(projectId: string) {
  const { message } = App.useApp();
  const download = useJobDownload();
  const jobCreated = useJobCreated();
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  const start = useMutation({
    mutationFn: (format: "csv" | "xlsx" | "docx") => api.post<Job>(`/projects/${projectId}/evidence/export`, { format }),
    onSuccess: (j, format) => {
      quietJobs.add(j.id);
      setJobId(j.id);
      jobCreated(projectId);
      message.info(`已开始导出 ${format.toUpperCase()}`);
    },
    onError: (e) => message.error(errorText(e)),
  });
  useEffect(() => {
    const j = job.data;
    if (!j || j.id !== jobId || isActiveJob(j)) return;
    setJobId(null);
    if (j.state !== "succeeded") {
      message.error(`导出失败：${j.error?.message ?? "任务已取消"}`);
      return;
    }
    const name = typeof j.result?.filename === "string" ? j.result.filename : "";
    void download(j.id, name);
    message.success({
      content: (
        <span>
          导出完成，
          <JobDownloadLink jobId={j.id} filename={name}>
            下载 {name}
          </JobDownloadLink>
        </span>
      ),
      duration: 6,
    });
  }, [job.data, jobId]); // eslint-disable-line react-hooks/exhaustive-deps
  return { start: start.mutate, busy: start.isPending || !!jobId };
}


export function EvidenceBasket({ projectId, open, onToggle }: { projectId: string; open: boolean; onToggle: () => void }) {
  const ev = useEvidence();
  const { message } = App.useApp();
  const exportJob = useBasketExport(projectId);
  const [clearing, setClearing] = useState(false);
  const [picking, setPicking] = useState(false);
  const [appendix, setAppendix] = useState(false);
  if (!ev) return null;
  const n = ev.items.length;

  /** One evidence ref per item; the API appends each quote block once (Q58). */
  async function toNote(t: NoteTarget) {
    const { note, added, skipped } = await writeEvidenceToNote(projectId, t, ev!.items);
    message[added ? "success" : "info"](
      <span>
        {basketNoteText(note.title, added, skipped)}，<Link to={knowledgeHref(projectId, { tab: "notes", doc: note.id })}>打开笔记</Link>
      </span>,
    );
  }

  /** Only the current user's items (DELETE ?mine=true); other members' pins stay. */
  async function clearMine() {
    setClearing(true);
    try {
      await api.del(`/projects/${projectId}/evidence?mine=true`);
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
          <span className="small muted num">{ev.total > n ? `显示 ${n} / 共 ${ev.total}` : `${n} 条`}</span>
        </div>
        <div className="dp-body">
          {ev.error ? (
            <div className="alert err" style={{ margin: 6 }}>
              {errorText(ev.error)}
            </div>
          ) : n === 0 ? (
            <div className="empty" style={{ padding: "24px 12px" }}>
              <span className="empty-ic" aria-hidden>
                <Icon name="pin" size={20} />
              </span>
              <span className="sm">暂无证据，点行尾的钉住图标添加</span>
            </div>
          ) : (
            ev.items.map((it, i) => (
              <div
                className="ev-item"
                key={it.id}
                style={{ animationDelay: `${i * 30}ms` }}
                draggable
                onDragStart={(e) => {
                  // drop into a note editor: Markdown quote as text, the item for the 引用 record
                  e.dataTransfer.setData("text/plain", `\n\n${evidenceMarkdown(it)}\n\n`);
                  e.dataTransfer.setData(EVIDENCE_MIME, JSON.stringify({ id: it.id, text: it.text, source: it.source, ref: it.ref }));
                  e.dataTransfer.effectAllowed = "copy";
                }}
              >
                <span className="ev-k">
                  <Icon name={evidenceIcon[it.kind] ?? "quote"} />
                </span>
                <EvidenceBody it={it} />
                <span style={{ gridColumn: 3, gridRow: 1 }}>
                  <Tip title="移出证据篮">
                    <button className="pin-btn" type="button" aria-label="移出证据篮" onClick={() => ev.remove(it.id)}>
                      <Icon name="x" />
                    </button>
                  </Tip>
                </span>
              </div>
            ))
          )}
          {!ev.error && ev.total > n && (
            <div className="row" style={{ justifyContent: "center", padding: 8 }}>
              <button className="btn xs" type="button" disabled={ev.loading} onClick={ev.loadMore}>
                加载更多
              </button>
            </div>
          )}
        </div>
        <div className="dp-foot">
          <button className="btn xs" type="button" disabled={!n} onClick={() => setPicking(true)}>
            <Icon name="note" size={14} />
            加入笔记
          </button>
          <button className="btn xs" type="button" disabled={!n || exportJob.busy} onClick={() => exportJob.start("xlsx")}>
            <Icon name="download" size={14} />
            XLSX
          </button>
          <button className="btn xs" type="button" disabled={!n || exportJob.busy} onClick={() => exportJob.start("docx")}>
            <Icon name="download" size={14} />
            DOCX
          </button>
          <button className="btn xs" type="button" disabled={!n} onClick={() => setAppendix(true)}>
            <Icon name="filetext" size={14} />
            生成方法附录
          </button>
          <div className="grow" />
          <ClearButton disabled={!ev.total || clearing} onConfirm={clearMine} projectId={projectId} />
        </div>
      </div>
      {appendix && <MethodAppendix projectId={projectId} evidence onClose={() => setAppendix(false)} />}
      <NotePicker open={picking} projectId={projectId} title={`加入笔记 · ${n} 条证据`} defaultTitle="证据摘录" onClose={() => setPicking(false)} onPick={toNote} />
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
          {ev.total}
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
      {armed ? "确认清空我钉的" : "清空我钉的"}
    </button>
  );
}
