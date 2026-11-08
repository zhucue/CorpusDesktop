import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Dropdown, Form, Input, Modal, Popover, Select } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import {
  ApiError,
  api,
  errorText,
  type Hit,
  type MetadataField,
  type ParseCorpus,
  type ParseResult,
  type SavedQuery,
  type Scope,
  type ScopePosition,
  type SearchRequest as BaseSearchRequest,
  type SearchResult,
  type SearchScope,
  type Span,
} from "../../api";
import { ErrorAlert, Empty, exportTip, IndexPendingNote, QueryChip, Sparkline, Tip } from "../../components/common";
import { ScopeSelect } from "../../components/common/ScopeSelect";
import { Icon } from "../../components/Icon";
import { conditionTerms, hasPos, KwicTable, type KwicMark, type KwicRow } from "../../components/results/Kwic";
import { cpLength, labelColor } from "../../components/annot/spans";
import { PageHeader } from "../../components/shell/AppShell";
import { useShell } from "../../components/shell/shell";
import { describeScope, useCorpora, useProjectId, useSubcorpora } from "../../lib/data";
import { fmt, fmtShortTime } from "../../lib/format";
import { useExportJob } from "../../lib/exportJob";
import { posLegend } from "../../lib/pos";
import { distRows, type DistRow } from "../stats/columns";
import { useStatJob } from "../stats/useStatJob";
import { defaultLayer, useLabelSets, useLayers } from "../annotate/data";
import ContextInspector, { hitEvidence } from "./ContextInspector";
import SentenceTree from "./SentenceTree";
import TermExampleButton from "../knowledge/TermExampleButton";
import { useDebounced } from "../../lib/useDebounced";
import { loadHistory, pushHistory, type HistoryEntry } from "./history";
import { distributionFields, fieldLabel } from "./fields";
import { posGroups } from "./posTags";
import { convertScript, guessScript, scriptLabel } from "./script";
import { sortNote, useCountPoll, type SearchCounts, type SearchPage } from "./countPoll";
import { withCondition } from "./condition";
import { AlignedInput, BreakdownMenu, hasPosition, isAlignedError, parseAlignedParam, POSITION_OFF, SampleDialog, TranslationsButton } from "./SearchTools";
import SemanticSearch from "./SemanticSearch";
import "./search.css";

const PAGE_SIZE = 50;

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
  ["[标签]", "[]", "片段标签：[时态]、词[时态]、[时态:k=v]"],
];

/** P11: 简繁通查 (contracts/p11.md §一); omitted = on for corpora with Chinese. */
type SearchRequest = BaseSearchRequest & { script_variants?: boolean };

/** Corpus has Chinese text (document languages from the index profile, else its declared language). */
function zhCorpus(c: { language?: string; meta?: { languages?: string[] } } | null | undefined): boolean {
  const langs = c?.meta?.languages?.length ? c.meta.languages : [c?.language ?? ""];
  return langs.some((l) => /^(zh|cmn|zho|chi)\b/i.test(l ?? ""));
}

/** Spans of a KWIC page's sentences, one request per page (POST /search/span-marks). */
type SpanMarks = { items: { document_id: string; sentence_index: number; spans: Pick<Span, "start_cp" | "end_cp" | "label" | "status">[] }[] };

const isExpired = (e: unknown) => e instanceof ApiError && e.code === "SEARCH_EXPIRED";
function withoutSearchId(r: SearchRequest): SearchRequest {
  const { search_id: _ignored, ...rest } = r;
  return rest;
}

/** Insert `snippet` at the caret; "" and [] place the caret inside, {k=} before the brace. */
export function insertAt(value: string, start: number, end: number, snippet: string): { value: string; caret: number } {
  const next = value.slice(0, start) + snippet + value.slice(end);
  const caret = snippet === '""' || snippet === "[]" ? start + 1 : snippet.endsWith("=}") ? start + snippet.length - 1 : start + snippet.length;
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

/** Final value straight away: rolling from the previous search's count read as a wrong number (QA Q24). */
function Count({ value, unit, pending }: { value: number | null; unit: string; pending?: string }) {
  if (pending) return <div className="count pending">{pending}</div>;
  return (
    <div className="count">
      <span className="n">{fmt(value ?? 0)}</span>
      <span className="unit">{unit}</span>
    </div>
  );
}

export function CountsCards({
  counts,
  spark,
  searching,
  note,
  parallel,
}: {
  counts: SearchCounts | null;
  spark?: { values: number[]; label: string } | null;
  /** A new search is running: the previous counts are not shown. */
  searching?: boolean;
  /** Shown on the hit card, e.g. 含译文条件. */
  note?: string;
  /** Parallel corpus: the third card counts sentence pairs, not documents (one document per language side). */
  parallel?: boolean;
}) {
  const pending = searching ? "检索中" : counts && !counts.complete ? (counts.failed ? "未完成" : "计算中") : undefined;
  const v = (n: number | undefined) => (counts ? (n ?? 0) : null);
  return (
    <section className="grid-3" aria-label="计数">
      <div className="card card-pad count-card">
        <div>
          <div className="stat-label">
            命中
            {note && <span className="tag t-info" style={{ marginLeft: 6 }}>{note}</span>}
          </div>
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
        {parallel ? (
          <div>
            <div className="stat-label">句对</div>
            <Count value={v(counts?.pairs ?? counts?.sentences)} unit="对" pending={pending} />
          </div>
        ) : (
          <div>
            <div className="stat-label">文档</div>
            <Count value={v(counts?.documents)} unit="篇" pending={pending} />
          </div>
        )}
      </div>
    </section>
  );
}

/** 插入 → 词性: the POS tags of the searched corpus's index, inserted as /TAG at the caret (QA Q21). */
function PosPicker({ info, onInsert }: { info: ParseCorpus | undefined; onInsert: (snippet: string) => void }) {
  const [open, setOpen] = useState(false);
  const tags = info ? posGroups(info.pos_tags) : [];
  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      placement="bottomLeft"
      content={
        <div style={{ width: 340 }}>
          <div className="small muted" style={{ marginBottom: 8 }}>
            {info ? `词性体系 ${info.tagset_name} · 写作 词/标签，如 语言/${tags.find((t) => t.tag === "NOUN" || t.tag === "n")?.tag ?? tags[0]?.tag ?? "n"}` : "选择语料库后列出词性"}
          </div>
          <div className="row wrap" style={{ gap: 4, maxHeight: 260, overflow: "auto" }}>
            {tags.map((t) => (
              <button
                key={t.tag}
                className="chip"
                type="button"
                onClick={() => {
                  setOpen(false);
                  onInsert(`/${t.tag}`);
                }}
              >
                <span className="mono">{t.tag}</span>
                {t.name && <span className="muted"> {t.name}</span>}
              </button>
            ))}
          </div>
        </div>
      }
    >
      <button className="chip" type="button" aria-label="插入词性">
        词性{info ? ` · ${info.tagset_name}` : ""}
      </button>
    </Popover>
  );
}

/** Temporary filter chip text: field names in Chinese, plain values (no JSON quotes); a distribution row's document-position part. */
function filterText(filter: Record<string, unknown>, position?: ScopePosition): string {
  const parts = Object.entries(filter).map(([k, v]) => {
    if (Array.isArray(v)) return `${fieldLabel(k)} = ${v.join("、")}`;
    if (v && typeof v === "object") {
      const r = v as { gte?: number; lte?: number };
      return `${fieldLabel(k)} ${r.gte ?? ""}–${r.lte ?? ""}`;
    }
    return `${fieldLabel(k)} = ${String(v)}`;
  });
  if (position) {
    const pct = (k: number) => Number(((100 * k) / position.bins).toPrecision(6));
    parts.push(`文档位置 ${pct(position.bin)}–${pct(position.bin + 1)}%`);
  }
  return parts.join("，");
}

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
  off,
}: {
  off?: string;
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
          disabled={!!off}
        />
        {(selected !== field || !!error) && (
          <button className="btn xs" type="button" disabled={running || !!off} title={off} onClick={onRun}>
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
        {items.length === 0 && <Empty icon="history" text="暂无查询历史" />}
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
  const [params, setParams] = useSearchParams();

  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"query" | "semantic">("query");
  const [tempScope, setTempScope] = useState<SearchScope | null>(null); // filtered scope from stats links
  const [ctxMode, setCtxMode] = useState<"char" | "sentence" | "paragraph">("char");
  const [sort, setSort] = useState<SearchRequest["sort"]>("position");
  const [req, setReq] = useState<SearchRequest | null>(null);
  const [runId, setRunId] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [within, setWithin] = useState("");
  const [withinOp, setWithinOp] = useState<"+" | "-">("+");
  // the query before 结果内筛选 added its condition; restored when the filter is cleared
  const [withinBase, setWithinBase] = useState<string | null>(null);
  const [variantsPick, setVariantsPick] = useState<{ corpus: string | undefined; on: boolean } | null>(null);
  const [posOn, setPosOn] = useState(false);
  const [legend, setLegend] = useState(false);
  const [histOpen, setHistOpen] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory(projectId));
  const [saving, setSaving] = useState(false);
  const [distBase, setDistBase] = useState<{ query: string; scope: SearchScope; aligned?: SearchRequest["aligned"] } | null>(null);
  const [picked, setPicked] = useState<number | null>(null);
  const [distPick, setDistPick] = useState<string | null>(null); // field chosen in the select
  const [distRuns, setDistRuns] = useState<Record<string, string>>({}); // search (query + scope) → computed field
  const [expanded, setExpanded] = useState<string | null>(null);
  const [alignedOp, setAlignedOp] = useState<"+" | "-">("+");
  const [alignedQuery, setAlignedQuery] = useState("");
  const [sampling, setSampling] = useState(false);
  const [layerPick, setLayerPick] = useState<{ corpus: string | null; pos?: string | null; dep?: string | null; span?: string | null }>({ corpus: null });
  const inputRef = useRef<HTMLInputElement>(null);
  const lastParams = useRef<string>("");

  const scope: SearchScope | null = tempScope ?? shell.scope;
  // a document-position part (B06): search and its CSV / XLSX export only; the other tools are off
  const shownMode = hasPosition(scope) ? "query" : mode;
  const allCorpora = corpora.data?.items ?? [];
  const allSubs = subcorpora.data?.items ?? [];
  const info = describeScope(scope, allCorpora, allSubs);
  const zh = zhCorpus(info.corpus);
  const variants = variantsPick && variantsPick.corpus === info.corpus?.id ? variantsPick.on : zh;

  /* ---------- annotation layers for {pos=} / {dep=} (default: latest ready layer of the corpus) ---------- */
  const layersQ = useLayers(projectId);
  const allLayers = layersQ.data ?? [];
  const labelSetsQ = useLabelSets(projectId);
  const corpusLayers = allLayers.filter((l) => l.corpus_id === info.corpus?.id && l.status === "ready");
  const pickLayer = (kind: "pos" | "dep" | "span"): string | null => {
    const p = layerPick.corpus === info.corpus?.id ? layerPick[kind] : undefined;
    return p === undefined ? (defaultLayer(allLayers, info.corpus?.id, kind)?.id ?? null) : p;
  };
  const posLayer = pickLayer("pos");
  const depLayer = pickLayer("dep");
  const spanLayer = pickLayer("span");
  function layersFor(sc: SearchScope): SearchRequest["layers"] | undefined {
    const cid = describeScope(sc, allCorpora, allSubs).corpus?.id;
    const same = cid === info.corpus?.id;
    const pos = same ? posLayer : (defaultLayer(allLayers, cid, "pos")?.id ?? null);
    const dep = same ? depLayer : (defaultLayer(allLayers, cid, "dep")?.id ?? null);
    const span = same ? spanLayer : (defaultLayer(allLayers, cid, "span")?.id ?? null);
    return pos || dep || span ? { ...(pos ? { pos } : {}), ...(dep ? { dep } : {}), ...(span ? { span } : {}) } : undefined;
  }

  /* ---------- parse as you type, against the corpus searched (tagset, layers) ---------- */
  const scopeStr = scope ? JSON.stringify(scope) : "";
  const corpusReady = info.corpus?.status === "ready" || info.corpus?.status === "stale";
  // What the corpus offers (POS tags, tagset, layers): an empty query parsed with the scope.
  const corpusFacts = useQuery({
    queryKey: ["parse-corpus", scopeStr, info.corpus?.index_version],
    queryFn: () => api.post<ParseResult>("/search/parse", { query: "", scope }),
    enabled: !!scope && corpusReady,
    staleTime: 5 * 60 * 1000,
    retry: false,
    meta: { background: true },
  });
  const facts = corpusFacts.data?.corpus;
  const debounced = useDebounced(query.trim(), 300);
  const parse = useQuery({
    queryKey: ["parse", debounced, scopeStr],
    queryFn: () => api.post<ParseResult>("/search/parse", scope && corpusReady ? { query: debounced, scope } : { query: debounced }),
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
        return await api.post<SearchPage>("/search", req);
      } catch (e) {
        if (!isExpired(e) || !req?.search_id) throw e;
        message.info(errorText(e));
        return api.post<SearchPage>("/search", withoutSearchId(req));
      }
    },
    enabled: !!req,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  });
  const result = search.data;
  // 简繁通查: the query as searched (Han strings with their other spellings), for the tools that count the
  // same hits (distribution, breakdown, translations, sampling, tidy export)
  const searched = result?.searched_query && req && result.searched_query !== req.query ? result.searched_query : null;
  const toolReq = req && searched ? { ...req, query: searched } : req;

  // Poll the background count; once done, the page on screen is fetched again when it was unsorted or short.
  const { counts, error: pollError } = useCountPoll({
    req,
    result,
    placeholder: search.isPlaceholderData,
    post: (body) => api.post<SearchPage>("/search", body),
    refetch: (next) => {
      setRunId((k) => k + 1);
      setReq(next);
    },
    expired: (r) => {
      setRunId((k) => k + 1);
      setReq(withoutSearchId(r));
    },
    isExpired,
  });

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
  const distFields = useMemo(() => distributionFields(fields.data ?? []), [fields.data]);
  const distSelected = distPick && distFields.includes(distPick) ? distPick : distFields[0];
  const distKey = distBase ? JSON.stringify(distBase) : "";
  // Re-paging keeps distBase, so the same computed field (and the cached stat) is reused.
  const distField = distBase ? (distRuns[distKey] ?? null) : null;
  const distBody =
    distBase && distField && result
      ? {
          scope: distBase.scope,
          query: searched && distBase.query === req?.query ? searched : distBase.query,
          field: distField,
          bins: 10,
          project_id: projectId,
          ...(distBase.aligned ? { aligned: distBase.aligned } : {}),
        }
      : null;
  const dist = useStatJob("distribution", distBody, projectId, 0, { quiet: true });
  const dRows = useMemo(() => (dist.stat ? distRows(dist.stat) : undefined), [dist.stat]);

  /* ---------- actions ---------- */
  function insert(snippet: string) {
    const el = inputRef.current;
    const s = el?.selectionStart ?? query.length;
    const e = el?.selectionEnd ?? query.length;
    const r = insertAt(query, s, e, snippet);
    setQuery(r.value);
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(r.caret, r.caret);
    });
  }

  function run(opts?: {
    query?: string;
    scope?: SearchScope | null;
    fromDist?: boolean;
    layers?: SearchRequest["layers"];
    aligned?: SearchRequest["aligned"] | null;
    keepWithin?: boolean;
    variants?: boolean;
  }) {
    const q = (opts?.query ?? query).trim();
    const sc = opts && "scope" in opts ? opts.scope : scope;
    if (!sc || !q) return;
    // 译文条件: an explicit value (link, re-run) is always sent (the API answers NOT_PARALLEL; corpora may not
    // be loaded yet on a fresh page); the input applies on parallel corpora only.
    const scParallel = !!describeScope(sc, allCorpora, allSubs).corpus?.parallel;
    const al = opts && "aligned" in opts ? opts.aligned : scParallel && alignedQuery.trim() ? { op: alignedOp, query: alignedQuery.trim() } : null;
    const next: SearchRequest = {
      scope: sc,
      query: q,
      context: { unit: ctxMode, size: 40 },
      sort,
      page: 1,
      page_size: PAGE_SIZE,
      include_tokens: true,
    };
    const scCorpus = describeScope(sc, allCorpora, allSubs).corpus;
    const scVariants = opts?.variants ?? (variantsPick && variantsPick.corpus === scCorpus?.id ? variantsPick.on : zhCorpus(scCorpus));
    if (zhCorpus(scCorpus) || scVariants) next.script_variants = scVariants;
    const lay = opts?.layers ? { ...layersFor(sc), ...opts.layers } : layersFor(sc);
    if (lay) next.layers = lay;
    if (al) next.aligned = al;
    if (sort === "random") next.seed = Math.floor(Math.random() * 1e9);
    setRunId((n) => n + 1);
    setReq(next);
    setSelected(null);
    setExpanded(null);
    if (!opts?.keepWithin) {
      setWithin("");
      setWithinBase(null);
    }
    if (!opts?.fromDist) {
      setPicked(null);
      setDistBase({ query: q, scope: sc, aligned: next.aligned });
      const p: Record<string, string> = { q };
      p.scope = JSON.stringify(sc);
      if (next.aligned) p.aligned = JSON.stringify(next.aligned);
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
    const sc = parseScopeParam(params.get("scope"));
    // ?scope= alone (corpus or subcorpus links) sets the range without searching.
    if (sc && "filter" in sc) setTempScope(sc);
    else {
      setTempScope(null);
      if (sc) shell.setScope(sc as Scope);
    }
    if (!q) return;
    setQuery(q);
    const effective = sc ?? shell.scope;
    // "回到例句" from a statistic counted on annotation layers carries them (?layers=)
    let urlLayers: SearchRequest["layers"] | undefined;
    try {
      urlLayers = params.get("layers") ? (JSON.parse(params.get("layers")!) as SearchRequest["layers"]) : undefined;
    } catch {
      urlLayers = undefined;
    }
    if (urlLayers && effective) {
      const cid = "corpus_id" in effective ? effective.corpus_id : describeScope(effective, allCorpora, allSubs).corpus?.id;
      if (cid) setLayerPick({ corpus: cid, ...urlLayers });
    }
    // 译文条件 from stats rows / assistant links: ?aligned=<JSON {op, query}>
    const urlAligned = parseAlignedParam(params.get("aligned"));
    setAlignedOp(urlAligned?.op ?? "+");
    setAlignedQuery(urlAligned?.query ?? "");
    if (effective) run({ query: q, scope: effective, layers: urlLayers, aligned: urlAligned });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  // The project scope changed elsewhere (palette, breadcrumb, header picker): a temporary filter no longer applies.
  const shellScopeKey = JSON.stringify(shell.scope ?? null);
  const lastShellScope = useRef(shellScopeKey);
  useEffect(() => {
    if (lastShellScope.current === shellScopeKey) return;
    lastShellScope.current = shellScopeKey;
    setTempScope(null);
  }, [shellScopeKey]);

  // Re-run when context length or sort changes.
  useEffect(() => {
    if (req) run({ query: req.query, scope: req.scope, fromDist: true, aligned: req.aligned ?? null, keepWithin: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctxMode, sort, posLayer, depLayer, spanLayer]);

  /** 结果内筛选: the term becomes a same-sentence condition and the search runs again over all hits. */
  function applyWithin(term: string) {
    if (!req) return;
    const base = withinBase ?? req.query;
    if (!term.trim()) {
      if (withinBase == null) return;
      setQuery(base);
      run({ query: base, scope: req.scope, aligned: req.aligned ?? null });
      return;
    }
    const q = withCondition(base, withinOp, term);
    setQuery(q);
    run({ query: q, scope: req.scope, aligned: req.aligned ?? null, keepWithin: true });
    setWithinBase(base);
  }

  function toggleVariants(on: boolean) {
    setVariantsPick({ corpus: info.corpus?.id, on });
    if (req) run({ query: req.query, scope: req.scope, fromDist: true, aligned: req.aligned ?? null, keepWithin: true, variants: on });
  }

  function pickDist(i: number | null) {
    setPicked(i);
    if (!distBase) return;
    const aligned = distBase.aligned ?? null;
    if (i == null || !dRows?.[i]) run({ query: distBase.query, scope: distBase.scope, fromDist: true, aligned });
    else run({ query: distBase.query, scope: dRows[i].scope, fromDist: true, aligned });
  }

  function changePage(page: number) {
    if (!req || !result) return;
    setReq({ ...req, page, search_id: result.search_id });
    setSelected(null);
  }

  // Background export: "已开始导出", then a toast with 下载 when the job finishes (QA Q32).
  const exporter = useExportJob(projectId);
  const exportAs = (format: "csv" | "xlsx") =>
    exporter.start({ url: "/search/export", body: { ...withoutSearchId(req!), format, project_id: projectId }, label: format.toUpperCase() });
  // 导出整洁数据 (contracts/p10.md §三): one row per document of the current scope, hit columns for the current query
  const tidyExport = (format: "csv" | "xlsx") =>
    exporter.start({ url: "/stats/tidy_export", body: { project_id: projectId, scope: req!.scope, queries: [toolReq!.query], format }, label: `整洁数据 ${format.toUpperCase()}` });

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
      req
        ? {
            label: counts?.complete ? `当前检索 · ${fmt(counts.hits)} 命中` : describeScope(sc, allCorpora, allSubs).name,
            scope: sc,
            query: req.query,
            search_id: result?.search_id,
            hit_ids: selected ? [selected] : undefined,
          }
        : sc
          ? { label: describeScope(sc, allCorpora, allSubs).name, scope: sc }
          : null,
    );
    return () => setAssistantContext(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [counts?.complete, counts?.hits, req, shell.scope, result?.search_id, selected]);

  /* ---------- rows ---------- */
  const terms = conditionTerms(result?.parse.conditions);
  const corpusName = info.corpus?.name ?? "";
  const parallel = !!info.corpus?.parallel;
  const alignedError = isAlignedError(search.error) ? search.error : null;
  const rows: (KwicRow & { hit: Hit })[] = (result?.items ?? []).map((h) => ({
      id: h.hit_id,
      left: h.left,
      match: h.match,
      right: h.right,
      source: h.document_title,
      locator: `句 ${h.sentence_index + 1}`,
      aligned: h.aligned,
      noAligned: parallel,
      tokens: h.tokens,
      evidence: hitEvidence(h, req!.query, req!.scope, corpusName),
      hit: h,
    }));
  const posAvailable = hasPos(rows);

  /* ---------- script (简/繁): recorded at import, else guessed from the hits; zero-hit hint (QA Q36) ---------- */
  const script = info.corpus?.meta?.script ?? facts?.script ?? guessScript(rows.slice(0, 20).map((r) => r.left + r.match + r.right).join(""));
  const zeroHits = !!req && !!counts?.complete && counts.hits === 0 && /[一-鿿]/.test(req.query) && !req.search_id && !result?.script_variants;
  const altScript = useQuery({
    queryKey: ["script-alt", req],
    enabled: zeroHits,
    staleTime: Infinity,
    retry: false,
    meta: { background: true },
    queryFn: async () => {
      for (const to of ["traditional", "simplified"] as const) {
        const alt = convertScript(req!.query, to);
        if (alt === req!.query) continue;
        const r = await api.post<SearchResult>("/search", { ...withoutSearchId(req!), query: alt, page: 1, page_size: 1, include_tokens: false });
        if (r.counts.hits !== 0) return { query: alt, to, hits: r.counts.complete ? r.counts.hits : null };
      }
      return null;
    },
  });

  /* ---------- span highlights (片段层): the spans of the page's sentences, one request per page ---------- */
  const markLayer = req?.layers?.span ?? null;
  const rowKey = (h: { document_id: string; sentence_index: number }) => `${h.document_id}:${h.sentence_index}`;
  const pageKeys = [...new Set((result?.items ?? []).map(rowKey))];
  const marksQ = useQuery({
    queryKey: ["span-marks", markLayer, pageKeys],
    enabled: !!markLayer && pageKeys.length > 0,
    staleTime: 60 * 1000,
    meta: { background: true },
    queryFn: () =>
      api.post<SpanMarks>("/search/span-marks", {
        layer_id: markLayer,
        sentences: pageKeys.map((k) => ({ document_id: k.slice(0, k.lastIndexOf(":")), sentence_index: Number(k.slice(k.lastIndexOf(":") + 1)) })),
      }),
  });
  const spanBy = new Map((marksQ.data?.items ?? []).map((x) => [rowKey(x), x.spans]));
  const markSet = labelSetsQ.data?.find((ls) => ls.id === allLayers.find((l) => l.id === markLayer)?.label_set_id);
  const markOrder = (markSet?.labels ?? []).map((l) => l.name);
  function rowMarks(r: KwicRow): KwicMark[] | undefined {
    const hit = rows.find((x) => x.id === r.id)?.hit;
    const ss = hit ? spanBy.get(rowKey(hit)) : undefined;
    if (!hit || !ss) return undefined;
    const rowStart = hit.start_cp - cpLength(hit.left);
    return ss
      .filter((x) => x.status !== "rejected")
      .map((x) => ({ start: x.start_cp - rowStart, end: x.end_cp - rowStart, label: x.label, color: labelColor(x.label, markOrder) }));
  }
  // 依存树 expander: the dependency layer the search used, else the corpus default; hidden without one.
  const treeLayer = req ? (req.layers?.dep ?? defaultLayer(allLayers, describeScope(req.scope, allCorpora, allSubs).corpus?.id, "dep")?.id ?? null) : null;
  const selectedHit = rows.find((r) => r.id === selected)?.hit ?? null;
  // 双语对照 word links: the most recent ready word alignment layer whose source is the searched corpus.
  const hitCorpusId = req ? describeScope(req.scope, allCorpora, allSubs).corpus?.id : undefined;
  // No dependency layer: the corpus's own CoNLL-U head / deprel (B04), when the parse facts say it has them.
  const nativeTree = !treeLayer && !!hitCorpusId && hitCorpusId === info.corpus?.id && !!facts?.layers.dep;
  const alignLayer =
    allLayers
      .filter((l) => l.kind === "alignment" && l.level === "word" && l.status === "ready" && (l.src_corpus_id ?? l.corpus_id) === hitCorpusId)
      .sort((a, b) => (b.updated_at ?? b.created_at).localeCompare(a.updated_at ?? a.created_at))[0] ?? null;
  const total = counts?.complete ? counts.hits : null;
  const pages = result ? (total != null ? Math.max(1, Math.ceil(total / result.page_size)) : result.page + (result.items.length === result.page_size ? 1 : 0)) : 1;
  const from = result ? (result.page - 1) * result.page_size + 1 : 0;
  const spark = dRows && dRows.length > 1 && picked == null && distField === "year" ? { values: dRows.map((r) => r.hits ?? 0), label: `命中按年份 ${dRows[0].label}–${dRows[dRows.length - 1].label}` } : null;

  return (
    <>
      <PageHeader
        title="检索"
        actions={
          <>
            <SearchMode value={shownMode} onChange={setMode} semanticOff={hasPosition(scope) ? POSITION_OFF : undefined} />
            {/* direct corpus / subcorpus picker (QA Q28) */}
            <ScopeSelect
              projectId={projectId}
              value={tempScope ? null : shell.scope}
              onChange={(sc) => {
                setTempScope(null);
                shell.setScope(sc);
              }}
              width={220}
            />
            <button className="btn s" type="button" onClick={() => setSaving(true)} disabled={shownMode === "semantic" || !query.trim() || !scope || !!tempScope}>
              <Icon name="plus" size={14} />
              <span className="lbl">保存查询</span>
            </button>
          </>
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
        {shownMode === "semantic" ? (
          <SemanticSearch projectId={projectId} scope={scope} corpus={info.corpus} />
        ) : (
        <>
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
            <PosPicker info={facts} onInsert={insert} />
            {CHIPS.map(([label, snippet, tip]) => (
              <Tip key={label} title={tip}>
                <button className="chip" type="button" onClick={() => insert(snippet)}>
                  {label}
                </button>
              </Tip>
            ))}
            {script && script !== "simplified" && <span className="tag t-gray">{scriptLabel[script]}</span>}
            {zh && (
              <Tip title="汉字串同时检索简体与繁体写法">
                <span className="pos-toggle">
                  <button className="switch" type="button" role="switch" aria-checked={variants} aria-label="简繁通查" onClick={() => toggleVariants(!variants)} />
                  <span>简繁通查</span>
                </span>
              </Tip>
            )}
            <div className="grow" />
            <div className="parse" aria-live="polite">
              <ParseLine query={query.trim()} parse={parseShown} error={parse.error} />
            </div>
          </div>
          {corpusLayers.some((l) => l.kind === "pos" || l.kind === "dep" || l.kind === "span") && (
            <div className="layer-pick">
              <span className="small muted">标注层</span>
              {(["pos", "dep", "span"] as const).map((kind) => {
                const opts = corpusLayers.filter((l) => l.kind === kind);
                if (!opts.length) return null;
                const name = kind === "pos" ? "词性" : kind === "dep" ? "依存" : "片段";
                return (
                  <Select
                    key={kind}
                    size="small"
                    style={{ width: 200 }}
                    aria-label={`${name}层`}
                    value={(kind === "pos" ? posLayer : kind === "dep" ? depLayer : spanLayer) ?? ""}
                    onChange={(v: string) => setLayerPick((p) => ({ ...(p.corpus === info.corpus?.id ? p : { corpus: info.corpus?.id ?? null }), [kind]: v || null }))}
                    options={[{ value: "", label: kind === "span" ? "片段：不选" : `${name}：系统层` }, ...opts.map((l) => ({ value: l.id, label: `${name}：${l.name}` }))]}
                  />
                );
              })}
            </div>
          )}
          {parallel && (
            <AlignedInput
              op={alignedOp}
              query={alignedQuery}
              onOp={setAlignedOp}
              onQuery={setAlignedQuery}
              scope={scope && corpusReady ? scope : null}
              error={alignedError}
              onSubmit={() => !parseBad && run()}
            />
          )}
          {!scope && (
            <div className="alert info">
              <Icon name="info" size={14} />
              <span>先选择范围</span>
              <ScopeSelect projectId={projectId} value={null} onChange={(sc) => shell.setScope(sc)} size="small" />
            </div>
          )}
          <IndexPendingNote corpus={info.corpus} />
          {tempScope && (
            <div className="row">
              <span className="filter-chip">
                临时筛选 · {"filter" in tempScope ? filterText(tempScope.filter, tempScope.position) : ""}
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

        {(result || search.isFetching) && (
          <CountsCards
            counts={counts}
            spark={spark}
            searching={search.isFetching && search.isPlaceholderData && !req?.search_id}
            note={req?.aligned ? `含译文条件（${req.aligned.op === "+" ? "含" : "不含"} ${req.aligned.query}）` : undefined}
            parallel={!!info.corpus?.parallel}
          />
        )}

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
            off={hasPosition(distBase.scope) ? POSITION_OFF : undefined}
          />
        )}

        {(result || search.error) && (
          // a query with a syntax error greys out the previous results (QA Q23)
          <section className="results-row" style={parseBad ? { opacity: 0.45 } : undefined}>
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
                <span className="row" style={{ gap: 4 }} role="group" aria-label="结果内筛选">
                  <Select
                    size="small"
                    value={withinOp}
                    onChange={setWithinOp}
                    style={{ width: 72 }}
                    aria-label="筛选方式"
                    options={[
                      { value: "+", label: "含" },
                      { value: "-", label: "不含" },
                    ]}
                  />
                  <Tip title="作为同句条件重新检索全部结果，回车生效">
                    <Input
                      size="small"
                      placeholder="结果内筛选"
                      value={within}
                      onChange={(e) => {
                        setWithin(e.target.value);
                        if (!e.target.value && withinBase != null) applyWithin("");
                      }}
                      onPressEnter={() => applyWithin(within)}
                      style={{ width: 128 }}
                      allowClear
                    />
                  </Tip>
                </span>
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
                {sortNote(result, counts) && (
                  <span className="muted" role="status">
                    {sortNote(result, counts)}
                  </span>
                )}
                <BreakdownMenu projectId={projectId} req={toolReq} fields={distFields} />
                {(parallel || !!req?.aligned) && <TranslationsButton projectId={projectId} req={toolReq} />}
                <Tip title={hasPosition(req?.scope) ? POSITION_OFF : counts?.complete ? "从全部命中中抽样并逐条编码" : "计数完成后可抽样"}>
                  <button className="btn s" type="button" disabled={!req || !counts?.complete || !counts.hits || hasPosition(req.scope)} onClick={() => setSampling(true)}>
                    <Icon name="pen" size={14} />
                    抽样编码
                  </button>
                </Tip>
                <Tip title={exportTip("导出 CSV")}>
                  <button className="btn s" type="button" disabled={!req || exporter.busy} onClick={() => exportAs("csv")}>
                    <Icon name="download" size={14} />
                    CSV
                  </button>
                </Tip>
                <Tip title={exportTip("导出 XLSX")}>
                  <button className="btn s" type="button" disabled={!req || exporter.busy} onClick={() => exportAs("xlsx")}>
                    <Icon name="download" size={14} />
                    XLSX
                  </button>
                </Tip>
                <Dropdown
                  disabled={!req || exporter.busy || hasPosition(req.scope)}
                  trigger={["click"]}
                  menu={{
                    items: [
                      { key: "csv", label: "CSV" },
                      { key: "xlsx", label: "XLSX" },
                    ],
                    onClick: ({ key }) => tidyExport(key as "csv" | "xlsx"),
                  }}
                >
                  <button className="btn s" type="button" disabled={!req || exporter.busy || hasPosition(req.scope)} title={hasPosition(req?.scope) ? POSITION_OFF : undefined}>
                    <Icon name="download" size={14} />
                    导出整洁数据
                  </button>
                </Dropdown>
              </div>
              <ErrorAlert error={parseBad || alignedError ? null : search.error} style={{ margin: 16 }} />
              {pollError ? <ErrorAlert error={pollError} style={{ margin: 16 }} /> : null}
              {counts?.failed && (
                <div className="alert warn" role="alert" style={{ margin: 16 }}>
                  <Icon name="info" size={14} />
                  <span className="grow">{counts.message || "计数失败，请缩小范围或加条件"}</span>
                </div>
              )}
              {search.isFetching && !result ? (
                <div className="col" style={{ padding: 16 }}>
                  {Array.from({ length: 6 }, (_, i) => (
                    <span key={i} className="skel h20" />
                  ))}
                </div>
              ) : result && result.items.length === 0 ? (
                <>
                  <Empty icon="searchx" text="没有命中" />
                  {altScript.data && (
                    <div className="alert info" style={{ margin: "0 16px 16px" }}>
                      <Icon name="info" size={14} />
                      <span className="grow">
                        该库为{altScript.data.to === "traditional" ? "繁体" : "简体"}，试试「{altScript.data.query}」
                        {altScript.data.hits != null ? `（${fmt(altScript.data.hits)} 次）` : ""}
                      </span>
                      <button
                        className="btn xs"
                        type="button"
                        onClick={() => {
                          setQuery(altScript.data!.query);
                          run({ query: altScript.data!.query });
                        }}
                      >
                        检索「{altScript.data.query}」
                      </button>
                    </div>
                  )}
                </>
              ) : (
                result && (
                  <div className="kwic-scroll" style={{ opacity: search.isFetching ? 0.55 : 1, transition: "opacity 200ms" }}>
                    <KwicTable
                      rows={rows}
                      wrap={ctxMode !== "char"}
                      terms={terms}
                      posColor={posOn && posAvailable}
                      selected={selected}
                      onSelect={setSelected}
                      expanded={expanded}
                      onExpand={setExpanded}
                      marks={markLayer ? rowMarks : undefined}
                      extraActions={(r) => {
                        const hit = rows.find((x) => x.id === r.id)?.hit;
                        return hit ? (
                          <span className="act-term">
                            <TermExampleButton projectId={projectId} hit={hit} source={r.evidence?.source ?? hit.document_title} />
                          </span>
                        ) : null;
                      }}
                      renderExpanded={
                        treeLayer || nativeTree
                          ? (r) => {
                              const hit = rows.find((x) => x.id === r.id)?.hit;
                              return hit ? <SentenceTree layerId={treeLayer} corpusId={hitCorpusId} posLayerId={req?.layers?.pos ?? null} hit={hit} projectId={projectId} /> : null;
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
                    {fmt(from)}–{fmt(from + result.items.length - 1)} / {total != null ? fmt(total) : counts?.failed ? "未完成" : "计算中"}
                  </span>
                  <div className="grow" />
                  <Pager page={result.page} pages={pages} onChange={changePage} />
                </div>
              )}
            </div>
            <ContextInspector
              hit={selectedHit}
              terms={terms}
              evidence={selectedHit && req ? hitEvidence(selectedHit, req.query, req.scope, corpusName) : null}
              alignLayer={alignLayer}
              projectId={projectId}
              parallel={parallel}
              onClose={() => setSelected(null)}
            />
          </section>
        )}
        </>
        )}
      </div>

      <SampleDialog open={sampling} onClose={() => setSampling(false)} projectId={projectId} req={toolReq} hits={counts?.complete ? counts.hits : null} />

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

function SearchMode({ value, onChange, semanticOff }: { value: "query" | "semantic"; onChange: (v: "query" | "semantic") => void; semanticOff?: string }) {
  return (
    <div className="seg-mini" role="tablist" aria-label="检索方式">
      {(
        [
          ["query", "查询式"],
          ["semantic", "语义"],
        ] as const
      ).map(([v, l]) => (
        <button
          key={v}
          type="button"
          role="tab"
          aria-selected={value === v}
          disabled={v === "semantic" && !!semanticOff}
          title={v === "semantic" ? semanticOff : undefined}
          onClick={() => onChange(v)}
        >
          {l}
        </button>
      ))}
    </div>
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
