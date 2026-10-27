import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Popconfirm } from "antd";
import { useState } from "react";
import { Link } from "react-router";
import { api, errorText, type Job, type KbDocument, type KbLocator, type NoteRef } from "../../api";
import { Empty, ErrorAlert, QueryChip, Skeleton } from "../../components/common";
import { Markdown } from "../../components/common/Markdown";
import { searchHref } from "../../components/global/CommandPalette";
import { Icon, type IconName } from "../../components/Icon";
import { useJobCreated } from "../../lib/data";
import { fmtShortTime } from "../../lib/format";
import { useAutosave, type SaveState } from "./autosave";
import { createNote, knowledgeHref, locatorText, useKbDocument } from "./data";

const str = (v: unknown) => (typeof v === "string" ? v : v == null ? "" : String(v));

export const refIcon: Record<NoteRef["kind"], IconName> = { search: "search", stat: "chart", evidence: "pin", chunk: "book", term: "term" };
const refKindLabel: Record<NoteRef["kind"], string> = { search: "检索", stat: "统计", evidence: "证据", chunk: "知识片段", term: "术语" };

/** Where a note reference points: search, stats, the knowledge page (chunk / term). */
export function refHref(projectId: string, r: NoteRef): string | null {
  const x = r.ref ?? {};
  const q = str(x.search_query ?? x.query);
  switch (r.kind) {
    case "search":
      return q ? searchHref(projectId, q, x.scope) : null;
    case "stat":
      return x.stat_id ? `/p/${projectId}/stats?stat=${encodeURIComponent(str(x.stat_id))}` : null;
    case "evidence":
      if (x.stat_id) return `/p/${projectId}/stats?stat=${encodeURIComponent(str(x.stat_id))}`;
      return q ? searchHref(projectId, q, x.scope) : null;
    case "chunk":
      return x.document_id ? knowledgeHref(projectId, { doc: str(x.document_id), chunk: str(x.chunk_id) }) : null;
    case "term":
      return x.term_id ? knowledgeHref(projectId, { tab: "terms", term: str(x.term_id), tq: str(x.term) }) : null;
    default:
      return null;
  }
}

function refText(r: NoteRef): React.ReactNode {
  const x = r.ref ?? {};
  const q = str(x.search_query ?? x.query);
  if (r.kind === "search" && q) return <QueryChip q={q} />;
  if (r.kind === "stat") return str(x.title ?? x.method) || `#${str(x.stat_id).slice(0, 8)}`;
  if (r.kind === "chunk") return [str(x.title), locatorText(x.locator as KbLocator | string | null)].filter(Boolean).join(" · ") || str(x.text).slice(0, 60) || "片段";
  if (r.kind === "term") return str(x.term) || "术语";
  return str(x.text).slice(0, 80) || str(x.source) || q || refKindLabel[r.kind];
}

const saveLabel: Record<SaveState, string> = { saved: "已保存", dirty: "未保存", saving: "保存中", error: "保存失败" };

/** Title + Markdown body with 1 s autosave, explicit 保存, preview, refs and export. */
export function NoteEditor({ note, editable }: { note: KbDocument; editable: boolean }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const jobCreated = useJobCreated();
  const [title, setTitle] = useState(note.title);
  const [body, setBody] = useState(note.body ?? "");
  const [preview, setPreview] = useState(!editable);
  const auto = useAutosave(async (v: { title: string; body: string }) => {
    const saved = await api.patch<KbDocument>(`/kb/documents/${note.id}`, { title: v.title.trim() || "未命名笔记", body: v.body });
    qc.setQueryData<KbDocument>(["kb-doc", note.id], (old) => (old ? { ...old, ...saved, body: v.body } : old));
    qc.setQueryData<KbDocument[]>(["kb-docs", note.project_id], (old) => old?.map((d) => (d.id === note.id ? { ...d, title: saved.title ?? v.title, updated_at: saved.updated_at ?? d.updated_at } : d)));
  }, 1000);
  const exportJob = useMutation({
    mutationFn: async (format: "docx" | "md") => {
      await auto.flush();
      return api.post<Job>(`/kb/documents/${note.id}/export`, { format });
    },
    onSuccess: () => {
      jobCreated(note.project_id);
      message.success(
        <span>
          已创建导出任务，<Link to={`/p/${note.project_id}/jobs`}>查看任务</Link>
        </span>,
      );
    },
    onError: (e) => message.error(errorText(e)),
  });
  const del = useMutation({
    mutationFn: () => api.del(`/kb/documents/${note.id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["kb-docs", note.project_id] });
      message.success("已删除");
    },
    onError: (e) => message.error(errorText(e)),
  });
  const refs = note.refs ?? [];

  return (
    <div className="col" style={{ gap: 16 }}>
      <article className="card">
        <div className="card-head">
          {editable ? (
            <input
              className="note-title"
              value={title}
              aria-label="笔记标题"
              onChange={(e) => {
                setTitle(e.target.value);
                auto.change({ title: e.target.value, body });
              }}
            />
          ) : (
            <b className="grow">{title}</b>
          )}
          <div className="seg-mini" role="tablist" aria-label="视图">
            {editable && (
              <button type="button" role="tab" aria-selected={!preview} onClick={() => setPreview(false)}>
                编辑
              </button>
            )}
            <button type="button" role="tab" aria-selected={preview} onClick={() => setPreview(true)}>
              预览
            </button>
          </div>
        </div>
        <div className="card-pad">
          {preview ? (
            body.trim() ? <Markdown text={body} /> : <span className="muted sm">空笔记</span>
          ) : (
            <textarea
              className="md-input"
              aria-label="笔记正文"
              value={body}
              placeholder="Markdown"
              onChange={(e) => {
                setBody(e.target.value);
                auto.change({ title, body: e.target.value });
              }}
            />
          )}
        </div>
        <div className="card-foot">
          {editable && (
            <>
              <span className={`small ${auto.state === "error" ? "" : "muted"}`} style={auto.state === "error" ? { color: "var(--err)" } : undefined} data-testid="save-state">
                {saveLabel[auto.state]}
                {auto.state === "error" && auto.error ? `：${errorText(auto.error)}` : ""}
              </span>
              <button className="btn s" type="button" disabled={auto.state === "saved" || auto.state === "saving"} onClick={() => void auto.flush()}>
                保存
              </button>
            </>
          )}
          <div className="grow" />
          <span className="small muted">更新于 {fmtShortTime(note.updated_at)}</span>
          <button className="btn s" type="button" disabled={exportJob.isPending} onClick={() => exportJob.mutate("docx")}>
            <Icon name="download" size={14} />
            DOCX
          </button>
          <button className="btn s" type="button" disabled={exportJob.isPending} onClick={() => exportJob.mutate("md")}>
            <Icon name="download" size={14} />
            Markdown
          </button>
          {editable && (
            <Popconfirm title="删除这篇笔记？" okText="删除" cancelText="取消" onConfirm={() => del.mutate()}>
              <button className="btn s ghost danger" type="button" aria-label="删除笔记">
                <Icon name="trash" size={14} />
              </button>
            </Popconfirm>
          )}
        </div>
      </article>
      <section className="card" aria-label="引用">
        <div className="card-head">
          <h2>引用</h2>
          <div className="grow" />
          <span className="small muted num">{refs.length}</span>
        </div>
        {refs.length === 0 ? (
          <div className="empty sm">暂无引用。证据篮"加入笔记"或助手保存的内容会出现在这里</div>
        ) : (
          <div className="card-pad col" style={{ gap: 6, paddingTop: 10 }}>
            {refs.map((r, i) => {
              const href = refHref(note.project_id, r);
              return (
                <div className="ref-row" key={i}>
                  <Icon name={refIcon[r.kind] ?? "link"} size={14} />
                  <span className="tag t-gray">{refKindLabel[r.kind] ?? r.kind}</span>
                  <span className="grow ellipsis">{href ? <Link to={href}>{refText(r)}</Link> : refText(r)}</span>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

function NotePane({ noteId, editable }: { noteId: string; editable: boolean }) {
  const note = useKbDocument(noteId);
  if (note.error) return <ErrorAlert error={note.error} />;
  if (!note.data) return <div className="card"><Skeleton rows={6} /></div>;
  return <NoteEditor key={note.data.id} note={note.data} editable={editable} />;
}

export default function NotesTab({
  projectId,
  docs,
  editable,
  selected,
  onSelect,
}: {
  projectId: string;
  docs: KbDocument[];
  editable: boolean;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const notes = docs.filter((d) => d.kind === "note").sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const current = selected && notes.some((n) => n.id === selected) ? selected : (notes[0]?.id ?? null);
  const create = useMutation({
    mutationFn: () => createNote(projectId, "未命名笔记", ""),
    onSuccess: (n) => {
      qc.setQueryData<KbDocument[]>(["kb-docs", projectId], (old) => (old ? [n, ...old] : old));
      void qc.invalidateQueries({ queryKey: ["kb-docs", projectId] });
      onSelect(n.id);
    },
    onError: (e) => message.error(errorText(e)),
  });
  return (
    <section className="kb-split">
      <div className="card" style={{ padding: 10 }}>
        {editable && (
          <button className="btn s p" type="button" style={{ width: "100%", marginBottom: 6 }} disabled={create.isPending} onClick={() => create.mutate()}>
            <Icon name="plus" size={14} />
            新建笔记
          </button>
        )}
        {notes.length === 0 && <div className="empty sm">暂无笔记</div>}
        {notes.map((n) => (
          <button key={n.id} className={`list-item ${n.id === current ? "on" : ""}`} type="button" style={{ width: "100%" }} onClick={() => onSelect(n.id)}>
            <span className="grow" style={{ textAlign: "left" }}>
              <span className="li-title ellipsis" style={{ display: "block" }}>
                {n.title || "未命名笔记"}
              </span>
              <span className="small muted mono">{fmtShortTime(n.updated_at)}</span>
            </span>
          </button>
        ))}
      </div>
      {current ? <NotePane key={current} noteId={current} editable={editable} /> : <Empty icon="note" text="新建一篇笔记，或从证据篮、助手保存内容" />}
    </section>
  );
}
