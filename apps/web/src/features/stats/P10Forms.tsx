import { useQuery } from "@tanstack/react-query";
import { Form, Input, InputNumber, Select } from "antd";
import { useEffect, useState } from "react";
import { api, type MetadataField, type Scope, type StatMethod, type StatResult } from "../../api";
import { IndexPendingNote } from "../../components/common";
import { ScopeSelect } from "../../components/common/ScopeSelect";
import { Icon } from "../../components/Icon";
import { canEdit, describeScope, useCorpora, useProject, useSubcorpora } from "../../lib/data";
import { useLayers } from "../annotate/data";
import { TEXT_METRICS } from "./columns";
import { type Body, fieldLabel, ParamsCard, POS_OPTIONS, scopeRule, toScope } from "./formParts";
import { useVocabLists, VocabListsDialog, vocabListLabel } from "./VocabLists";

/** Methods added in P10 (contracts/p10.md §一、§二、§四、§五); their forms and results live in P10Forms / P10Results. */
export const P10_METHODS: StatMethod[] = ["text_metrics", "vocab_profile", "compare", "word_sketch", "sketch_diff"];
export const isP10 = (m: StatMethod) => P10_METHODS.includes(m);

const ALL_METRICS = TEXT_METRICS.map((m) => m.key);
const SKETCH_TOP = [10, 25, 50].map((n) => ({ value: n, label: `每栏 ${n}` }));
const TESTS = [
  { value: "none", label: "无" },
  { value: "mann_whitney", label: "Mann-Whitney U（两项）" },
  { value: "spearman", label: "Spearman（数值字段）" },
];
const MAX_ITEMS = 10;
const itemName = (i: number) => String.fromCharCode(65 + i);

function useFields(corpusId: string | undefined) {
  return useQuery({
    queryKey: ["metadata-fields", corpusId],
    queryFn: () => api.get<MetadataField[]>(`/corpora/${corpusId}/metadata-fields`),
    enabled: !!corpusId,
  });
}

/** Form values that reproduce a stored P10 result's request. */
function p10Values(stat: StatResult): Body {
  const p = stat.params as Body;
  const scope = toScope(p.scope) ?? toScope(stat.scope);
  const dep = (p.layers as { dep?: string } | undefined)?.dep;
  let v: Body = {};
  if (stat.method === "text_metrics")
    v = { scope, metrics: Array.isArray(p.metrics) ? p.metrics.filter((m) => ALL_METRICS.includes(m)) : undefined, group_by: p.group_by, sttr_window: p.sttr_window };
  if (stat.method === "vocab_profile") v = { scope, list_id: p.list_id, by: p.by };
  if (stat.method === "compare")
    v = {
      items: Array.isArray(p.items) ? (p.items as Body[]).map((it) => ({ label: it.label, scope: toScope(it.scope), query: it.query })) : undefined,
      by: p.by,
      test: p.test,
    };
  if (stat.method === "word_sketch") v = { scope, lemma: p.lemma, pos: p.pos, dep, min_freq: p.min_freq, top: p.top };
  if (stat.method === "sketch_diff") v = { scope, lemma_a: p.lemma_a, lemma_b: p.lemma_b, pos: p.pos, dep, min_freq: p.min_freq, top: p.top };
  return Object.fromEntries(Object.entries(v).filter(([, x]) => x !== undefined && x !== null));
}

/** Parameter form for the P10 methods; builds the POST /stats/{method} body (contracts/p10.md). */
export function P10MethodForm({
  method,
  projectId,
  scope,
  onScope,
  initial,
  running,
  onRun,
}: {
  method: StatMethod;
  projectId: string;
  scope: Scope | null;
  onScope: (s: Scope) => void;
  initial?: StatResult;
  running: boolean;
  onRun: (body: Body) => void;
}) {
  const [form] = Form.useForm();
  const corpora = useCorpora(projectId);
  const subs = useSubcorpora(projectId);
  const project = useProject();
  const [vocabOpen, setVocabOpen] = useState(false);
  const isCompare = method === "compare";
  const formScope = Form.useWatch("scope", form) as Scope | undefined;
  const items = (Form.useWatch("items", form) as { label?: string; scope?: Scope; query?: string }[] | undefined) ?? [];
  // compare: the first item's corpus offers the fields
  const fieldScope = isCompare ? (items[0]?.scope ?? null) : (formScope ?? null);
  const corpus = describeScope(fieldScope, corpora.data?.items ?? [], subs.data?.items ?? []).corpus;
  const fields = useFields(method === "text_metrics" || method === "vocab_profile" || isCompare ? corpus?.id : undefined);
  const fieldOptions = (fields.data ?? []).map((f) => ({ value: f.field, label: fieldLabel(f.field) }));
  const lists = useVocabLists(projectId);
  const layers = useLayers(projectId);
  const sketch = method === "word_sketch" || method === "sketch_diff";
  const depLayers = (layers.data ?? []).filter((l) => l.kind === "dep" && l.status === "ready" && (!corpus || l.corpus_id === corpus.id));
  const chinese = !!corpus?.language?.startsWith("zh");
  const by = Form.useWatch("by", form) as string | undefined;
  const test = Form.useWatch("test", form) as string | undefined;
  const byNumeric = !!by && (fields.data ?? []).find((f) => f.field === by)?.type === "number";

  useEffect(() => {
    if (scope && !isCompare) form.setFieldValue("scope", scope);
  }, [scope, isCompare, form]);
  useEffect(() => {
    if (initial && initial.method === method) form.setFieldsValue(p10Values(initial));
  }, [initial?.id, method]); // eslint-disable-line react-hooks/exhaustive-deps
  // compare: start with two items on the shared range
  useEffect(() => {
    if (isCompare && !form.getFieldValue("items")) form.setFieldValue("items", [0, 1].map((i) => ({ label: itemName(i), scope: scope ?? undefined, query: "" })));
  }, [isCompare]); // eslint-disable-line react-hooks/exhaustive-deps
  // vocab profile: default to a list in the corpus's language, else the first
  useEffect(() => {
    if (method !== "vocab_profile" || form.getFieldValue("list_id") || !lists.data?.length) return;
    const lang = corpus?.language?.slice(0, 2);
    form.setFieldValue("list_id", (lists.data.find((l) => l.language === lang) ?? lists.data[0]).id);
  }, [method, lists.data, corpus?.language]); // eslint-disable-line react-hooks/exhaustive-deps
  // The test must fit: Mann-Whitney needs exactly two items, Spearman a numeric field.
  useEffect(() => {
    if (!isCompare) return;
    if ((test === "mann_whitney" && items.length !== 2) || (test === "spearman" && !byNumeric)) form.setFieldValue("test", "none");
  }, [isCompare, test, items.length, byNumeric]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = () => {
    const v = form.getFieldsValue(true) as Body;
    const body: Body = { project_id: projectId };
    const s = (x: unknown) => String(x ?? "").trim();
    if (method === "text_metrics") {
      const chosen = (v.metrics as string[] | undefined)?.length ? (v.metrics as string[]) : ALL_METRICS;
      // words and sentences are in every row (contracts/p10.md §一)
      Object.assign(body, { scope: v.scope, metrics: ["words", "sentences", ...chosen], group_by: v.group_by || undefined, sttr_window: v.sttr_window ?? 1000 });
    }
    if (method === "vocab_profile") Object.assign(body, { scope: v.scope, list_id: v.list_id, by: v.by ?? "corpus" });
    if (isCompare)
      Object.assign(body, {
        items: ((v.items as Body[]) ?? []).map((it) => ({ label: s(it.label), scope: it.scope, query: s(it.query) })),
        by: v.by || null,
        test: v.test ?? "none",
      });
    if (sketch) {
      const lemmas = method === "word_sketch" ? { lemma: s(v.lemma) } : { lemma_a: s(v.lemma_a), lemma_b: s(v.lemma_b) };
      Object.assign(body, { scope: v.scope, ...lemmas, pos: v.pos || undefined, min_freq: v.min_freq ?? 2, top: v.top ?? 25 });
      if (v.dep) body.layers = { dep: v.dep };
    }
    onRun(body);
  };

  const required = (msg: string) => [{ required: true, whitespace: true, message: msg }];
  const scopeField = (
    <Form.Item name="scope" label="范围" rules={scopeRule()}>
      <ScopeSelect projectId={projectId} value={form.getFieldValue("scope")} onChange={onScope} />
    </Form.Item>
  );
  const groupField = (name: string, label: string) => (
    <Form.Item name={name} label={label}>
      <Select allowClear placeholder="不分组" style={{ width: 150 }} loading={fields.isFetching} options={fieldOptions} />
    </Form.Item>
  );

  return (
    <>
      <ParamsCard form={form} onSubmit={submit} running={running}>
        {!isCompare && scopeField}
        {method === "text_metrics" && (
          <>
            <Form.Item name="metrics" label="指标" initialValue={ALL_METRICS} rules={[{ required: true, message: "至少选一个指标" }]}>
              <Select mode="multiple" options={TEXT_METRICS.map((m) => ({ value: m.key, label: m.label }))} style={{ minWidth: 220, maxWidth: 420 }} maxTagCount="responsive" />
            </Form.Item>
            {groupField("group_by", "按元数据分组")}
            <Form.Item name="sttr_window" label="STTR 窗口（词）" initialValue={1000}>
              <InputNumber min={100} max={100000} step={100} className="mono" style={{ width: 112 }} />
            </Form.Item>
          </>
        )}
        {method === "vocab_profile" && (
          <>
            <Form.Item name="list_id" label="词表" rules={[{ required: true, message: "请选择词表" }]}>
              <Select style={{ width: 220 }} loading={lists.isFetching} options={(lists.data ?? []).map((l) => ({ value: l.id, label: vocabListLabel(l) }))} />
            </Form.Item>
            <Form.Item label=" ">
              <button className="btn s" type="button" onClick={() => setVocabOpen(true)}>
                <Icon name="layers" size={14} />
                管理词表
              </button>
            </Form.Item>
            <Form.Item name="by" label="按" initialValue="corpus">
              <Select
                style={{ width: 150 }}
                loading={fields.isFetching}
                options={[
                  { value: "corpus", label: "整体" },
                  { value: "document", label: "每篇" },
                  ...(fieldOptions.length ? [{ label: "元数据字段", options: fieldOptions }] : []),
                ]}
              />
            </Form.Item>
          </>
        )}
        {isCompare && (
          <>
            <Form.List name="items">
              {(rows, { add, remove }) => (
                <div className="cmp-items">
                  {rows.map((row, i) => (
                    <div className="cmp-item" key={row.key}>
                      <Form.Item name={[row.name, "label"]} label={i === 0 ? "标签" : undefined} rules={required("请输入标签")}>
                        <Input style={{ width: 110 }} maxLength={40} aria-label={`第 ${i + 1} 项标签`} />
                      </Form.Item>
                      <Form.Item name={[row.name, "scope"]} label={i === 0 ? "范围" : undefined} rules={scopeRule()}>
                        <ScopeSelect projectId={projectId} value={items[i]?.scope} onChange={() => {}} width={200} />
                      </Form.Item>
                      <Form.Item name={[row.name, "query"]} label={i === 0 ? "查询式" : undefined} rules={required("请输入查询式")}>
                        <Input className="mono" style={{ width: 220 }} placeholder="翻译/v" aria-label={`第 ${i + 1} 项查询式`} />
                      </Form.Item>
                      <button className="btn ghost icon" type="button" aria-label={`删除第 ${i + 1} 项`} disabled={rows.length <= 2} onClick={() => remove(row.name)}>
                        <Icon name="x" size={14} />
                      </button>
                    </div>
                  ))}
                  <div>
                    <button
                      className="btn s"
                      type="button"
                      disabled={rows.length >= MAX_ITEMS}
                      onClick={() => add({ label: itemName(rows.length), scope: items[rows.length - 1]?.scope ?? scope ?? undefined, query: "" })}
                    >
                      <Icon name="plus" size={14} />
                      添加一项
                    </button>
                  </div>
                </div>
              )}
            </Form.List>
            {groupField("by", "按字段")}
            <Form.Item name="test" label="检验" initialValue="none">
              <Select
                style={{ width: 200 }}
                options={TESTS.map((t) => ({
                  ...t,
                  disabled: (t.value === "mann_whitney" && items.length !== 2) || (t.value === "spearman" && !byNumeric),
                }))}
              />
            </Form.Item>
          </>
        )}
        {method === "word_sketch" && (
          <Form.Item name="lemma" label="词元" rules={required("请输入词元")}>
            <Input className="mono" style={{ width: 150 }} placeholder="make" maxLength={200} />
          </Form.Item>
        )}
        {method === "sketch_diff" && (
          <>
            <Form.Item name="lemma_a" label="词元 A" rules={required("请输入词元 A")}>
              <Input className="mono" style={{ width: 130 }} placeholder="big" maxLength={200} />
            </Form.Item>
            <Form.Item
              name="lemma_b"
              label="词元 B"
              rules={[
                ...required("请输入词元 B"),
                { validator: (_, v) => (v && String(v).trim() === String(form.getFieldValue("lemma_a") ?? "").trim() ? Promise.reject(new Error("与词元 A 相同")) : Promise.resolve()) },
              ]}
            >
              <Input className="mono" style={{ width: 130 }} placeholder="large" maxLength={200} />
            </Form.Item>
          </>
        )}
        {sketch && (
          <>
            <Form.Item name="pos" label="词性">
              <Select allowClear placeholder="全部" options={POS_OPTIONS} style={{ width: 136 }} />
            </Form.Item>
            {chinese && (
              <Form.Item name="dep" label="依存层">
                <Select allowClear style={{ width: 180 }} placeholder="最新依存预标层" options={depLayers.map((l) => ({ value: l.id, label: l.name }))} />
              </Form.Item>
            )}
            <Form.Item name="min_freq" label="最低频次" initialValue={2}>
              <InputNumber min={1} className="mono" style={{ width: 96 }} />
            </Form.Item>
            <Form.Item name="top" label="显示" initialValue={25}>
              <Select options={SKETCH_TOP} style={{ width: 104 }} />
            </Form.Item>
          </>
        )}
      </ParamsCard>
      <IndexPendingNote corpus={corpus?.index_pending ? corpus : null} />
      {method === "vocab_profile" && <VocabListsDialog open={vocabOpen} onClose={() => setVocabOpen(false)} projectId={projectId} editable={canEdit(project.data)} />}
    </>
  );
}
