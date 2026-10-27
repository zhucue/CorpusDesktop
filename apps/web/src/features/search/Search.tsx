import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Form, Input, Modal, Select } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import {
  ApiError,
  api,
  errorText,
  type Counts,
  type Hit,
  type Job,
  type MetadataField,
  type ParseResult,
  type SavedQuery,
  type Scope,
  type SearchRequest,
  type SearchResult,
  type SearchScope,
} from "../../api";
import { Count, ErrorAlert, Empty, QueryChip, Sparkline, Tip } from "../../components/common";
import { Icon } from "../../components/Icon";
import { conditionTerms, hasPos, KwicTable, type KwicRow } from "../../components/results/Kwic";
import { PageHeader } from "../../components/shell/AppShell";
import { useShell } from "../../components/shell/shell";
import { describeScope, useCorpora, useJobCreated, useProjectId, useSubcorpora } from "../../lib/data";
import { fmt, fmtShortTime } from "../../lib/format";
import { posLegend } from "../../lib/pos";
import { distRows, type DistRow } from "../stats/columns";
import { useStatJob } from "../stats/useStatJob";
import { defaultLayer, useLayers } from "../annotate/data";
import ContextInspector, { hitEvidence } from "./ContextInspector";
import SentenceTree from "./SentenceTree";
import TermExampleButton from "../knowledge/TermExampleButton";
import { useDebounced } from "../../lib/useDebounced";
import { loadHistory, pushHistory, type HistoryEntry } from "./history";
import "./search.css";

const PAGE_SIZE = 50;
const COUNT_POLL_MS = 3000;
const COUNT_POLL_MAX = 20; // 3 s × 20 = 1 min

const CHIPS: [string, string, string][] = [
  ["词/n", "/n", "词 + 词性"],
  ["$3", " $3 ", "中间最多 3 个词"],
  ["$2-5", " $2-5 ", "中间 2 到 5 个词"],
  ["|", "|", "或"],
  ["+条件", " +", "同句须出现"],
  ["-排除", " -", "同句不出现"],
  ['"精确"', '""', "精确词形"],
  ["*", "*", "任意词"],
  ["?", "?", "任意单字"],
  ["{pos=}", "{pos=}", "词性属性，可接在词后"],
  ["{dep=}", "{dep=}", "依存关系，可接在词后"],
  ["{lemma=}", "{lemma=}", "词元"],
];

const isExpired = (e: unknown) => e instanceof ApiError && e.code === "SEARCH_EXPIRED";
function withoutSearchId(r: SearchRequest): SearchRequest {
  const { search_id: _ignored, ...rest } = r;
  return rest;
}

/** Insert `snippet` at the caret; "" places the caret between the quotes, {k=} before the brace. */
export function insertAt(value: string, start: number, end: number, snippet: string): { value: string; caret: number } {
  const next = value.slice(0, start) + snippet + value.slice(end);
  const caret = snippet === '""' ? start + 1 : snippet.endsWith("=}") ? start + snippet.length - 1 : start + snippet.length;
  return { value: next, caret };
}

const ATTR_NAMES: Record<string, string> = { pos: "词性", dep: "依存", lemma: "词元" };

/** Token attribute constraints in a query: {pos=v,dep=root} → [["pos","v"],["dep","root"]]. */
export function attrPairs(q: string): [string, string][] {
  const out: [string, string][] = [];
  for (const m of q.matchAll(/\{([^{}]*)\}/g))
    for (const part of m[1].split(",")) {
      const eq = part.indexOf("=");
      if (eq > 0) out.push([part.slice(0, eq).trim(), part.slice(eq + 1).trim()]);
    }
  return out;
}

export function ParseLine({ query, parse, error }: { query: string; parse: ParseResult | undefined; error: unknown }) {
  if (!query) return <span className="muted">输入查询式</span>;
  if (error) return <span className="bad">{errorText(error)}</span>;
  if (!parse) return null;
  if (!parse.ok && parse.error) {
    const chars = Array.from(query);
    const p = parse.error.position;
    return (
      <>
        <span className="bad">
          <Icon name="alert" size={14} />第 {p + 1} 个字符：{parse.error.message}
        </span>
        <span className="q">
          {chars.slice(0, p).join("")}
          <span className="caret-mark">{chars[p] ?? " "}</span>
          {chars.slice(p + 1).join("")}
        </span>
      </>
    );
  }
  return (
    <>
      <span className="tag t-run">主查询</span>
      <QueryChip q={parse.anchor} />
      {attrPairs(parse.anchor).map(([k, v], i) => (
        <span key={`attr${i}`} className="tag t-line attr-tag">
          {ATTR_NAMES[k] ?? k} <b className="mono">{v}</b>
        </span>
      ))}
      {parse.conditions.map((c, i) => (
        <span key={i} className="row" style={{ gap: 6 }}>
          <span className={`tag ${c.op === "-" ? "t-warn" : "t-gray"}`} style={{ marginLeft: 6 }}>
            {c.op === "+" ? "同句含" : "同句不含"}
          </span>
          <QueryChip q={c.text} />
        </span>
      ))}
      <span className="ok" style={{ marginLeft: 8 }}>
        <Icon name="check" size={14} />
        可检索
      </span>
    </>
  );
}

export function CountsCards({ counts, timedOut, spark }: { counts: Counts | null; timedOut: boolean; spark?: { values: number[]; label: string } | null }) {
  const pending = counts && !counts.complete ? (timedOut ? "未完成" : "计算中") : undefined;
  const v = (n: number | undefined) => (counts ? (n ?? 0) : null);
  return (
    <section className="grid-3" aria-label="计数">
      <div className="card card-pad count-card">
        <div>
          <div className="stat-label">命中</div>
          <Count value={v(counts?.hits)} unit="次" pending={pending} />
        </div>
        {spark && !pending && <Sparkline values={spark.values} w={88} h={28} label={spark.label} />}
      </div>
      <div className="card card-pad count-card">
        <div>
          <div className="stat-label">句</div>
          <Count value={v(counts?.sentences)} unit="句" pending={pending} />
        </div>
      </div>
      <div className="card card-pad count-card">
        <div>
          <div className="stat-label">文档</div>
          <Count value={v(counts?.documents)} unit="篇" pending={pending} />
        </div>
      </div>
    </section>
  );
}

const fieldLabel = (field: string) => (field === "position" ? "文档位置" : field === "year" ? "年份" : field);

/** Distribution of the current hits; computed only when the user asks (stats.distribution job). */
function DistributionCard({
  fields,
  selected,
  onSelect,
  onRun,
  field,
  rows,
  running,
  error,
  picked,
  onPick,
}: {
  fields: string[];
  selected: string;
  onSelect: (field: string) => void;
  onRun: () => void;
  field: string | null;
  rows: DistRow[] | undefined;
  running: boolean;
  error: unknown;
  picked: number | null;
  onPick: (i: number | null) => void;
}) {
  const total = rows?.reduce((s, r) => s + (r.hits ?? 0), 0) ?? 0;
  return (
    <section className="card dist" aria-label="分布">
      <div className="row wrap">
        <h2 className="sec-title">分布</h2>
        <Select
          size="small"
          value={selected}
          onChange={onSelect}
          options={fields.map((f) => ({ value: f, label: fieldLabel(f) }))}
          style={{ width: 120 }}
          aria-label="分布字段"
        />
        {(selected !== field || !!error) && (
          <button className="btn xs" type="button" disabled={running} onClick={onRun}>
            计算分布
          </button>
        )}
        {picked != null && rows?.[picked] && (
          <span className="filter-chip">
            {fieldLabel(field ?? "")} = {rows[picked].label}
            <button type="button" aria-label="清除筛选" onClick={() => onPick(null)}>
              <Icon name="x" size={14} />
            </button>
          </span>
        )}
        <div className="grow" />
        {rows && (
          <div className="dist-legend">
            {rows.map((r, i) => (
              <span key={i} data-c={(i % 8) + 1}>
                <i />
                {r.label} <b className="num" style={{ fontWeight: 500 }}>{fmt(r.hits ?? 0)}</b>
              </span>
            ))}
          </div>
        )}
        {running && !rows && <span className="small muted">计算中</span>}
      </div>
      {!field ? null : error ? (
        <ErrorAlert error={error} />
      ) : rows ? (
        rows.length ? (
          <div className={`distbar ${picked != null ? "filtered" : ""}`} role="group" aria-label="按分布筛选">
            {rows.map((r, i) => (
              <Tip key={i} title={`${r.label} · ${fmt(r.hits ?? 0)} 次 · ${total ? (((r.hits ?? 0) / total) * 100).toFixed(1) : 0}%`}>
                <button
                  type="button"
                  data-c={(i % 8) + 1}
                  className={picked === i ? "on" : ""}
                  style={{ ["--w" as string]: Math.max(r.hits ?? 0, 0.0001), ["--i" as string]: i }}
                  aria-pressed={picked === i}
                  aria-label={`${r.label} ${r.hits} 次`}
                  onClick={() => onPick(picked === i ? null : i)}
                />
              </Tip>
            ))}
          </div>
        ) : (
          <span className="small muted">无分布数据</span>
        )
      ) : (
        <span className="prog indet thin">
          <i />
        </span>
      )}
    </section>
  );
}

function Pager({ page, pages, onChange }: { page: number; pages: number; onChange: (p: number) => void }) {
  const list: (number | "…")[] = [];
  for (let p = 1; p <= pages; p++) {
    if (p === 1 || p === pages || Math.abs(p - page) <= 1) list.push(p);
    else if (list[list.length - 1] !== "…") list.push("…");
  }
  return (
    <div className="pager" role="navigation" aria-label="分页">
      <button type="button" aria-label="上一页" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        <Icon name="left" size={14} />
      </button>
      {list.map((p, i) =>
        p === "…" ? (
          <button key={`e${i}`} type="button" disabled>
            …
          </button>
        ) : (
          <button key={p} type="button" aria-current={p === page ? "page" : undefined} onClick={() => onChange(p)}>
            {p}
          </button>
        ),
      )}
      <button type="button" aria-label="下一页" disabled={page >= pages} onClick={() => onChange(page + 1)}>
        <Icon name="right" size={14} />
      </button>
    </div>
  );
}

function HistoryPanel({
  open,
  items,
  current,
  onPick,
  onClose,
}: {
  open: boolean;
  items: HistoryEntry[];
  current: string;
  onPick: (h: HistoryEntry) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (e.target instanceof HTMLElement && !e.target.closest(".hist, [data-hist-btn]")) onClose();
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open, onClose]);
  return (
    <aside className={`hist ${open ? "open" : ""}`} aria-label="查询历史" aria-hidden={!open}>
      <div className="card-head">
        <h2 className="sec-title grow">查询历史</h2>
        <span className="small muted">最近 {items.length} 条</span>
        <button className="btn ghost icon" type="button" aria-label="关闭查询历史" onClick={onClose}>
          <Icon name="x" size={14} />
        </button>
      </div>
      <div className="hist-list">
        {items.length === 0 && <div className="empty sm">暂无查询历史</div>}
        {items.map((h, i) => (
          <button
            key={`${h.query}-${i}`}
            className={`hist-item ${h.query === current ? "on" : ""}`}
            type="button"
            style={{ ["--i" as string]: i }}
            onClick={() => onPick(h)}
            tabIndex={open ? 0 : -1}
          >
            <QueryChip q={h.query} />
            <span className="num">{h.hits != null ? fmt(h.hits) : ""}</span>
            <span className="meta">{h.scopeName}</span>
            <span className="meta" style={{ textAlign: "right" }}>
              {fmtShortTime(h.at)}
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function parseScopeParam(s: string | null): SearchScope | null {
  if (!s) return null;
  try {
    const v = JSON.parse(s);
    return v && typeof v === "object" && ("corpus_id" in v || "subcorpus_id" in v) ? (v as SearchScope) : null;
  } catch {
    return null;
  }
}

export default function Search() {
  const projectId = useProjectId();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const shell = useShell();
  const corpora = useCorpora(projectId);
  const subcorpora = useSubcorpora(projectId);
  const jobCreated = useJobCreated();
  const [params, setParams] = useSearchParams();

  const [query, setQuery] = useState("");
  const [tempScope, setTempScope] = useState<SearchScope | null>(null); // filtered scope from stats links
  const [ctxMode, setCtxMode] = useState<"char" | "sentence" | "paragraph">("char");
  const [sort, setSort] = useState<SearchRequest["sort"]>("position");
  const [req, setReq] = useState<SearchRequest | null>(null);
  const [runId, setRunId] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [within, setWithin] = useState("");
  const [posOn, setPosOn] = useState(false);
  const [legend, setLegend] = useState(false);
  const [histOpen, setHistOpen] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory(projectId));
  const [saving, setSaving] = useState(false);
  const [distBase, setDistBase] = useState<{ query: string; scope: SearchScope } | null>(null);
  const [picked, setPicked] = useState<number | null>(null);
  const [distPick, setDistPick] = useState<string | null>(null); // field chosen in the select
  const [distRuns, setDistRuns] = useState<Record<string, string>>({}); // search (query + scope) → computed field
  const [expanded, setExpanded] = useState<string | null>(null);
  const [layerPick, setLayerPick] = useState<{ corpus: string | null; pos?: string | null; dep?: string | null }>({ corpus: null });
  const inputRef = useRef<HTMLInputElement>(null);
  const lastParams = useRef<string>("");

  const scope: SearchScope | null = tempScope ?? shell.scope;
  const allCorpora = corpora.data?.items ?? [];
  const allSubs = subcorpora.data?.items ?? [];
  const info = describeScope(scope, allCorpora, allSubs);

  /* ---------- annotation layers for {pos=} / {dep=} (default: latest ready layer of the corpus) ---------- */
  const layersQ = useLayers(projectId);
  const allLayers = layersQ.data ?? [];
  const corpusLayers = allLayers.filter((l) => l.corpus_id === info.corpus?.id && l.status === "ready");
  const pickLayer = (kind: "pos" | "dep"): string | null => {
    const p = layerPick.corpus === info.corpus?.id ? layerPick[kind] : undefined;
    return p === undefined ? (defaultLayer(allLayers, info.corpus?.id, kind)?.id ?? null) : p;
  };
  const posLayer = pickLayer("pos");
  const depLayer = pickLayer("dep");
  function layersFor(sc: SearchScope): SearchRequest["layers"] | undefined {
    const cid = describeScope(sc, allCorpora, allSubs).corpus?.id;
    const pos = cid === info.corpus?.id ? posLayer : (defaultLayer(allLayers, cid, "pos")?.id ?? null);
    const dep = cid === info.corpus?.id ? depLayer : (defaultLayer(allLayers, cid, "dep")?.id ?? null);
    return pos || dep ? { ...(pos ? { pos } : {}), ...(dep ? { dep } : {}) } : undefined;
  }

  /* ---------- parse as you type ---------- */
  const debounced = useDebounced(query.trim(), 300);
  const parse = useQuery({
    queryKey: ["parse", debounced],
    queryFn: () => api.post<ParseResult>("/search/parse", { query: debounced }),
    enabled: debounced.length > 0,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    meta: { background: true },
  });
  const parseShown = debounced && debounced === query.trim() ? parse.data : undefined;
  const parseBad = !!parseShown && !parseShown.ok;

  /* ---------- search ---------- */
  const search = useQuery({
    queryKey: ["search", runId, req],
    queryFn: async () => {
      try {
        return await api.post<SearchResult>("/search", req);
      } catch (e) {
        if (!isExpired(e) || !req?.search_id) throw e;
        message.info(errorText(e));
        return api.post<SearchResult>("/search", withoutSearchId(req));
      }
    },
    enabled: !!req,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  });
  const result = search.data;

  // Re-request the same search_id while counts are incomplete, every 3 s for up to 1 min.
  const [polled, setPolled] = useState<{ id: string; counts: Counts } | null>(null);
  const [pollState, setPollState] = useState<{ id: string; timedOut: boolean; error?: unknown } | null>(null);
  const [pollRound, setPollRound] = useState(0);
  useEffect(() => {
    if (!req || !result || result.counts.complete) return;
    const id = result.search_id;
    let n = 0;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    setPollState({ id, timedOut: false });
    const tick = async () => {
      n += 1;
      try {
        const r = await api.post<SearchResult>("/search", { ...req, search_id: id });
        if (stopped) return;
        setPolled({ id, counts: r.counts });
        if (r.counts.complete) return;
      } catch (e) {
        if (stopped) return;
        if (isExpired(e)) {
          setRunId((k) => k + 1);
          setReq(withoutSearchId(req));
        } else setPollState({ id, timedOut: true, error: e });
        return;
      }
      if (n < COUNT_POLL_MAX) timer = setTimeout(tick, COUNT_POLL_MS);
      else setPollState({ id, timedOut: true });
    };
    timer = setTimeout(tick, COUNT_POLL_MS);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result?.search_id, result?.counts.complete, pollRound]);

  const counts = result && !result.counts.complete && polled?.id === result.search_id ? polled.counts : (result?.counts ?? null);
  const timedOut = !!result && pollState?.id === result.search_id && pollState.timedOut && !counts?.complete;

  // History keeps the final hit count.
  useEffect(() => {
    if (!req || !counts?.complete || picked != null) return;
    setHistory(pushHistory(projectId, { query: req.query, scope: req.scope, scopeName: info.name, hits: counts.hits, at: new Date().toISOString() }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [counts?.complete, counts?.hits, req?.query]);

  /* ---------- distribution (stats.distribution) ---------- */
  const distCorpusId = distBase ? describeScope(distBase.scope, allCorpora, allSubs).corpus?.id : undefined;
  const fields = useQuery({
    queryKey: ["metadata-fields", distCorpusId],
    queryFn: () => api.get<MetadataField[]>(`/corpora/${distCorpusId}/metadata-fields`),
    enabled: !!distCorpusId,
    staleTime: 5 * 60 * 1000,
    meta: { background: true },
  });
  const distFields = useMemo(() => {
    const numeric = (fields.data ?? []).filter((f) => f.type === "number").map((f) => f.field);
    return [...numeric.filter((f) => f === "year"), ...numeric.filter((f) => f !== "year"), "position"];
  }, [fields.data]);
  const distSelected = distPick && distFields.includes(distPick) ? distPick : distFields[0];
  const distKey = distBase ? JSON.stringify(distBase) : "";
  // Re-paging keeps distBase, so the same computed field (and the cached stat) is reused.
  const distField = distBase ? (distRuns[distKey] ?? null) : null;
  const distBody = distBase && distField && result ? { scope: distBase.scope, query: distBase.query, field: distField, bins: 10, project_id: projectId } : null;
  const dist = useStatJob("distribution", distBody, projectId, 0, { quiet: true });
  const dRows = useMemo(() => (dist.stat ? distRows(dist.stat) : undefined), [dist.stat]);

  /* ---------- actions ---------- */
  function run(opts?: { query?: string; scope?: SearchScope | null; fromDist?: boolean }) {
    const q = (opts?.query ?? query).trim();
    const sc = opts && "scope" in opts ? opts.scope : scope;
    if (!sc || !q) return;
    const next: SearchRequest = {
      scope: sc,
      query: q,
      context: { unit: ctxMode, size: 40 },
      sort,
      page: 1,
      page_size: PAGE_SIZE,
      include_tokens: true,
    };
    const lay = layersFor(sc);
    if (lay) next.layers = lay;
    if (sort === "random") next.seed = Math.floor(Math.random() * 1e9);
    setRunId((n) => n + 1);
    setReq(next);
    setSelected(null);
    setExpanded(null);
    setWithin("");
    if (!opts?.fromDist) {
      setPicked(null);
      setDistBase({ query: q, scope: sc });
      const p: Record<string, string> = { q };
      p.scope = JSON.stringify(sc);
      lastParams.current = new URLSearchParams(p).toString();
      setParams(p, { replace: true });
      setHistory(pushHistory(projectId, { query: q, scope: sc, scopeName: describeScope(sc, allCorpora, allSubs).name, hits: null, at: new Date().toISOString() }));
    }
  }

  // Open from a link: ?q=…&scope=… (stats "回到例句", saved queries, palette).
  useEffect(() => {
    const s = params.toString();
    if (s === lastParams.current) return;
    lastParams.current = s;
    const q = params.get("q");
    if (!q) return;
    const sc = parseScopeParam(params.get("scope"));
    setQuery(q);
    if (sc && "filter" in sc) setTempScope(sc);
    else {
      setTempScope(null);
      if (sc) shell.setScope(sc as Scope);
    }
    const effective = sc ?? shell.scope;
    if (effective) run({ query: q, scope: effective });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  // Re-run when context length or sort changes.
  useEffect(() => {
    if (req) run({ query: req.query, scope: req.scope, fromDist: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctxMode, sort, posLayer, depLayer]);

  function pickDist(i: number | null) {
    setPicked(i);
    if (!distBase) return;
    if (i == null || !dRows?.[i]) run({ query: distBase.query, scope: distBase.scope, fromDist: true });
    else run({ query: distBase.query, scope: dRows[i].scope, fromDist: true });
  }

  function changePage(page: number) {
    if (!req || !result) return;
    setReq({ ...req, page, search_id: result.search_id });
    setSelected(null);
  }

  const exportJob = useMutation({
    mutationFn: (format: "csv" | "xlsx") => api.post<Job>("/search/export", { ...withoutSearchId(req!), format, project_id: projectId }),
    onSuccess: (_, format) => {
      jobCreated(projectId);
      message.success(
        <span>
          已提交导出任务：{format.toUpperCase()}
          {counts?.complete ? `，${fmt(counts.hits)} 行` : ""}，<Link to={`/p/${projectId}/jobs`}>查看任务</Link>
        </span>,
      );
    },
    onError: (e) => message.error(errorText(e)),
  });

  const saveQuery = useMutation({
    mutationFn: (name: string) => api.post<SavedQuery>(`/projects/${projectId}/queries`, { name, query: query.trim(), scope }),
    onSuccess: (s) => {
      setSaving(false);
      message.success(`已保存查询「${s.name}」`);
      qc.invalidateQueries({ queryKey: ["queries", projectId] });
    },
  });

  // Page shortcuts: H history, P POS colouring.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && e.target.closest("input, textarea, select")) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "h" || e.key === "H") setHistOpen((o) => !o);
      else if (e.key === "p" || e.key === "P") setPosOn((o) => !o);
      else if (e.key === "Escape") setHistOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  /* ---------- assistant drawer context ---------- */
  const { setAssistantContext } = shell;
  useEffect(() => {
    const sc = req && !("filter" in req.scope) ? (req.scope as Scope) : shell.scope;
    setAssistantContext(
      counts?.complete && req ? { label: `当前检索 · ${fmt(counts.hits)} 命中`, scope: sc } : sc ? { label: describeScope(sc, allCorpora, allSubs).name, scope: sc } : null,
    );
    return () => setAssistantContext(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [counts?.complete, counts?.hits, req, shell.scope]);

  /* ---------- rows ---------- */
  const terms = conditionTerms(result?.parse.conditions);
  const corpusName = info.corpus?.name ?? "";
  const rows: (KwicRow & { hit: Hit })[] = (result?.items ?? [])
    .filter((h) => !within || `${h.left}${h.match}${h.right}`.includes(within))
    .map((h) => ({
      id: h.hit_id,
      left: h.left,
      match: h.match,
      right: h.right,
      source: h.document_title,
      aligned: h.aligned,
      tokens: h.tokens,
      evidence: hitEvidence(h, req!.query, req!.scope, corpusName),
      hit: h,
    }));
  const posAvailable = hasPos(rows);
  // 依存树 expander: the dependency layer the search used, else the corpus default; hidden without one.
  const treeLayer = req ? (req.layers?.dep ?? defaultLayer(allLayers, describeScope(req.scope, allCorpora, allSubs).corpus?.id, "dep")?.id ?? null) : null;
  const selectedHit = rows.find((r) => r.id === selected)?.hit ?? null;
  const total = counts?.complete ? counts.hits : null;
  const pages = result ? (total != null ? Math.max(1, Math.ceil(total / result.page_size)) : result.page + (result.items.length === result.page_size ? 1 : 0)) : 1;
  const from = result ? (result.page - 1) * result.page_size + 1 : 0;
  const spark = dRows && dRows.length > 1 && picked == null && distField === "year" ? { values: dRows.map((r) => r.hits ?? 0), label: `命中按年份 ${dRows[0].label}–${dRows[dRows.length - 1].label}` } : null;

  return (
    <>
      <PageHeader
        title="检索"
        actions={
          <button className="btn s" type="button" onClick={() => setSaving(true)} disabled={!query.trim() || !scope || !!tempScope}>
            <Icon name="plus" size={14} />
            <span className="lbl">保存查询</span>
          </button>
        }
      />
      <HistoryPanel
        open={histOpen}
        items={history}
        current={req?.query ?? ""}
        onClose={() => setHistOpen(false)}
        onPick={(h) => {
          setHistOpen(false);
          setQuery(h.query);
          if ("filter" in h.scope) setTempScope(h.scope);
          else {
            setTempScope(null);
            shell.setScope(h.scope as Scope);
          }
          run({ query: h.query, scope: h.scope });
        }}
      />
      <div className="content">
        <section className="card query-card" aria-label="查询">
          <form
            className="row"
            style={{ gap: 10 }}
            onSubmit={(e) => {
              e.preventDefault();
              if (!parseBad) run();
            }}
          >
            <Tip title="查询历史（H）">
              <button
                className="btn lg icon"
                type="button"
                aria-label="查询历史"
                aria-expanded={histOpen}
                data-hist-btn
                onClick={() => setHistOpen((o) => !o)}
              >
                <Icon name="history" size={18} />
              </button>
            </Tip>
            <label htmlFor="q" className="sr-only">
              查询式
            </label>
            <input
              id="q"
              ref={inputRef}
              className={`query-input ${parseBad ? "bad" : ""}`}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              placeholder="翻译/v +文化"
              data-slash
            />
            <button className="btn p lg" type="submit" disabled={!query.trim() || !scope || parseBad || search.isFetching}>
              {search.isFetching ? <span className="spin" /> : <Icon name="search" />}
              检索
            </button>
          </form>
          <div className="row wrap">
            <span className="small muted" style={{ marginRight: 2 }}>
              插入
            </span>
            {CHIPS.map(([label, snippet, tip]) => (
              <Tip key={label} title={tip}>
                <button
                  className="chip"
                  type="button"
                  onClick={() => {
                    const el = inputRef.current;
                    const s = el?.selectionStart ?? query.length;
                    const e = el?.selectionEnd ?? query.length;
                    const r = insertAt(query, s, e, snippet);
                    setQuery(r.value);
                    requestAnimationFrame(() => {
                      el?.focus();
                      el?.setSelectionRange(r.caret, r.caret);
                    });
                  }}
                >
                  {label}
                </button>
              </Tip>
            ))}
            <div className="grow" />
            <div className="parse" aria-live="polite">
              <ParseLine query={query.trim()} parse={parseShown} error={parse.error} />
            </div>
          </div>
          {corpusLayers.length > 0 && (
            <div className="layer-pick">
              <span className="small muted">标注层</span>
              {(["pos", "dep"] as const).map((kind) => {
                const opts = corpusLayers.filter((l) => l.kind === kind);
                if (!opts.length) return null;
                const name = kind === "pos" ? "词性" : "依存";
                return (
                  <Select
                    key={kind}
                    size="small"
                    style={{ width: 200 }}
                    aria-label={`${name}层`}
                    value={(kind === "pos" ? posLayer : depLayer) ?? ""}
                    onChange={(v: string) => setLayerPick((p) => ({ ...(p.corpus === info.corpus?.id ? p : { corpus: info.corpus?.id ?? null }), [kind]: v || null }))}
                    options={[{ value: "", label: `${name}：系统层` }, ...opts.map((l) => ({ value: l.id, label: `${name}：${l.name}` }))]}
                  />
                );
              })}
            </div>
          )}
          {!scope && (
            <div className="alert info">
              <Icon name="info" size={14} />
              <span>
                先选择范围：
                <button className="back" type="button" onClick={() => shell.openPalette("语料库")}>
                  选择语料库
                </button>
              </span>
            </div>
          )}
          {tempScope && (
            <div className="row">
              <span className="filter-chip">
                临时筛选 · {"filter" in tempScope ? Object.entries(tempScope.filter).map(([k, v]) => `${k} = ${JSON.stringify(v)}`).join("，") : ""}
                <button
                  type="button"
                  aria-label="清除筛选"
                  onClick={() => {
                    setTempScope(null);
                    if (req && shell.scope) run({ query: req.query, scope: shell.scope });
                  }}
                >
                  <Icon name="x" size={14} />
                </button>
              </span>
            </div>
          )}
        </section>

        {(result || search.isFetching) && <CountsCards counts={counts} timedOut={timedOut} spark={spark} />}

        {result && distBase && (
          <DistributionCard
            fields={distFields}
            selected={distSelected}
            onSelect={setDistPick}
            onRun={() => {
              setPicked(null);
              setDistRuns((r) => ({ ...r, [distKey]: distSelected }));
            }}
            field={distField}
            rows={dRows}
            running={dist.running}
            error={dist.error}
            picked={picked}
            onPick={pickDist}
          />
        )}

        {(result || search.error) && (
          <section className="results-row">
            <div className="card grow" style={{ display: "flex", flexDirection: "column" }}>
              <div className="card-head kwic-head">
                <SegmentedCtx value={ctxMode} onChange={setCtxMode} />
                <Select
                  size="small"
                  value={sort}
                  onChange={setSort}
                  style={{ width: 116 }}
                  aria-label="排序"
                  options={[
                    { value: "position", label: "按出处" },
                    { value: "left", label: "按左语境" },
                    { value: "right", label: "按右语境" },
                    { value: "random", label: "随机" },
                  ]}
                />
                <Input size="small" placeholder="结果内筛选" value={within} onChange={(e) => setWithin(e.target.value)} style={{ width: 128 }} allowClear />
                <span className="pos-toggle">
                  <Tip title={posAvailable ? "词性着色（P）" : "当前结果不含词性"}>
                    <button
                      className="switch"
                      type="button"
                      role="switch"
                      aria-checked={posOn && posAvailable}
                      aria-label="词性着色"
                      disabled={!posAvailable}
                      onClick={() => setPosOn((o) => !o)}
                    />
                  </Tip>
                  <span>词性</span>
                  <button className="btn ghost icon" type="button" aria-label="词性图例" aria-expanded={legend} onClick={() => setLegend((l) => !l)}>
                    <Icon name="palette" size={14} />
                  </button>
                  {legend && (
                    <div className="popover" style={{ top: 36, right: 0, width: 240 }} onMouseLeave={() => setLegend(false)}>
                      <div className="small muted" style={{ marginBottom: 8 }}>
                        词性颜色
                      </div>
                      <div className="legend-list">
                        {posLegend.map(([c, label]) => (
                          <span key={c} data-c={c}>
                            <i />
                            {label}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </span>
                <div className="grow" />
                {timedOut && (
                  <button className="btn s" type="button" onClick={() => setPollRound((n) => n + 1)}>
                    继续计数
                  </button>
                )}
                <button className="btn s" type="button" disabled={!req || exportJob.isPending} onClick={() => exportJob.mutate("csv")}>
                  <Icon name="download" size={14} />
                  CSV
                </button>
                <button className="btn s" type="button" disabled={!req || exportJob.isPending} onClick={() => exportJob.mutate("xlsx")}>
                  <Icon name="download" size={14} />
                  XLSX
                </button>
              </div>
              <ErrorAlert error={search.error} style={{ margin: 16 }} />
              {pollState?.error && pollState.id === result?.search_id ? <ErrorAlert error={pollState.error} style={{ margin: 16 }} /> : null}
              {search.isFetching && !result ? (
                <div className="col" style={{ padding: 16 }}>
                  {Array.from({ length: 6 }, (_, i) => (
                    <span key={i} className="skel h20" />
                  ))}
                </div>
              ) : result && result.items.length === 0 ? (
                <Empty icon="search" text="没有命中" />
              ) : (
                result && (
                  <div style={{ opacity: search.isFetching ? 0.55 : 1, transition: "opacity 200ms" }}>
                    <KwicTable
                      rows={rows}
                      terms={terms}
                      posColor={posOn && posAvailable}
                      selected={selected}
                      onSelect={setSelected}
                      expanded={expanded}
                      onExpand={setExpanded}
                      extraActions={(r) => {
                        const hit = rows.find((x) => x.id === r.id)?.hit;
                        return hit ? <TermExampleButton projectId={projectId} hit={hit} source={r.evidence?.source ?? hit.document_title} /> : null;
                      }}
                      renderExpanded={
                        treeLayer
                          ? (r) => {
                              const hit = rows.find((x) => x.id === r.id)?.hit;
                              return hit ? <SentenceTree layerId={treeLayer} posLayerId={req?.layers?.pos ?? null} hit={hit} projectId={projectId} /> : null;
                            }
                          : undefined
                      }
                    />
                  </div>
                )
              )}
              {result && result.items.length > 0 && (
                <div className="card-foot" style={{ marginTop: "auto" }}>
                  <span className="num">
                    {fmt(from)}–{fmt(from + result.items.length - 1)} / {total != null ? fmt(total) : "计算中"}
                  </span>
                  <div className="grow" />
                  <Pager page={result.page} pages={pages} onChange={changePage} />
                </div>
              )}
            </div>
            <ContextInspector
              hit={selectedHit}
              terms={terms}
              indexVersion={info.corpus?.index_version}
              evidence={selectedHit && req ? hitEvidence(selectedHit, req.query, req.scope, corpusName) : null}
            />
          </section>
        )}
      </div>

      <Modal title="保存查询" open={saving} footer={null} onCancel={() => setSaving(false)} destroyOnHidden>
        <div className="col" style={{ marginBottom: 12 }}>
          <QueryChip q={query.trim()} />
          <span className="small muted">{info.name}</span>
        </div>
        <Form layout="vertical" onFinish={(v: { name: string }) => saveQuery.mutate(v.name.trim())} requiredMark={false}>
          <Form.Item name="name" label="名称" rules={[{ required: true, whitespace: true, message: "请输入名称" }]}>
            <Input maxLength={100} autoFocus />
          </Form.Item>
          <ErrorAlert error={saveQuery.error} style={{ marginBottom: 12 }} />
          <button className="btn p" type="submit" disabled={saveQuery.isPending}>
            保存
          </button>
        </Form>
      </Modal>
    </>
  );
}

function SegmentedCtx({ value, onChange }: { value: "char" | "sentence" | "paragraph"; onChange: (v: "char" | "sentence" | "paragraph") => void }) {
  const opts: ["char" | "sentence" | "paragraph", string][] = [
    ["char", "40 字"],
    ["sentence", "整句"],
    ["paragraph", "整段"],
  ];
  return (
    <div className="seg-mini" role="tablist" aria-label="语境长度">
      {opts.map(([v, l]) => (
        <button key={v} type="button" role="tab" aria-selected={value === v} onClick={() => onChange(v)}>
          {l}
        </button>
      ))}
    </div>
  );
}
