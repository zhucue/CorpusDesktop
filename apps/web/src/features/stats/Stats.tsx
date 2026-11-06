import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Checkbox, Drawer, Form, Input, InputNumber, Popconfirm, Select, Tabs } from "antd";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { MAX_PAGE_SIZE, api, errorCode, errorText, type StatMethod, type Corpus, type MetadataField, type Page, type Scope, type StatResult } from "../../api";
import { Empty, ErrorAlert, exportTip, IndexPendingNote, Skeleton, Tip } from "../../components/common";
import { ScopeSelect } from "../../components/common/ScopeSelect";
import { Icon, type IconName } from "../../components/Icon";
import { MethodAppendix } from "../../components/global/MethodAppendix";
import { statIcon } from "../../components/iconSets";
import { download, downloadText, type EChartHandle } from "../../components/results/EChart";
import { PageHeader } from "../../components/shell/AppShell";
import { useShell } from "../../components/shell/shell";
import { describeScope, sameScope, useCorpora, useProjectId, useSubcorpora } from "../../lib/data";
import { useExportJob } from "../../lib/exportJob";
import { fmt, fmtRelative, fmtShortTime } from "../../lib/format";
import { measureKey } from "./columns";
import { type Body, fieldLabel, ParamsCard, POS_OPTIONS, scopeRule, toScope } from "./formParts";
import { isP10, P10MethodForm } from "./P10Forms";
import { P10Result } from "./P10Results";
import { TidyExportDialog } from "./TidyExport";
import { MEASURE_LABELS, StatChart } from "./StatChart";
import { methodLabels, StatTable } from "./StatTable";
import "./stats.css";
import { useStatJob, useStatResult } from "./useStatJob";
import { useLayers } from "../annotate/data";
import { AlignmentStatsCard } from "../annotate/AlignStats";

const METHODS: StatMethod[] = [
  "frequency",
  "ngrams",
  "collocations",
  "keywords",
  "distribution",
  "breakdown",
  "translations",
  "text_metrics",
  "vocab_profile",
  "compare",
  "word_sketch",
  "sketch_diff",
];
/** Methods with the 排除标点和数字 option (word / lemma units). */
const PUNCT_METHODS: StatMethod[] = ["frequency", "ngrams", "collocations", "keywords", "translations"];
/** Methods whose form offers the corpus's metadata fields. */
const FIELD_METHODS: StatMethod[] = ["frequency", "distribution", "breakdown", "translations"];

const methodIcon = (m: StatMethod): IconName => statIcon[m] ?? "barchart";

const UNIT_OPTIONS = [
  { value: "word", label: "词形" },
  { value: "lemma", label: "词元" },
];
const TOP_OPTIONS = [50, 100, 200].map((n) => ({ value: n, label: `前 ${n}` }));
const MEASURES = ["logdice", "mi", "t", "ll", "mi3", "delta_p", "z"].map((m) => ({ value: m, label: MEASURE_LABELS[m] }));
const DEFAULT_MEASURES = ["logdice", "mi", "t", "ll"];
const KEYWORD_MEASURES = [
  { value: "ll", label: "LL" },
  { value: "log_ratio", label: "Log Ratio" },
  { value: "pct_diff", label: "%DIFF" },
  { value: "odds_ratio", label: "Odds Ratio" },
];
const DIRECTIONS = [
  { value: "positive", label: "正（目标多）" },
  { value: "negative", label: "负（参照多）" },
  { value: "both", label: "双向" },
];
const BREAKDOWN_BY = [
  { value: "word", label: "词形" },
  { value: "lemma", label: "词元" },
  { value: "pos", label: "词性" },
  { value: "left1", label: "左一词" },
  { value: "right1", label: "右一词" },
  { value: "meta", label: "元数据字段" },
];
/** Simplified / traditional script of a corpus (`meta.script`), as 简体 / 繁体; null when unknown. */
function corpusScript(c: Corpus | null | undefined): "简体" | "繁体" | null {
  const s = (c?.meta as { script?: unknown } | undefined)?.script;
  if (typeof s !== "string") return null;
  const v = s.toLowerCase();
  if (["simplified", "hans", "zh-hans", "zh-cn", "简体", "简"].includes(v)) return "简体";
  if (["traditional", "hant", "zh-hant", "zh-tw", "zh-hk", "繁体", "繁"].includes(v)) return "繁体";
  return null;
}

/** The plain corpus / subcorpus scope a stored result was computed on (target for keywords), for the shared scope. */
function resultScope(stat: StatResult): Scope | undefined {
  const p = stat.params as Body;
  const first = stat.method === "compare" && Array.isArray(p.items) ? (p.items as Body[])[0]?.scope : undefined;
  const s = toScope(stat.method === "keywords" ? p.target : (first ?? p.scope)) ?? toScope(stat.scope);
  return s && !("filter" in s) ? s : undefined;
}

/** Form values that reproduce a stored result's request (its method tab is chosen by the caller). */
function formValues(stat: StatResult): Body {
  const p = stat.params as Body;
  const v: Body = { unit: p.unit, pos: p.pos ?? undefined, min_freq: p.min_freq, top: p.top, exclude_punct: p.exclude_punct ?? false };
  const lay = p.layers as { span?: string; relation?: string } | undefined;
  if (lay?.span || lay?.relation) v.layer_id = lay.span ?? lay.relation;
  if (stat.method === "keywords") Object.assign(v, { target: toScope(p.target) ?? toScope(stat.scope), reference: toScope(p.reference), measure: p.measure });
  else v.scope = toScope(p.scope) ?? toScope(stat.scope);
  if (stat.method === "ngrams") Object.assign(v, { n: p.n, pos_pattern: Array.isArray(p.pos_pattern) ? p.pos_pattern.join(" ") : undefined, contains: p.contains ?? undefined });
  if (stat.method === "collocations")
    Object.assign(v, { node: p.node, window: p.window, measure: Array.isArray(p.measures) ? p.measures[0] : undefined, measures: Array.isArray(p.measures) ? p.measures : undefined });
  if (stat.method === "distribution") Object.assign(v, { query: p.query ?? undefined, field: p.field, bins: p.bins });
  if (stat.method === "frequency" && typeof p.parts === "string") v.parts = p.parts;
  if (stat.method === "keywords") Object.assign(v, { direction: p.direction ?? undefined, items: Array.isArray(p.items) && p.items.length ? p.items : undefined });
  if (stat.method === "breakdown") {
    const by = String(p.by ?? "word");
    Object.assign(v, { query: p.query ?? undefined, by: by.startsWith("meta:") ? "meta" : by, by_field: by.startsWith("meta:") ? by.slice(5) : undefined });
  }
  if (stat.method === "translations") Object.assign(v, { query: p.query ?? undefined, measure: p.measure, target_language: p.target_language ?? undefined });
  return Object.fromEntries(Object.entries(v).filter(([, x]) => x !== undefined && x !== null));
}

/** Warn when a keyword comparison mixes simplified and traditional corpora (meta.script). */
function ScriptWarning({ projectId, target, reference }: { projectId: string; target?: Scope | null; reference?: Scope | null }) {
  const corpora = useCorpora(projectId).data?.items ?? [];
  const subs = useSubcorpora(projectId).data?.items ?? [];
  if (!target || !reference) return null;
  const a = corpusScript(describeScope(target, corpora, subs).corpus);
  const b = corpusScript(describeScope(reference, corpora, subs).corpus);
  if (!a || !b || a === b) return null;
  return <Alert type="warning" showIcon message={`目标为${a}、参照为${b}：同一个词的简繁字形会被算作不同的词，关键词前列会是简繁差异。请选用同一字形的参照。`} />;
}

/** Parameter form per method; builds the POST /stats/{method} body from contracts/p2.md §三. */
function MethodForm({
  method,
  projectId,
  scope,
  onScope,
  reference,
  onReference,
  initial,
  running,
  onRun,
}: {
  method: StatMethod;
  projectId: string;
  /** The project's shared scope (lib/scope); the keyword target uses it too. */
  scope: Scope | null;
  onScope: (s: Scope) => void;
  reference: Scope | null;
  onReference: (s: Scope | null) => void;
  initial?: StatResult;
  running: boolean;
  onRun: (body: Body) => void;
}) {
  const [form] = Form.useForm();
  const corpora = useCorpora(projectId);
  const subs = useSubcorpora(projectId);
  const scopeKey = method === "keywords" ? "target" : "scope";
  const formScope = Form.useWatch(scopeKey, form) as Scope | undefined;
  const ref = Form.useWatch("reference", form) as Scope | undefined;
  const scopeCorpus = describeScope(formScope ?? null, corpora.data?.items ?? [], subs.data?.items ?? []).corpus;
  const corpusId = scopeCorpus?.id;
  // 译法 needs a parallel corpus; until the corpora load the range is not judged.
  const notParallel = method === "translations" && !!scopeCorpus && !scopeCorpus.parallel;
  const fields = useQuery({
    queryKey: ["metadata-fields", corpusId],
    queryFn: () => api.get<MetadataField[]>(`/corpora/${corpusId}/metadata-fields`),
    enabled: FIELD_METHODS.includes(method) && !!corpusId,
  });
  const fieldOptions = (fields.data ?? []).map((f) => ({ value: f.field, label: fieldLabel(f.field) }));
  const languages = (fields.data ?? []).find((f) => f.field === "language")?.values ?? [];
  const field = Form.useWatch("field", form);
  const unit = Form.useWatch("unit", form) as string | undefined;
  const by = Form.useWatch("by", form) as string | undefined;
  const kwItems = Form.useWatch("items", form) as string[] | undefined;
  const chosenMeasures = (Form.useWatch("measures", form) as string[] | undefined) ?? DEFAULT_MEASURES;
  const itemsMode = method === "keywords" && !!kwItems?.length;
  const dispersion = method === "frequency" && (unit === undefined || unit === "word" || unit === "lemma" || unit === "pos");
  const layers = useLayers(projectId);
  const labelUnit = method === "frequency" && (unit === "span_label" || unit === "relation_label");
  const unitLayers = (layers.data ?? []).filter((l) => l.kind === (unit === "relation_label" ? "relation" : "span") && l.status === "ready" && (!corpusId || l.corpus_id === corpusId));
  const punctOption = PUNCT_METHODS.includes(method) && (unit === undefined || unit === "word" || unit === "lemma");

  // The range follows the shared scope (palette, breadcrumb, other tabs, search); declared before the
  // opened-result effect so an opened result's own (possibly filtered) scope wins on mount.
  useEffect(() => {
    if (scope) form.setFieldValue(scopeKey, scope);
  }, [scope, scopeKey, form]);
  useEffect(() => {
    if (method === "keywords" && reference && !form.getFieldValue("reference")) form.setFieldValue("reference", reference);
  }, [method, reference, form]);
  // An opened result (?stat=, 统计结果 drawer) shows the parameters it was computed with.
  useEffect(() => {
    if (initial && initial.method === method) form.setFieldsValue(formValues(initial));
  }, [initial?.id, method]); // eslint-disable-line react-hooks/exhaustive-deps
  // The reference may not be the target: picking the reference's corpus as target clears it.
  useEffect(() => {
    if (method === "keywords" && formScope && ref && sameScope(formScope, ref)) {
      form.setFieldValue("reference", undefined);
      onReference(null);
    }
  }, [method, formScope, ref]); // eslint-disable-line react-hooks/exhaustive-deps

  // The sort measure is one of the chosen measures.
  const sortMeasure = Form.useWatch("measure", form) as string | undefined;
  useEffect(() => {
    if (method === "collocations" && sortMeasure && chosenMeasures.length && !chosenMeasures.includes(sortMeasure)) form.setFieldValue("measure", chosenMeasures[0]);
  }, [method, sortMeasure, chosenMeasures.join(" ")]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = () => {
    const v = form.getFieldsValue(true) as Body;
    const body: Body = { project_id: projectId };
    const punct = punctOption ? !!v.exclude_punct : undefined;
    if (method === "frequency") {
      const spanUnit = v.unit === "span_label" || v.unit === "relation_label";
      Object.assign(body, { scope: v.scope, unit: v.unit, pos: spanUnit ? undefined : v.pos || undefined, top: v.top, min_freq: v.min_freq, exclude_punct: punct });
      if (spanUnit && v.layer_id) body.layers = { [v.unit === "span_label" ? "span" : "relation"]: v.layer_id };
      if (dispersion) Object.assign(body, { parts: v.parts ?? "document", dispersion: true });
    }
    if (method === "ngrams")
      Object.assign(body, {
        scope: v.scope,
        n: v.n,
        unit: v.unit,
        pos_pattern: typeof v.pos_pattern === "string" && v.pos_pattern.trim() ? v.pos_pattern.trim().split(/\s+/) : undefined,
        contains: typeof v.contains === "string" && v.contains.trim() ? v.contains.trim() : undefined,
        top: v.top,
        min_freq: v.min_freq,
        exclude_punct: punct,
      });
    if (method === "collocations") {
      const chosen = (v.measures as string[] | undefined)?.length ? (v.measures as string[]) : DEFAULT_MEASURES;
      const sortBy = chosen.includes(v.measure as string) ? (v.measure as string) : chosen[0];
      // The first measure orders the rows (contracts/p2.md §三).
      const order = [sortBy, ...chosen.filter((m) => m !== sortBy)];
      Object.assign(body, { scope: v.scope, node: String(v.node).trim(), window: v.window, unit: v.unit, pos: v.pos || undefined, measures: order, min_freq: v.min_freq, top: v.top, exclude_punct: punct });
    }
    if (method === "keywords") {
      const items = (v.items as string[] | undefined)?.map((x) => x.trim()).filter(Boolean) ?? [];
      Object.assign(body, { target: v.target, reference: v.reference, unit: v.unit, measure: v.measure, min_freq: v.min_freq, top: v.top, exclude_punct: punct, direction: v.direction ?? "positive" });
      if (items.length) body.items = items;
    }
    if (method === "distribution") Object.assign(body, { scope: v.scope, query: String(v.query).trim(), field: v.field, bins: v.field === "position" ? v.bins : undefined });
    if (method === "breakdown")
      Object.assign(body, { scope: v.scope, query: String(v.query).trim(), by: v.by === "meta" ? `meta:${v.by_field}` : v.by, top: v.top, min_freq: v.min_freq });
    if (method === "translations")
      Object.assign(body, {
        scope: v.scope,
        query: String(v.query).trim(),
        unit: v.unit,
        measure: v.measure,
        target_language: v.target_language || undefined,
        top: v.top,
        min_freq: v.min_freq,
        exclude_punct: punct,
      });
    onRun(body);
  };

  const minFreq = (n: number) => (
    <Form.Item name="min_freq" label="最低频次" initialValue={n}>
      <InputNumber min={1} className="mono" style={{ width: 96 }} disabled={itemsMode} />
    </Form.Item>
  );
  const top = (n: number) => (
    <Form.Item name="top" label="显示" initialValue={n}>
      <Select options={TOP_OPTIONS} style={{ width: 96 }} />
    </Form.Item>
  );
  const queryField = (placeholder: string) => (
    <Form.Item name="query" label="查询式" rules={[{ required: true, whitespace: true, message: "请输入查询式" }]}>
      <Input className="mono" style={{ width: 200 }} placeholder={placeholder} />
    </Form.Item>
  );
  const defaultMinFreq = method === "frequency" || method === "breakdown" ? 1 : method === "ngrams" || method === "translations" ? 2 : 3;

  return (
    <>
      <ParamsCard form={form} onSubmit={submit} running={running} blocked={notParallel}>
        {method === "keywords" ? (
          <>
            <Form.Item name="target" label="目标" rules={scopeRule("请选择目标")}>
              <ScopeSelect projectId={projectId} value={form.getFieldValue("target")} onChange={onScope} width={200} />
            </Form.Item>
            <Form.Item
              name="reference"
              label="参照"
              rules={[
                ...scopeRule("请选择参照"),
                { validator: (_, v) => (v && sameScope(v, form.getFieldValue("target")) ? Promise.reject(new Error("参照与目标相同")) : Promise.resolve()) },
              ]}
            >
              <ScopeSelect projectId={projectId} value={form.getFieldValue("reference")} onChange={onReference} exclude={formScope} width={200} />
            </Form.Item>
          </>
        ) : (
          <Form.Item name="scope" label="范围" rules={scopeRule()} validateStatus={notParallel ? "error" : undefined} help={notParallel ? "仅平行语料" : undefined}>
            <ScopeSelect projectId={projectId} value={form.getFieldValue("scope")} onChange={onScope} />
          </Form.Item>
        )}
        {method === "collocations" && (
          <Form.Item name="node" label="节点词" rules={[{ required: true, whitespace: true, message: "请输入查询式" }]}>
            <Input className="mono" style={{ width: 150 }} placeholder="翻译/v" />
          </Form.Item>
        )}
        {method === "distribution" && queryField("翻译/v +文化")}
        {method === "breakdown" && queryField("翻译/v")}
        {method === "translations" && queryField("翻译")}
        {method === "breakdown" && (
          <>
            <Form.Item name="by" label="按" initialValue="word">
              <Select options={BREAKDOWN_BY} style={{ width: 120 }} />
            </Form.Item>
            {by === "meta" && (
              <Form.Item name="by_field" label="字段" rules={[{ required: true, message: "请选择字段" }]}>
                <Select style={{ width: 140 }} loading={fields.isFetching} options={fieldOptions} />
              </Form.Item>
            )}
          </>
        )}
        {method === "ngrams" && (
          <Form.Item name="n" label="n" initialValue={2}>
            <Select options={[2, 3, 4].map((n) => ({ value: n, label: String(n) }))} style={{ width: 72 }} />
          </Form.Item>
        )}
        {method !== "distribution" && method !== "breakdown" && (
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
        {dispersion && (
          <Form.Item name="parts" label="部分" initialValue="document">
            <Select
              style={{ width: 140 }}
              loading={fields.isFetching}
              options={[
                { value: "document", label: "文档" },
                { value: "segments", label: "等分 10 段" },
                ...(fieldOptions.length ? [{ label: "元数据字段", options: fieldOptions.map((o) => ({ value: `field:${o.value}`, label: o.label })) }] : []),
              ]}
            />
          </Form.Item>
        )}
        {method === "ngrams" && (
          <>
            <Form.Item name="contains" label="包含词">
              <Input className="mono" placeholder="文化" style={{ width: 120 }} allowClear />
            </Form.Item>
            <Form.Item name="pos_pattern" label="词性模式">
              <Input className="mono" placeholder="VERB NOUN" style={{ width: 160 }} />
            </Form.Item>
          </>
        )}
        {method === "collocations" && (
          <>
            <Form.Item name="window" label="窗口 ±" initialValue={5}>
              <InputNumber min={1} max={10} className="mono" style={{ width: 80 }} />
            </Form.Item>
            <Form.Item name="measures" label="指标" initialValue={DEFAULT_MEASURES} rules={[{ required: true, message: "至少选一个指标" }]}>
              <Select mode="multiple" options={MEASURES} style={{ minWidth: 200, maxWidth: 360 }} maxTagCount="responsive" />
            </Form.Item>
            <Form.Item name="measure" label="排序指标" initialValue="logdice">
              <Select options={MEASURES.filter((m) => chosenMeasures.includes(m.value))} style={{ width: 104 }} />
            </Form.Item>
          </>
        )}
        {method === "keywords" && (
          <>
            <Form.Item name="measure" label="排序指标" initialValue="ll">
              <Select options={KEYWORD_MEASURES} style={{ width: 120 }} />
            </Form.Item>
            <Form.Item name="direction" label="方向" initialValue="positive">
              <Select options={DIRECTIONS} style={{ width: 128 }} disabled={itemsMode} />
            </Form.Item>
            <Form.Item
              name="items"
              label="指定词对比"
              rules={[{ validator: (_, v?: string[]) => ((v?.length ?? 0) > 50 ? Promise.reject(new Error("最多 50 个词")) : Promise.resolve()) }]}
            >
              <Select
                mode="tags"
                open={false}
                suffixIcon={null}
                tokenSeparators={[" ", ",", "，", "、"]}
                placeholder="输入词后回车"
                style={{ minWidth: 180, maxWidth: 320 }}
                maxTagCount="responsive"
                aria-label="指定词对比"
              />
            </Form.Item>
          </>
        )}
        {method === "translations" && (
          <>
            <Form.Item name="measure" label="指标" initialValue="dice">
              <Select
                options={[
                  { value: "dice", label: "Dice" },
                  { value: "ll", label: "LL" },
                ]}
                style={{ width: 96 }}
              />
            </Form.Item>
            {languages.length > 0 && (
              <Form.Item name="target_language" label="译文语言">
                <Select allowClear placeholder="另一侧" style={{ width: 112 }} options={languages.map((l) => ({ value: String(l), label: String(l) }))} />
              </Form.Item>
            )}
          </>
        )}
        {method === "distribution" && (
          <>
            <Form.Item name="field" label="按" initialValue="position" rules={[{ required: true }]}>
              <Select style={{ width: 150 }} loading={fields.isFetching} options={[{ value: "position", label: "文档位置" }, ...fieldOptions]} />
            </Form.Item>
            {field === "position" && (
              <Form.Item name="bins" label="区间" initialValue={10}>
                <InputNumber min={2} max={50} className="mono" style={{ width: 80 }} />
              </Form.Item>
            )}
          </>
        )}
        {method !== "distribution" && minFreq(defaultMinFreq)}
        {method !== "distribution" && top(method === "translations" ? 100 : 200)}
        {punctOption && (
          <Form.Item name="exclude_punct" valuePropName="checked" initialValue={true} className="chk">
            <Checkbox>排除标点和数字</Checkbox>
          </Form.Item>
        )}
      </ParamsCard>
      {method === "keywords" && <ScriptWarning projectId={projectId} target={formScope} reference={ref} />}
      <IndexPendingNote corpus={scopeCorpus?.index_pending ? scopeCorpus : method === "keywords" ? describeScope(ref ?? null, corpora.data?.items ?? [], subs.data?.items ?? []).corpus : null} />
    </>
  );
}

function ResultView({ stat, projectId, chartRef }: { stat: StatResult; projectId: string; chartRef: React.Ref<EChartHandle> }) {
  const [view, setView] = useState<"network" | "bar">("network");
  const [picked, setPicked] = useState<number | null>(null);
  const [appendix, setAppendix] = useState(false);
  const exporter = useExportJob(projectId);
  const corpora = useCorpora(projectId);
  const corpus = corpora.data?.items.find((c) => c.id === stat.scope.corpus_id);
  const p = stat.params as Body;
  const measure =
    stat.method === "collocations"
      ? String(((p as { measures?: string[] }).measures ?? ["logdice"])[0])
      : stat.method === "translations"
        ? String(p.measure ?? "dice")
        : undefined;
  const runExport = (format: "csv" | "xlsx") => exporter.start({ url: `/stats/${stat.id}/export`, body: { format }, label: format.toUpperCase() });

  const t = stat.totals;
  const n = (v: number) => <span className="num">{fmt(v)}</span>;
  // Token totals count every token, punctuation included, also when punctuation is left out of the rows.
  const parts: React.ReactNode[] = [stat.scope.name];
  if (t.tokens != null)
    parts.push(
      <>
        {n(t.tokens)} 词（含标点）
        {stat.method === "keywords" && t.reference && <> 对 {n(t.reference.tokens)} 词</>}
      </>,
    );
  parts.push(...p10Meta(stat));
  if (stat.method === "collocations" && t.node_hits != null) parts.push(<>节点 {n(t.node_hits)} 次</>);
  if ((stat.method === "distribution" || stat.method === "breakdown") && t.hits != null) parts.push(<>{n(t.hits)} 命中</>);
  if (stat.method === "breakdown" && typeof p.by === "string") parts.push(`按${breakdownByLabel(p.by)}`);
  if (stat.method === "frequency" && t.parts != null) parts.push(<>{n(t.parts)} 部分（{partsLabel(String(p.parts ?? "document"))}）</>);
  if (stat.method === "keywords" && Array.isArray(p.items) && p.items.length) parts.push(`指定 ${p.items.length} 词`);
  else if (stat.method === "keywords" && p.direction && p.direction !== "positive") parts.push(DIRECTIONS.find((d) => d.value === p.direction)?.label ?? String(p.direction));
  if (stat.method === "translations") {
    if (t.target_language) parts.push(`译文 ${t.target_language}`);
    if (t.hit_sentences != null) parts.push(<>命中句 {n(t.hit_sentences)}</>);
    if (t.aligned_sentences != null) parts.push(<>有对齐 {n(t.aligned_sentences)}</>);
    if (t.unaligned) parts.push(<>无对齐 {n(t.unaligned)}</>);
  }
  if (stat.method === "ngrams" && typeof p.contains === "string" && p.contains) parts.push(`含“${p.contains}”`);
  if (p.exclude_punct === true) parts.push(<>已排除标点和数字{t.excluded_tokens != null && <> {n(t.excluded_tokens)} 词</>}</>);
  // Data version in words (the index hash means nothing to users): computed on an older index, or when the index was built.
  if (corpus && corpus.index_version != null && String(corpus.index_version) !== String(stat.index_version)) parts.push("基于旧版索引");
  else if (corpus?.meta?.indexed_at) parts.push(`索引更新 ${fmtRelative(corpus.meta.indexed_at)}`);
  parts.push(fmtShortTime(stat.created_at));
  parts.push(
    <>
      <span className="num">
        {fmt(stat.rows.length)}
        {stat.row_count > stat.rows.length ? ` / ${fmt(stat.row_count)}` : ""}
      </span>{" "}
      项
    </>,
  );
  const meta = (
    <span className="res-meta">
      {parts.map((x, i) => (
        <span key={i}>
          {i > 0 && "· "}
          {x}
        </span>
      ))}
    </span>
  );

  const head = (
    <div className="card-head">
      <h2>{stat.method === "ngrams" ? `${(p as { n?: number }).n ?? ""}-gram` : methodLabels[stat.method]}</h2>
      {meta}
      <div className="grow" />
      <span className="head-btns">
        <button className="btn xs" type="button" onClick={() => setAppendix(true)}>
          方法说明
        </button>
        <Tip title={exportTip("导出 CSV")}>
          <button className="btn xs" type="button" disabled={exporter.busy} onClick={() => runExport("csv")}>
            CSV
          </button>
        </Tip>
        <Tip title={exportTip("导出 XLSX")}>
          <button className="btn xs" type="button" disabled={exporter.busy} onClick={() => runExport("xlsx")}>
            XLSX
          </button>
        </Tip>
      </span>
      {appendix && <MethodAppendix projectId={projectId} statIds={[stat.id]} onClose={() => setAppendix(false)} />}
    </div>
  );
  const table = (
    <div className="card" key="table">
      {head}
      {stat.rows.length === 0 ? (
        <Empty icon="barchart" text={`当前参数下无结果${(p as { min_freq?: number }).min_freq ? `（最低频次 ${(p as { min_freq?: number }).min_freq}）` : ""}`} />
      ) : (
        <div className="stat-scroll">
          <StatTable stat={stat} projectId={projectId} highlight={measure && measureKey(measure)} selected={picked} cellBar={stat.method === "ngrams" ? "freq" : undefined} />
        </div>
      )}
    </div>
  );
  if (isP10(stat.method)) return <P10Result stat={stat} projectId={projectId} head={head} table={table} chartRef={chartRef} />;
  if (stat.method === "ngrams" || stat.rows.length === 0) return table;

  const chartTitle =
    stat.method === "frequency"
      ? `前 10 · ${stat.columns.some((c) => c.key === "per_million") ? "每百万词" : "频次"}`
      : stat.method === "collocations"
        ? "搭配强度"
        : stat.method === "keywords"
          ? "Log Ratio × LL"
          : stat.method === "breakdown"
            ? "前 10 · 命中数"
            : stat.method === "translations"
              ? `前 10 · ${MEASURE_LABELS[measure ?? "dice"] ?? measure}`
              : distTitle(stat);
  const chart = (
    <div className="card card-pad col gap-16 chart-card" key="chart">
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
      {stat.method === "collocations" && view === "network" && measure && (
        <div className="small muted" style={{ textAlign: "center" }}>
          距离 / 线宽 = {MEASURE_LABELS[measure] ?? measure}
        </div>
      )}
    </div>
  );
  return <div className={`res ${stat.method === "distribution" ? "dist" : ""}`}>{stat.method === "distribution" ? [chart, table] : [table, chart]}</div>;
}

const TEST_LABELS: Record<string, string> = { mann_whitney: "Mann-Whitney U", spearman: "Spearman" };
const VOCAB_BY: Record<string, string> = { corpus: "整体", document: "每篇" };

/** Result header facts of the P10 methods (parameters that change how to read the numbers). */
function p10Meta(stat: StatResult): React.ReactNode[] {
  const p = stat.params as Body;
  const t = stat.totals;
  const out: React.ReactNode[] = [];
  if (stat.method === "text_metrics") {
    if (t.documents != null) out.push(`${fmt(t.documents)} 篇`);
    if (p.sttr_window) out.push(`STTR 窗口 ${fmt(Number(p.sttr_window))} 词`);
    if (p.group_by) out.push(`按 ${p.group_by}`);
  }
  if (stat.method === "vocab_profile" && typeof p.by === "string") out.push(`按${VOCAB_BY[p.by] ?? ` ${p.by}`}`);
  if (stat.method === "compare") {
    if (Array.isArray(p.items)) out.push(`${p.items.length} 项`);
    if (p.by) out.push(`按 ${p.by}`);
    if (typeof p.test === "string" && TEST_LABELS[p.test]) out.push(TEST_LABELS[p.test]);
  }
  if (stat.method === "word_sketch" && p.lemma) out.push(`词元 ${p.lemma}${p.pos ? `/${p.pos}` : ""}`);
  if (stat.method === "sketch_diff" && p.lemma_a) out.push(`${p.lemma_a} 对 ${p.lemma_b}${p.pos ? ` · ${p.pos}` : ""}`);
  if ((stat.method === "word_sketch" || stat.method === "sketch_diff") && p.min_freq) out.push(`最低频次 ${p.min_freq}`);
  return out;
}

function breakdownByLabel(by: string): string {
  if (by.startsWith("meta:")) return ` ${by.slice(5)}`;
  return BREAKDOWN_BY.find((b) => b.value === by)?.label ?? by;
}

function partsLabel(parts: string): string {
  if (parts === "segments") return "等分 10 段";
  if (parts.startsWith("field:")) return `按 ${parts.slice(6)}`;
  return "文档";
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
              <Icon name={methodIcon(s.method)} size={12} />
              {methodLabels[s.method]}
            </span>
            <div className="grow col" style={{ gap: 2 }}>
              <span className="li-title ellipsis">{summary(s)}</span>
              <span className="small muted num">
                {s.scope.name} · {fmt(s.row_count)} 项 · {fmtShortTime(s.created_at)}
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
  if (s.method === "ngrams") return `${p.n ?? ""}-gram · ${p.unit ?? ""}${p.contains ? ` · 含 ${p.contains}` : ""}`;
  if (s.method === "keywords") return `${p.measure ?? ""} · ${p.unit ?? ""}${Array.isArray(p.items) && p.items.length ? ` · 指定 ${p.items.length} 词` : ""}`;
  if (s.method === "breakdown") return `${p.query ?? ""} · 按${breakdownByLabel(String(p.by ?? ""))}`;
  if (s.method === "translations") return `${p.query ?? ""} · ${p.unit ?? ""} · ${p.measure ?? ""}`;
  if (s.method === "text_metrics") return p.group_by ? `按 ${p.group_by}` : `STTR 窗口 ${p.sttr_window ?? ""}`;
  if (s.method === "vocab_profile") return `按${VOCAB_BY[String(p.by)] ?? ` ${p.by ?? ""}`}`;
  if (s.method === "compare") return (Array.isArray(p.items) ? (p.items as Body[]).map((i) => String(i.label ?? "")).join(" / ") : "") + (p.by ? ` · 按 ${p.by}` : "");
  if (s.method === "word_sketch") return `${p.lemma ?? ""}${p.pos ? `/${p.pos}` : ""}`;
  if (s.method === "sketch_diff") return `${p.lemma_a ?? ""} 对 ${p.lemma_b ?? ""}`;
  return `${p.unit ?? ""}${p.pos ? ` · ${p.pos}` : ""}`;
}

/** Why the chart export buttons are off; null when a chart is shown. */
function chartOffReason(stat: StatResult | undefined): string | null {
  if (!stat) return "先计算出结果";
  if (stat.method === "ngrams") return "n-gram 结果没有图表";
  if (stat.method === "word_sketch" || stat.method === "sketch_diff") return "按栏显示，没有图表";
  if (stat.rows.length === 0) return "没有结果，无图表";
  return null;
}

export default function Stats() {
  const projectId = useProjectId();
  const shell = useShell();
  const { message } = App.useApp();
  const allLayers = useLayers(projectId);
  const alignLayers = (allLayers.data ?? []).filter((l) => l.kind === "alignment" && l.status === "ready");
  const [tab, setTab] = useState<StatMethod>("frequency");
  const [runs, setRuns] = useState<Partial<Record<StatMethod, { body: Body; n: number }>>>({});
  const [opened, setOpened] = useState<Partial<Record<StatMethod, string>>>({});
  const corpora = useCorpora(projectId);
  const subs = useSubcorpora(projectId);
  // 译法 only on a parallel corpus: the tab is off while the shared range is a known non-parallel one.
  const scopeCorpus = describeScope(shell.scope, corpora.data?.items ?? [], subs.data?.items ?? []).corpus;
  const noParallel = !!scopeCorpus && !scopeCorpus.parallel;
  const disabledTab = (m: StatMethod) => m === "translations" && noParallel && tab !== "translations";
  const [reference, setReference] = useState<Scope | null>(null);
  const [savedOpen, setSavedOpen] = useState(false);
  const [tidyOpen, setTidyOpen] = useState(false);
  const chartRef = useRef<EChartHandle>(null);
  const [params] = useSearchParams();
  const linked = useStatResult(params.get("stat"));

  /** Show a stored result: its tab, its parameters, and its range as the shared scope. */
  const openResult = (s: StatResult) => {
    setTab(s.method);
    setOpened((o) => ({ ...o, [s.method]: s.id }));
    const sc = resultScope(s);
    if (sc) shell.setScope(sc);
    if (s.method === "keywords") setReference(toScope((s.params as Body).reference) ?? null);
  };
  useEffect(() => {
    if (linked.data) openResult(linked.data);
  }, [linked.data]); // eslint-disable-line react-hooks/exhaustive-deps

  // The result shows on this page: no completion toast while it is open (the tray still lists the job).
  const live = useStatJob(tab, runs[tab]?.body ?? null, projectId, runs[tab]?.n ?? 0, { quiet: "mounted" });
  const savedId = opened[tab];
  const saved = useStatResult(savedId);
  const stat = savedId ? saved.data : live.stat;
  const running = !savedId && live.running;
  const error = savedId ? saved.error : (live.error ?? (params.get("stat") && !linked.data ? linked.error : null));

  const disabledRef = useRef(disabledTab);
  disabledRef.current = disabledTab;
  // 1–9 switch to the first nine methods.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && e.target.closest("input, textarea, select, .ant-select")) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const n = Number(e.key);
      if (n >= 1 && n <= Math.min(9, METHODS.length) && !disabledRef.current(METHODS[n - 1])) setTab(METHODS[n - 1]);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  async function exportChart(kind: "svg" | "png") {
    const h = chartRef.current;
    if (!h || !stat) return;
    const name = `${methodLabels[stat.method]}-${stat.scope.name}-${stat.id.slice(0, 8)}.${kind}`;
    try {
      if (kind === "svg") {
        const svg = h.svg();
        if (svg) downloadText(svg, "image/svg+xml", name);
      } else {
        const url = await h.png();
        if (url) download(url, name);
      }
    } catch (e) {
      message.error(`图表导出失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }

  const off = running ? "计算中" : chartOffReason(stat);
  const chartButton = (kind: "svg" | "png") => (
    <Tip title={off ?? `导出图表 ${kind.toUpperCase()}（浅色、白底）`}>
      <span className="tip-wrap">
        <button className="btn s" type="button" disabled={!!off} onClick={() => exportChart(kind)}>
          <Icon name="download" size={14} />
          {kind.toUpperCase()}
        </button>
      </span>
    </Tip>
  );
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
            <button className="btn s" type="button" onClick={() => setTidyOpen(true)}>
              <Icon name="filespreadsheet" size={14} />
              <span className="lbl">导出整洁数据</span>
            </button>
            {chartButton("svg")}
            {chartButton("png")}
          </>
        }
      />
      <div className="content">
        <Tabs
          activeKey={tab}
          onChange={(k) => setTab(k as StatMethod)}
          items={METHODS.map((m) => ({
            key: m,
            disabled: disabledTab(m),
            label: disabledTab(m) ? (
              <Tip title="仅平行语料">
                <span>{methodLabels[m]}</span>
              </Tip>
            ) : (
              methodLabels[m]
            ),
            icon: <Icon name={methodIcon(m)} size={14} />,
          }))}
          className="stat-tabs"
        />
        <div className="col gap-20 panel-in" key={tab}>
          {isP10(tab) ? (
            <P10MethodForm
              method={tab}
              projectId={projectId}
              scope={shell.scope}
              onScope={shell.setScope}
              initial={savedId ? saved.data : undefined}
              running={running}
              onRun={(body) => {
                setOpened((o) => ({ ...o, [tab]: undefined }));
                setRuns((r) => ({ ...r, [tab]: { body, n: (r[tab]?.n ?? 0) + 1 } }));
              }}
            />
          ) : (
            <MethodForm
              method={tab}
              projectId={projectId}
              scope={shell.scope}
              onScope={shell.setScope}
              reference={reference}
              onReference={setReference}
              initial={savedId ? saved.data : undefined}
              running={running}
              onRun={(body) => {
                setOpened((o) => ({ ...o, [tab]: undefined }));
                setRuns((r) => ({ ...r, [tab]: { body, n: (r[tab]?.n ?? 0) + 1 } }));
              }}
            />
          )}
          {error ? (
            <ErrorAlert error={error}>
              {errorCode(error) === "NO_DEPENDENCIES" && (
                <Link className="btn xs" to={`/p/${projectId}/annotate?kind=dep`}>
                  去标注页建依存层
                </Link>
              )}
            </ErrorAlert>
          ) : null}
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
      <TidyExportDialog open={tidyOpen} onClose={() => setTidyOpen(false)} projectId={projectId} scope={shell.scope} />
      <SavedResults
        open={savedOpen}
        onClose={() => setSavedOpen(false)}
        projectId={projectId}
        onOpen={(s) => {
          openResult(s);
          setSavedOpen(false);
        }}
      />
    </>
  );
}
