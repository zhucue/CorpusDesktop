import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Drawer, Form, Input, InputNumber, Popconfirm, Select, Tabs } from "antd";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { MAX_PAGE_SIZE, api, errorText, type Job, type MetadataField, type Page, type Scope, type StatMethod, type StatResult } from "../../api";
import { Empty, ErrorAlert, exportTip, Skeleton, Tip } from "../../components/common";
import { ScopeSelect } from "../../components/common/ScopeSelect";
import { Icon } from "../../components/Icon";
import { statIcon } from "../../components/iconSets";
import { download, type EChartHandle } from "../../components/results/EChart";
import { PageHeader } from "../../components/shell/AppShell";
import { useShell } from "../../components/shell/shell";
import { describeScope, useCorpora, useJobCreated, useProjectId, useSubcorpora } from "../../lib/data";
import { fmt, fmtShortTime, fmtVersion } from "../../lib/format";
import { StatChart } from "./StatChart";
import { methodLabels, StatTable } from "./StatTable";
import "./stats.css";
import { useStatJob, useStatResult } from "./useStatJob";
import { useLayers } from "../annotate/data";
import { AlignmentStatsCard } from "../annotate/AlignStats";

const METHODS: StatMethod[] = ["frequency", "ngrams", "collocations", "keywords", "distribution"];

const UNIT_OPTIONS = [
  { value: "word", label: "词形" },
  { value: "lemma", label: "词元" },
];
const POS_OPTIONS = [
  ["NOUN", "名词"],
  ["VERB", "动词"],
  ["ADJ", "形容词"],
  ["ADV", "副词"],
  ["PRON", "代词"],
  ["ADP", "介词"],
  ["NUM", "数词"],
  ["PROPN", "专名"],
].map(([v, l]) => ({ value: v, label: `${l} ${v}` }));
const TOP_OPTIONS = [50, 100, 200].map((n) => ({ value: n, label: `前 ${n}` }));
const MEASURES = [
  { value: "logdice", label: "logDice" },
  { value: "mi", label: "MI" },
  { value: "t", label: "t 值" },
  { value: "ll", label: "LL" },
];

type Body = Record<string, unknown>;

function ParamsCard({ children, onSubmit, running, form }: { children: React.ReactNode; onSubmit: () => void; running: boolean; form: ReturnType<typeof Form.useForm>[0] }) {
  return (
    <Form form={form} className="card params" layout="vertical" onFinish={onSubmit} requiredMark={false}>
      {children}
      <div className="grow" />
      <button className="btn p" type="submit" disabled={running}>
        {running ? <span className="spin" /> : <Icon name="play" size={14} />}
        计算
      </button>
    </Form>
  );
}

/** Stored scopes carry nulls and a display name; the form wants a request scope. */
function toScope(v: unknown): Scope | undefined {
  const s = (v ?? {}) as { corpus_id?: string | null; subcorpus_id?: string | null; filter?: Record<string, unknown> | null };
  if (s.subcorpus_id) return { subcorpus_id: s.subcorpus_id };
  if (s.corpus_id && s.filter) return { corpus_id: s.corpus_id, filter: s.filter } as unknown as Scope;
  if (s.corpus_id) return { corpus_id: s.corpus_id };
  return undefined;
}

/** Form values that reproduce a stored result's request (its method tab is chosen by the caller). */
function formValues(stat: StatResult): Body {
  const p = stat.params as Body;
  const v: Body = { unit: p.unit, pos: p.pos ?? undefined, min_freq: p.min_freq, top: p.top };
  const lay = p.layers as { span?: string; relation?: string } | undefined;
  if (lay?.span || lay?.relation) v.layer_id = lay.span ?? lay.relation;
  if (stat.method === "keywords") Object.assign(v, { target: toScope(p.target) ?? toScope(stat.scope), reference: toScope(p.reference), measure: p.measure });
  else v.scope = toScope(p.scope) ?? toScope(stat.scope);
  if (stat.method === "ngrams") Object.assign(v, { n: p.n, pos_pattern: Array.isArray(p.pos_pattern) ? p.pos_pattern.join(" ") : undefined });
  if (stat.method === "collocations") Object.assign(v, { node: p.node, window: p.window, measure: Array.isArray(p.measures) ? p.measures[0] : undefined });
  if (stat.method === "distribution") Object.assign(v, { query: p.query ?? undefined, field: p.field, bins: p.bins });
  return Object.fromEntries(Object.entries(v).filter(([, x]) => x !== undefined && x !== null));
}

function scopeRule(msg = "请选择范围") {
  return [{ required: true, message: msg }];
}

/** Parameter form per method; builds the POST /stats/{method} body from contracts/p2.md §三. */
function MethodForm({
  method,
  projectId,
  defaultScope,
  initial,
  running,
  onRun,
}: {
  method: StatMethod;
  projectId: string;
  defaultScope: Scope | null;
  initial?: StatResult;
  running: boolean;
  onRun: (body: Body) => void;
}) {
  const [form] = Form.useForm();
  const corpora = useCorpora(projectId);
  const subs = useSubcorpora(projectId);
  const scope = Form.useWatch("scope", form) as Scope | undefined;
  const corpusId = describeScope(scope ?? null, corpora.data?.items ?? [], subs.data?.items ?? []).corpus?.id;
  const fields = useQuery({
    queryKey: ["metadata-fields", corpusId],
    queryFn: () => api.get<MetadataField[]>(`/corpora/${corpusId}/metadata-fields`),
    enabled: method === "distribution" && !!corpusId,
  });
  const field = Form.useWatch("field", form);
  const unit = Form.useWatch("unit", form) as string | undefined;
  const layers = useLayers(projectId);
  const labelUnit = method === "frequency" && (unit === "span_label" || unit === "relation_label");
  const unitLayers = (layers.data ?? []).filter((l) => l.kind === (unit === "relation_label" ? "relation" : "span") && l.status === "ready" && (!corpusId || l.corpus_id === corpusId));

  useEffect(() => {
    if (initial?.method === method) return; // the opened result's own scope wins
    if (defaultScope && !form.getFieldValue(method === "keywords" ? "target" : "scope")) form.setFieldValue(method === "keywords" ? "target" : "scope", defaultScope);
  }, [defaultScope, form, method, initial?.method]);
  // An opened result (?stat=, 统计结果 drawer) shows the parameters it was computed with.
  useEffect(() => {
    if (initial && initial.method === method) form.setFieldsValue(formValues(initial));
  }, [initial?.id, method]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = () => {
    const v = form.getFieldsValue(true) as Body;
    const body: Body = { project_id: projectId };
    if (method === "frequency") {
      const spanUnit = v.unit === "span_label" || v.unit === "relation_label";
      Object.assign(body, { scope: v.scope, unit: v.unit, pos: spanUnit ? undefined : v.pos || undefined, top: v.top, min_freq: v.min_freq });
      if (spanUnit && v.layer_id) body.layers = { [v.unit === "span_label" ? "span" : "relation"]: v.layer_id };
    }
    if (method === "ngrams")
      Object.assign(body, {
        scope: v.scope,
        n: v.n,
        unit: v.unit,
        pos_pattern: typeof v.pos_pattern === "string" && v.pos_pattern.trim() ? v.pos_pattern.trim().split(/\s+/) : undefined,
        top: v.top,
        min_freq: v.min_freq,
      });
    if (method === "collocations") {
      const order = [v.measure as string, ...MEASURES.map((m) => m.value).filter((m) => m !== v.measure)];
      Object.assign(body, { scope: v.scope, node: String(v.node).trim(), window: v.window, unit: v.unit, pos: v.pos || undefined, measures: order, min_freq: v.min_freq, top: v.top });
    }
    if (method === "keywords") Object.assign(body, { target: v.target, reference: v.reference, unit: v.unit, measure: v.measure, min_freq: v.min_freq, top: v.top });
    if (method === "distribution")
      Object.assign(body, { scope: v.scope, query: typeof v.query === "string" && v.query.trim() ? v.query.trim() : undefined, field: v.field, bins: v.field === "position" ? v.bins : undefined });
    onRun(body);
  };

  const scopeField = (
    <Form.Item name="scope" label="范围" rules={scopeRule()}>
      <ScopeSelect projectId={projectId} value={form.getFieldValue("scope")} onChange={(s) => form.setFieldValue("scope", s)} />
    </Form.Item>
  );
  const minFreq = (n: number) => (
    <Form.Item name="min_freq" label="最低频次" initialValue={n}>
      <InputNumber min={1} className="mono" style={{ width: 96 }} />
    </Form.Item>
  );
  const top = (
    <Form.Item name="top" label="显示" initialValue={200}>
      <Select options={TOP_OPTIONS} style={{ width: 96 }} />
    </Form.Item>
  );

  return (
    <ParamsCard form={form} onSubmit={submit} running={running}>
      {method === "keywords" ? (
        <>
          <Form.Item name="target" label="目标" rules={scopeRule("请选择目标")}>
            <ScopeSelect projectId={projectId} value={form.getFieldValue("target")} onChange={(s) => form.setFieldValue("target", s)} width={200} />
          </Form.Item>
          <Form.Item name="reference" label="参照" rules={scopeRule("请选择参照")}>
            <ScopeSelect projectId={projectId} value={form.getFieldValue("reference")} onChange={(s) => form.setFieldValue("reference", s)} width={200} />
          </Form.Item>
        </>
      ) : (
        scopeField
      )}
      {method === "collocations" && (
        <Form.Item name="node" label="节点词" rules={[{ required: true, whitespace: true, message: "请输入查询式" }]}>
          <Input className="mono" style={{ width: 150 }} placeholder="翻译/v" />
        </Form.Item>
      )}
      {method === "distribution" && (
        <Form.Item name="query" label="查询式">
          <Input className="mono" style={{ width: 200 }} placeholder="翻译/v +文化" />
        </Form.Item>
      )}
      {method === "ngrams" && (
        <Form.Item name="n" label="n" initialValue={2}>
          <Select options={[2, 3, 4].map((n) => ({ value: n, label: String(n) }))} style={{ width: 72 }} />
        </Form.Item>
      )}
      {method !== "distribution" && (
        <Form.Item name="unit" label="单位" initialValue="word">
          <Select
            options={method === "frequency" ? [...UNIT_OPTIONS, { value: "pos", label: "词性" }, { value: "span_label", label: "片段标签" }, { value: "relation_label", label: "关系标签" }] : UNIT_OPTIONS}
            style={{ width: method === "frequency" ? 112 : 96 }}
          />
        </Form.Item>
      )}
      {labelUnit && (
        <Form.Item name="layer_id" label={unit === "relation_label" ? "关系层" : "片段层"}>
          <Select allowClear style={{ width: 180 }} placeholder="最近更新的层" options={unitLayers.map((l) => ({ value: l.id, label: l.name }))} />
        </Form.Item>
      )}
      {(method === "collocations" || (method === "frequency" && !labelUnit)) && (
        <Form.Item name="pos" label={method === "collocations" ? "搭配词词性" : "词性"}>
          <Select allowClear placeholder="全部" options={POS_OPTIONS} style={{ width: 136 }} />
        </Form.Item>
      )}
      {method === "ngrams" && (
        <Form.Item name="pos_pattern" label="词性模式">
          <Input className="mono" placeholder="VERB NOUN" style={{ width: 160 }} />
        </Form.Item>
      )}
      {method === "collocations" && (
        <>
          <Form.Item name="window" label="窗口 ±" initialValue={5}>
            <InputNumber min={1} max={10} className="mono" style={{ width: 80 }} />
          </Form.Item>
          <Form.Item name="measure" label="排序指标" initialValue="logdice">
            <Select options={MEASURES} style={{ width: 104 }} />
          </Form.Item>
        </>
      )}
      {method === "keywords" && (
        <Form.Item name="measure" label="指标" initialValue="ll">
          <Select options={[{ value: "ll", label: "LL" }, { value: "log_ratio", label: "Log Ratio" }]} style={{ width: 110 }} />
        </Form.Item>
      )}
      {method === "distribution" && (
        <>
          <Form.Item name="field" label="按" initialValue="position" rules={[{ required: true }]}>
            <Select
              style={{ width: 150 }}
              loading={fields.isFetching}
              options={[{ value: "position", label: "文档位置" }, ...(fields.data ?? []).map((f) => ({ value: f.field, label: f.field === "year" ? "年份 year" : f.field }))]}
            />
          </Form.Item>
          {field === "position" && (
            <Form.Item name="bins" label="区间" initialValue={10}>
              <InputNumber min={2} max={50} className="mono" style={{ width: 80 }} />
            </Form.Item>
          )}
        </>
      )}
      {method !== "distribution" && minFreq(method === "frequency" ? 1 : method === "ngrams" ? 2 : 3)}
      {method !== "distribution" && top}
    </ParamsCard>
  );
}

function ResultView({ stat, projectId, chartRef }: { stat: StatResult; projectId: string; chartRef: React.Ref<EChartHandle> }) {
  const { message } = App.useApp();
  const jobCreated = useJobCreated();
  const [view, setView] = useState<"network" | "bar">("network");
  const [picked, setPicked] = useState<number | null>(null);
  const measure = stat.method === "collocations" ? String(((stat.params as { measures?: string[] }).measures ?? ["logdice"])[0]) : undefined;
  const exportJob = useMutation({
    mutationFn: (format: "csv" | "xlsx") => api.post<Job>(`/stats/${stat.id}/export`, { format }),
    onSuccess: (_, f) => {
      jobCreated(projectId);
      message.success(
        <span>
          已提交导出任务：{f.toUpperCase()}，<Link to={`/p/${projectId}/jobs`}>查看任务</Link>
        </span>,
      );
    },
    onError: (e) => message.error(errorText(e)),
  });

  const t = stat.totals;
  const meta = (
    <span className="res-meta">
      <span>{stat.scope.name}</span> · <span className="num">{fmt(t.tokens)}</span> 词
      {stat.method === "keywords" && t.reference && (
        <>
          对 <span className="num">{fmt(t.reference.tokens)}</span> 词
        </>
      )}
      {stat.method === "collocations" && t.node_hits != null && (
        <>
          · 节点 <span className="num">{fmt(t.node_hits)}</span> 次
        </>
      )}
      {stat.method === "distribution" && t.hits != null && (
        <>
          · <span className="num">{fmt(t.hits)}</span> 命中
        </>
      )}
      · 索引 {fmtVersion(stat.index_version)} · {fmtShortTime(stat.created_at)} ·{" "}
      <span className="num">
        {fmt(stat.rows.length)}
        {stat.row_count > stat.rows.length ? ` / ${fmt(stat.row_count)}` : ""}
      </span>{" "}
      项
    </span>
  );

  const table = (
    <div className="card">
      <div className="card-head">
        <h2>{stat.method === "ngrams" ? `${(stat.params as { n?: number }).n ?? ""}-gram` : methodLabels[stat.method]}</h2>
        {meta}
        <div className="grow" />
        <Tip title={exportTip("导出 CSV")}>
          <button className="btn xs" type="button" disabled={exportJob.isPending} onClick={() => exportJob.mutate("csv")}>
            CSV
          </button>
        </Tip>
        <Tip title={exportTip("导出 XLSX")}>
          <button className="btn xs" type="button" disabled={exportJob.isPending} onClick={() => exportJob.mutate("xlsx")}>
            XLSX
          </button>
        </Tip>
      </div>
      {stat.rows.length === 0 ? (
        <Empty icon="barchart" text={`当前参数下无结果${(stat.params as { min_freq?: number }).min_freq ? `（最低频次 ${(stat.params as { min_freq?: number }).min_freq}）` : ""}`} />
      ) : (
        <div className="stat-scroll">
          <StatTable stat={stat} projectId={projectId} highlight={measure} selected={picked} cellBar={stat.method === "ngrams" ? "freq" : undefined} />
        </div>
      )}
    </div>
  );
  if (stat.method === "ngrams" || stat.rows.length === 0) return table;

  const chartTitle =
    stat.method === "frequency"
      ? `前 10 · ${stat.columns.some((c) => c.key === "per_million") ? "每百万词" : "频次"}`
      : stat.method === "collocations"
        ? "搭配强度"
        : stat.method === "keywords"
          ? "Log Ratio × LL"
          : distTitle(stat);
  const chart = (
    <div className="card card-pad col gap-16 chart-card">
      <div className="row between">
        <h2>{chartTitle}</h2>
        {stat.method === "collocations" && (
          <div className="seg-mini" role="tablist" aria-label="图表">
            <button type="button" role="tab" aria-selected={view === "network"} onClick={() => setView("network")}>
              网络
            </button>
            <button type="button" role="tab" aria-selected={view === "bar"} onClick={() => setView("bar")}>
              条形
            </button>
          </div>
        )}
      </div>
      <StatChart ref={chartRef} stat={stat} measure={measure} view={view} onPick={setPicked} />
      {stat.method === "collocations" && view === "network" && <div className="small muted" style={{ textAlign: "center" }}>距离 / 线宽 = {measure}</div>}
    </div>
  );
  return <div className={`res ${stat.method === "distribution" ? "dist" : ""}`}>{stat.method === "distribution" ? [chart, table] : [table, chart]}</div>;
}

function distTitle(stat: StatResult): string {
  const field = String((stat.params as { field?: string }).field ?? "");
  const by = field === "position" ? "按文档位置" : `按 ${field}`;
  return stat.rows.some((r) => r.values.per_million != null) ? `每百万词 · ${by}` : `词数 · ${by}`;
}

function SavedResults({ open, onClose, projectId, onOpen }: { open: boolean; onClose: () => void; projectId: string; onOpen: (s: StatResult) => void }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const list = useQuery({
    queryKey: ["stats-list", projectId],
    queryFn: () => api.get<Page<StatResult>>(`/projects/${projectId}/stats`, { page_size: MAX_PAGE_SIZE }),
    enabled: open,
  });
  const del = useMutation({
    mutationFn: (id: string) => api.del(`/stats/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["stats-list", projectId] }),
    onError: (e) => message.error(errorText(e)),
  });
  return (
    <Drawer open={open} onClose={onClose} width={420} title="统计结果">
      <ErrorAlert error={list.error} />
      {list.isPending && <Skeleton />}
      {list.data?.items.length === 0 && <Empty icon="barchart" text="暂无统计结果" />}
      <div className="col" style={{ gap: 4 }}>
        {list.data?.items.map((s) => (
          <div key={s.id} className="list-item" role="button" tabIndex={0} onClick={() => onOpen(s)} onKeyDown={(e) => e.key === "Enter" && onOpen(s)}>
            <span className="tag t-info">
              <Icon name={statIcon[s.method] ?? "barchart"} size={12} />
              {methodLabels[s.method]}
            </span>
            <div className="grow col" style={{ gap: 2 }}>
              <span className="li-title ellipsis">{summary(s)}</span>
              <span className="small muted num">
                {s.scope.name} · {fmt(s.row_count)} 项 · {fmtVersion(s.index_version)} · {fmtShortTime(s.created_at)}
              </span>
            </div>
            <Popconfirm title="删除这条结果？" okText="删除" cancelText="取消" onConfirm={() => del.mutate(s.id)}>
              <button className="btn ghost icon danger" type="button" aria-label="删除" onClick={(e) => e.stopPropagation()}>
                <Icon name="trash" size={14} />
              </button>
            </Popconfirm>
          </div>
        ))}
      </div>
    </Drawer>
  );
}

function summary(s: StatResult): string {
  const p = s.params as Record<string, unknown>;
  if (s.method === "collocations") return `${p.node ?? ""} · ±${p.window ?? ""}`;
  if (s.method === "distribution") return `${p.query ?? "全部"} · ${p.field ?? ""}`;
  if (s.method === "ngrams") return `${p.n ?? ""}-gram · ${p.unit ?? ""}`;
  if (s.method === "keywords") return `${p.measure ?? ""} · ${p.unit ?? ""}`;
  return `${p.unit ?? ""}${p.pos ? ` · ${p.pos}` : ""}`;
}

export default function Stats() {
  const projectId = useProjectId();
  const shell = useShell();
  const allLayers = useLayers(projectId);
  const alignLayers = (allLayers.data ?? []).filter((l) => l.kind === "alignment" && l.status === "ready");
  const [tab, setTab] = useState<StatMethod>("frequency");
  const [runs, setRuns] = useState<Partial<Record<StatMethod, { body: Body; n: number }>>>({});
  const [opened, setOpened] = useState<Partial<Record<StatMethod, string>>>({});
  const [savedOpen, setSavedOpen] = useState(false);
  const chartRef = useRef<EChartHandle>(null);
  const [params] = useSearchParams();
  const linked = useStatResult(params.get("stat"));
  useEffect(() => {
    const s = linked.data;
    if (!s) return;
    setTab(s.method);
    setOpened((o) => ({ ...o, [s.method]: s.id }));
  }, [linked.data]);

  const live = useStatJob(tab, runs[tab]?.body ?? null, projectId, runs[tab]?.n ?? 0);
  const savedId = opened[tab];
  const saved = useStatResult(savedId);
  const stat = savedId ? saved.data : live.stat;
  const running = !savedId && live.running;
  const error = savedId ? saved.error : (live.error ?? (params.get("stat") && !linked.data ? linked.error : null));

  // 1–5 switch method.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && e.target.closest("input, textarea, select, .ant-select")) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const n = Number(e.key);
      if (n >= 1 && n <= 5) setTab(METHODS[n - 1]);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  async function exportChart(kind: "svg" | "png") {
    const h = chartRef.current;
    if (!h || !stat) return;
    const url = kind === "svg" ? h.svgDataUrl() : await h.pngDataUrl();
    if (url) download(url, `${methodLabels[stat.method]}-${stat.id.slice(0, 8)}.${kind}`);
  }

  const hasChart = !!stat && stat.method !== "ngrams" && stat.rows.length > 0;
  return (
    <>
      <PageHeader
        title="统计"
        busy={running}
        actions={
          <>
            <button className="btn s" type="button" onClick={() => setSavedOpen(true)}>
              <Icon name="history" size={14} />
              <span className="lbl">统计结果</span>
            </button>
            <button className="btn s" type="button" disabled={!hasChart} onClick={() => exportChart("svg")}>
              <Icon name="download" size={14} />
              SVG
            </button>
            <button className="btn s" type="button" disabled={!hasChart} onClick={() => exportChart("png")}>
              <Icon name="download" size={14} />
              PNG
            </button>
          </>
        }
      />
      <div className="content">
        <Tabs
          activeKey={tab}
          onChange={(k) => setTab(k as StatMethod)}
          items={METHODS.map((m) => ({ key: m, label: methodLabels[m], icon: <Icon name={statIcon[m]} size={14} /> }))}
          className="stat-tabs"
        />
        <div className="col gap-20 panel-in" key={tab}>
          <MethodForm
            method={tab}
            projectId={projectId}
            defaultScope={shell.scope}
            initial={savedId ? saved.data : undefined}
            running={running}
            onRun={(body) => {
              setOpened((o) => ({ ...o, [tab]: undefined }));
              setRuns((r) => ({ ...r, [tab]: { body, n: (r[tab]?.n ?? 0) + 1 } }));
            }}
          />
          {error ? <ErrorAlert error={error} /> : null}
          {running && (
            <div className="card">
              <div className="card-head">
                <h2>结果</h2>
                <span className="res-meta">
                  {live.job ? (
                    <>
                      任务 #{live.job.id.slice(0, 8)} · {live.job.state === "queued" ? "排队中" : "计算中"}
                      {live.job.progress.total ? ` · ${fmt(live.job.progress.done)} / ${fmt(live.job.progress.total)}` : ""}
                    </>
                  ) : (
                    "提交中"
                  )}
                </span>
              </div>
              <Skeleton rows={6} />
            </div>
          )}
          {!running && stat && <ResultView key={stat.id} stat={stat} projectId={projectId} chartRef={chartRef} />}
          {!running && !stat && !error && <Empty icon="sigma" text="设置参数后点“计算”" />}
          {tab === "frequency" && alignLayers.length > 0 && <AlignmentStatsCard projectId={projectId} layers={alignLayers} />}
        </div>
      </div>
      <SavedResults
        open={savedOpen}
        onClose={() => setSavedOpen(false)}
        projectId={projectId}
        onOpen={(s) => {
          setTab(s.method);
          setOpened((o) => ({ ...o, [s.method]: s.id }));
          setSavedOpen(false);
        }}
      />
    </>
  );
}
