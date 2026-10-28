import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Drawer, Popconfirm } from "antd";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { api, errorText, type Job, type KbChunk, type KbDocument, type Page } from "../../api";
import { Empty, ErrorAlert, Progress, Skeleton } from "../../components/common";
import { Markdown } from "../../components/common/Markdown";
import { Icon } from "../../components/Icon";
import { kbDocIcon } from "../../components/iconSets";
import { useJob, useJobCreated } from "../../lib/data";
import { fmt, fmtBytes, fmtShortTime, fmtTime } from "../../lib/format";
import {
  ACCEPT_KB,
  MAX_KB_BYTES,
  docType,
  importJobOf,
  importJobs,
  isBusyDoc,
  kindLabels,
  locatorText,
  statusView,
  uploadKbFiles,
  useKbDocument,
} from "./data";

const EXT = /\.(pdf|docx|md|markdown|txt)$/i;

export function DocStatusTag({ doc }: { doc: KbDocument }) {
  const v = statusView[doc.status] ?? { label: doc.status, cls: "t-gray" };
  return (
    <span className={`tag ${v.cls}`} title={doc.error ?? undefined}>
      {v.busy && <span className="spin" style={{ width: 9, height: 9 }} />}
      {v.label}
    </span>
  );
}

/** Status cell: tag plus the import job's progress while it runs. */
function DocStatus({ doc }: { doc: KbDocument }) {
  const busy = isBusyDoc(doc);
  const job = useJob(busy ? importJobOf(doc) : null, 2000);
  const p = job.data?.progress;
  return (
    <div className="col" style={{ gap: 4, alignItems: "flex-start" }}>
      <DocStatusTag doc={doc} />
      {busy && p && (
        <div style={{ width: 110 }}>
          <Progress done={p.done} total={p.total} state={job.data?.state} thin />
        </div>
      )}
    </div>
  );
}

type StageState = "" | "done" | "run" | "fail";

/** 解析 → 分段 → 向量化 from the document status (failure lands on the stage that had no output). */
function stagesOf(doc: KbDocument): StageState[] {
  switch (doc.status) {
    case "parsing":
      return ["run", "", ""];
    case "embedding":
      return ["done", "done", "run"];
    case "ready":
      return ["done", "done", "done"];
    case "failed":
      return doc.chunk_count > 0 ? ["done", "done", "fail"] : ["fail", "", ""];
    default:
      return ["", "", ""];
  }
}

function Pipe({ doc, size, editable, onRetry }: { doc: KbDocument; size?: number; editable: boolean; onRetry: () => void }) {
  const job = useJob(isBusyDoc(doc) ? importJobOf(doc) : null, 2000);
  const st = stagesOf(doc);
  const p = job.data?.progress;
  const nums = [
    doc.meta?.pages ? `${doc.meta.pages} 页` : "",
    doc.chunk_count ? fmt(doc.chunk_count) : "",
    doc.status === "ready" ? fmt(doc.chunk_count) : doc.status === "embedding" && p ? (p.total ? `${fmt(p.done)}/${fmt(p.total)}` : fmt(p.done)) : "",
  ];
  const names = ["解析", "分段", "向量化"];
  return (
    <div className="pipe">
      <div className="row between sm">
        <b style={{ fontWeight: 500 }} className="ellipsis">
          {doc.title}
        </b>
        {size != null && <span className="mono small muted">{fmtBytes(size)}</span>}
      </div>
      <div className="stages">
        {st.map((s, i) => (
          <span key={i} className={`stage ${s}`}>
            {s === "done" && <Icon name="check" size={12} />}
            {s === "run" && <span className="spin" style={{ width: 10, height: 10 }} />}
            {s === "fail" && <Icon name="x" size={12} />}
            {s === "" && <Icon name="clock" size={12} />}
            {s === "fail" ? `${names[i]}失败` : names[i]}
            {s !== "fail" && nums[i] && <span className="num">{nums[i]}</span>}
          </span>
        ))}
      </div>
      {doc.status === "failed" && (
        <div className="row small" style={{ color: "var(--err)" }}>
          <Icon name="alert" size={14} />
          <span className="grow">{doc.error || "导入失败"}</span>
          {editable && (
            <button className="btn xs" type="button" onClick={onRetry}>
              <Icon name="retry" size={14} />
              重试
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function useReimport(projectId: string) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const jobCreated = useJobCreated();
  return useMutation({
    mutationFn: (id: string) => api.post<Job>(`/kb/documents/${id}/reimport`),
    onSuccess: (job, id) => {
      importJobs.set(id, job.id);
      jobCreated(projectId);
      void qc.invalidateQueries({ queryKey: ["kb-docs", projectId] });
      void qc.invalidateQueries({ queryKey: ["kb-doc", id] });
      message.success("已重新导入");
    },
    onError: (e) => message.error(errorText(e)),
  });
}

/** Dropzone + URL import + pipelines of the imports that are running, failed or started here. */
export function ImportCard({ projectId, docs, editable }: { projectId: string; docs: KbDocument[]; editable: boolean }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const jobCreated = useJobCreated();
  const [drag, setDrag] = useState(false);
  const [url, setUrl] = useState("");
  const [sizes, setSizes] = useState<Record<string, number>>({});
  const [recent, setRecent] = useState<string[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const reimport = useReimport(projectId);

  const done = (list: KbDocument[]) => {
    for (const d of list) if (d.job_id) importJobs.set(d.id, d.job_id);
    setRecent((r) => [...list.map((d) => d.id), ...r]);
    qc.setQueryData<KbDocument[]>(["kb-docs", projectId], (old) => (old ? [...list, ...old.filter((x) => !list.some((d) => d.id === x.id))] : old));
    void qc.invalidateQueries({ queryKey: ["kb-docs", projectId] });
    jobCreated(projectId);
  };

  const upload = useMutation({
    mutationFn: (files: File[]) => uploadKbFiles(projectId, files),
    onSuccess: (list, files) => {
      const s: Record<string, number> = {};
      list.forEach((d, i) => {
        const f = files.find((x) => x.name === d.source || x.name === d.title) ?? files[i];
        if (f) s[d.id] = f.size;
      });
      setSizes((o) => ({ ...o, ...s }));
      done(list);
      message.success(`已提交 ${list.length} 个文件`);
    },
    onError: (e) => message.error(errorText(e)),
  });

  const addUrl = useMutation({
    mutationFn: (u: string) => api.post<KbDocument>(`/projects/${projectId}/kb/documents`, { url: u }),
    onSuccess: (d) => {
      done([d]);
      setUrl("");
      message.success("已提交网页导入");
    },
    onError: (e) => message.error(errorText(e)),
  });

  function pick(list: FileList | null) {
    const files = Array.from(list ?? []);
    if (!files.length) return;
    const bad = files.filter((f) => !EXT.test(f.name));
    const big = files.filter((f) => EXT.test(f.name) && f.size > MAX_KB_BYTES);
    if (bad.length) message.error(`不支持的文件格式：${bad.map((f) => f.name).join("、")}`);
    if (big.length) message.error(`文件超过 50 MB：${big.map((f) => f.name).join("、")}`);
    const ok = files.filter((f) => EXT.test(f.name) && f.size <= MAX_KB_BYTES);
    if (ok.length) upload.mutate(ok);
    if (input.current) input.current.value = "";
  }

  const literature = docs.filter((d) => d.kind === "literature" || d.kind === "url");
  const shown = literature.filter((d) => isBusyDoc(d) || d.status === "failed" || recent.includes(d.id)).slice(0, 8);

  return (
    <div className="card" id="kb-import">
      <div className="card-head">
        <h2>导入</h2>
      </div>
      <div className="card-pad col gap-12">
        {editable ? (
          <>
            <label
              className={`dropzone ${drag ? "drag" : ""}`}
              htmlFor="kb-file"
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDrag(false);
                pick(e.dataTransfer.files);
              }}
            >
              {upload.isPending ? <span className="spin" /> : <Icon name="upload" size={20} />}
              <b style={{ fontWeight: 600, color: "var(--text)" }}>拖入文件或点击选择</b>
              <span className="small muted">PDF · DOCX · Markdown · TXT，单个 ≤ 50 MB</span>
              <input id="kb-file" ref={input} type="file" className="sr-only" multiple accept={ACCEPT_KB} onChange={(e) => pick(e.target.files)} />
            </label>
            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault();
                const u = url.trim();
                if (!/^https?:\/\/\S+$/i.test(u)) {
                  message.error("请输入以 http:// 或 https:// 开头的网页链接");
                  return;
                }
                addUrl.mutate(u);
              }}
            >
              <label htmlFor="kb-url" className="sr-only">
                网页链接
              </label>
              <input className="input s" id="kb-url" placeholder="或粘贴网页链接" value={url} onChange={(e) => setUrl(e.target.value)} />
              <button className="btn s" type="submit" disabled={!url.trim() || addUrl.isPending}>
                添加
              </button>
            </form>
          </>
        ) : (
          <div className="muted sm">查看者不能导入文献</div>
        )}
        {shown.length > 0 && (
          <div>
            {shown.map((d) => (
              <Pipe key={d.id} doc={d} size={sizes[d.id]} editable={editable} onRetry={() => reimport.mutate(d.id)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function DocTable({ docs, onOpen, loading, error }: { docs: KbDocument[]; onOpen: (id: string) => void; loading: boolean; error: unknown }) {
  const literature = docs.filter((d) => d.kind === "literature" || d.kind === "url");
  return (
    <div className="card">
      <div className="card-head">
        <h2>文献</h2>
        <div className="grow" />
        <span className="small muted num">{fmt(literature.length)} 篇</span>
      </div>
      <ErrorAlert error={error} style={{ margin: 16 }} />
      {loading ? (
        <Skeleton rows={5} />
      ) : literature.length === 0 ? (
        <Empty icon="bookopentext" text="还没有文献，拖入文件或粘贴网页链接导入" />
      ) : (
        <table className="tbl mid">
          <thead>
            <tr>
              <th>标题</th>
              <th>类型</th>
              <th className="r">片段</th>
              <th>导入</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody className="stagger">
            {literature.map((d, i) => (
              <tr key={d.id} style={{ ["--i" as string]: i, cursor: "pointer" }} onClick={() => onOpen(d.id)}>
                <td>
                  <button type="button" className="linkish" onClick={() => onOpen(d.id)}>
                    {d.title}
                  </button>
                </td>
                <td className="mono small">
                  <span className="row gap-4">
                    <Icon name={kbDocIcon(d.kind, d.source, d.title)} size={14} className="muted" />
                    {docType(d)}
                  </span>
                </td>
                <td className="r num">{d.chunk_count ? fmt(d.chunk_count) : <span className="muted">—</span>}</td>
                <td className="mono small muted">{fmtShortTime(d.created_at)}</td>
                <td>
                  <DocStatus doc={d} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/* ---------- drawer ---------- */

function useChunks(docId: string | null) {
  return useInfiniteQuery({
    queryKey: ["kb-chunks", docId],
    queryFn: async ({ pageParam }) => {
      const r = await api.get<KbChunk[] | Page<KbChunk>>(`/kb/documents/${docId}/chunks`, { page: pageParam });
      return Array.isArray(r) ? { items: r, total: null as number | null } : { items: r.items ?? [], total: r.total ?? null };
    },
    initialPageParam: 1,
    getNextPageParam: (last, all, lastPage) => {
      const loaded = all.reduce((n, p) => n + p.items.length, 0);
      return last.total != null && last.items.length > 0 && loaded < last.total ? lastPage + 1 : undefined;
    },
    enabled: !!docId,
  });
}

function Summary({ doc, editable }: { doc: KbDocument; editable: boolean }) {
  const qc = useQueryClient();
  const jobCreated = useJobCreated();
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId, 1500);
  const start = useMutation({
    mutationFn: () => api.post<Job>(`/kb/documents/${doc.id}/summarize`),
    onSuccess: (j) => {
      setJobId(j.id);
      jobCreated(doc.project_id);
    },
  });
  const state = job.data?.state;
  useEffect(() => {
    if (state === "succeeded") {
      void qc.invalidateQueries({ queryKey: ["kb-doc", doc.id] });
      void qc.invalidateQueries({ queryKey: ["kb-docs", doc.project_id] });
    }
  }, [state, qc, doc.id, doc.project_id]);
  const running = start.isPending || state === "queued" || state === "running";
  const summary = doc.meta?.summary;
  return (
    <section className="col" style={{ gap: 8 }}>
      <div className="row">
        <span className="label grow">摘要</span>
        {summary && doc.meta?.summary_source === "model" && <span className="tag t-info">模型生成</span>}
        {editable && doc.status === "ready" && (
          <button className="btn xs" type="button" disabled={running} onClick={() => start.mutate()}>
            {running ? <span className="spin" style={{ width: 10, height: 10 }} /> : <Icon name="spark" size={14} />}
            {running ? "生成中" : summary ? "重新摘要" : "摘要"}
          </button>
        )}
      </div>
      <ErrorAlert error={start.error} />
      {state === "failed" && <div className="alert err">{job.data?.error?.message ?? "摘要失败"}</div>}
      {summary ? <Markdown text={summary} /> : !running && <span className="muted sm">暂无摘要</span>}
    </section>
  );
}

export function DocDrawer({
  docId,
  chunkId,
  editable,
  onClose,
}: {
  docId: string | null;
  chunkId?: string | null;
  editable: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const doc = useKbDocument(docId);
  const d = doc.data;
  const chunks = useChunks(d && d.status === "ready" ? d.id : null);
  const reimport = useReimport(d?.project_id ?? "");
  const del = useMutation({
    mutationFn: () => api.del(`/kb/documents/${docId}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["kb-docs"] });
      message.success("已删除");
      onClose();
    },
    onError: (e) => message.error(errorText(e)),
  });
  const list = chunks.data?.pages.flatMap((p) => p.items) ?? [];
  const found = !!chunkId && list.some((c) => String(c.id) === chunkId); // ids are JSON numbers (bigint), the URL param a string

  // Load pages until the target chunk shows up, then scroll to it.
  useEffect(() => {
    if (!chunkId || found || !chunks.hasNextPage || chunks.isFetchingNextPage) return;
    void chunks.fetchNextPage();
  }, [chunkId, found, chunks]);
  useEffect(() => {
    if (!found) return;
    const t = setTimeout(() => document.getElementById(`chunk-${chunkId}`)?.scrollIntoView({ block: "center", behavior: "smooth" }), 250);
    return () => clearTimeout(t);
  }, [found, chunkId]);

  return (
    <Drawer
      open={!!docId}
      onClose={onClose}
      width={640}
      destroyOnHidden
      title={
        d && (
          <span className="row" style={{ minWidth: 0 }}>
            <span className="ellipsis">{d.title}</span>
            <span className="tag t-gray">
              <Icon name={kbDocIcon(d.kind, d.source, d.title)} size={12} />
              {kindLabels[d.kind]}
            </span>
            <DocStatusTag doc={d} />
          </span>
        )
      }
      extra={
        d &&
        editable && (
          <span className="row" style={{ gap: 6 }}>
            {(d.kind === "literature" || d.kind === "url") && (
              <button className="btn s" type="button" disabled={reimport.isPending || isBusyDoc(d)} onClick={() => reimport.mutate(d.id)}>
                <Icon name="retry" size={14} />
                重新导入
              </button>
            )}
            <Popconfirm title="删除这篇文档及其片段？" okText="删除" cancelText="取消" onConfirm={() => del.mutate()}>
              <button className="btn s danger" type="button">
                <Icon name="trash" size={14} />
                删除
              </button>
            </Popconfirm>
          </span>
        )
      }
    >
      {doc.isPending && <Skeleton />}
      <ErrorAlert error={doc.error} />
      {d && (
        <div className="col gap-20">
          <dl className="kv">
            <dt>来源</dt>
            <dd className="mono small">{/^https?:\/\//i.test(d.source) ? <a href={d.source} target="_blank" rel="noreferrer">{d.source}</a> : d.source}</dd>
            {d.meta?.author && (
              <>
                <dt>作者</dt>
                <dd>{String(d.meta.author)}</dd>
              </>
            )}
            {d.meta?.year != null && (
              <>
                <dt>年份</dt>
                <dd className="num">{String(d.meta.year)}</dd>
              </>
            )}
            {d.meta?.pages != null && (
              <>
                <dt>页数</dt>
                <dd className="num">{fmt(d.meta.pages)}</dd>
              </>
            )}
            <dt>片段</dt>
            <dd className="num">{fmt(d.chunk_count)}</dd>
            <dt>导入</dt>
            <dd className="num">{fmtTime(d.created_at)}</dd>
          </dl>
          {d.status === "failed" && (
            <div className="alert err" role="alert">
              <Icon name="alert" size={14} />
              <span>{d.error || "导入失败"}</span>
            </div>
          )}
          {isBusyDoc(d) && (
            <div className="alert info">
              <span className="spin" style={{ width: 12, height: 12 }} />
              <span>
                正在处理，<Link to={`/p/${d.project_id}/jobs`}>查看任务</Link>
              </span>
            </div>
          )}
          <Summary doc={d} editable={editable} />
          <section className="col" style={{ gap: 8 }}>
            <div className="row">
              <span className="label grow">片段</span>
              <span className="small muted num">{fmt(d.chunk_count)}</span>
            </div>
            <ErrorAlert error={chunks.error} />
            {chunks.isPending && d.status === "ready" && <Skeleton rows={3} />}
            {list.length === 0 && !chunks.isPending && d.text_preview && <p className="sm sub" style={{ whiteSpace: "pre-wrap" }}>{d.text_preview}</p>}
            {list.map((c) => (
              <div key={c.id} id={`chunk-${c.id}`} className={`chunk ${String(c.id) === chunkId ? "on" : ""}`}>
                <div className="row small muted">
                  <span className="mono">#{c.ordinal + 1}</span>
                  <span className="mono grow ellipsis">{locatorText(c.locator)}</span>
                </div>
                <p>{c.text}</p>
              </div>
            ))}
            {chunks.hasNextPage && (
              <button className="btn s" type="button" disabled={chunks.isFetchingNextPage} onClick={() => void chunks.fetchNextPage()}>
                加载更多
              </button>
            )}
          </section>
        </div>
      )}
    </Drawer>
  );
}
