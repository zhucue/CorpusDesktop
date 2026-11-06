import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Checkbox, Form, Input, Modal, Select } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, errorText, type Doc, type LabelSet, type Layer, type LayerKind, type Page } from "../../api";
import { ErrorAlert } from "../../components/common";
import { Icon } from "../../components/Icon";
import { layerIcon } from "../../components/iconSets";
import { useCorpora, useJobCreated, useSubcorpora } from "../../lib/data";
import { fmt } from "../../lib/format";
import { useKbDocuments } from "../knowledge/data";
import { SendNotice, useModelHost } from "../knowledge/SendNotice";
import { useLabelSets, useLayers } from "./data";
import { useMembers } from "./spanData";

interface Values {
  corpus_id: string;
  kind: LayerKind;
  name?: string;
  label_set_id?: string;
  scope?: "all" | "subcorpus" | "documents";
  subcorpus_id?: string;
  document_ids?: string[];
  base_layer_id?: string;
  tgt_corpus_id?: string;
  level?: "sentence" | "word";
  guideline_document_id?: string;
  mode?: "single" | "multi";
  annotators?: string[];
  preannotate?: boolean;
}

export const kindLabels: Record<LayerKind, string> = { pos: "词性", dep: "依存", span: "片段", relation: "关系", alignment: "对齐" };
const KINDS: LayerKind[] = ["pos", "dep", "span", "relation", "alignment"];

/** Built-in label set templates offered for span / relation layers (contracts/p5.md §二). */
export const TEMPLATES: { name: string; label: string; kind: "span" | "relation" }[] = [
  { name: "learner-errors", label: "学习者偏误", kind: "span" },
  { name: "translation-strategies", label: "翻译策略", kind: "span" },
  { name: "error-correction", label: "偏误更正", kind: "relation" },
];

/** Built-in label set for a new layer: jieba for Chinese POS, UPOS otherwise; UD relations for dependencies; first template otherwise. */
export function defaultLabelSetName(kind: LayerKind, language: string | undefined): string {
  if (kind === "dep") return "ud-deprel";
  if (kind === "span") return "learner-errors";
  if (kind === "relation") return "error-correction";
  return language?.toLowerCase().startsWith("zh") ? "jieba" : "upos";
}

/** POST /projects/{id}/layers/estimate: what pre-annotation of the chosen scope would send to the chat model. */
interface Estimate {
  documents: number;
  sentences: number;
  units: number;
  batch_size: number;
  model_calls: number;
  basis: string;
}

const DOC_PAGE = 50;

/** Documents of a corpus searched by title on the server, 50 at a time (scroll for more). */
function DocumentPicker({ corpusId, value, onChange }: { corpusId?: string; value?: string[]; onChange?: (v: string[]) => void }) {
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQ(input.trim()), 300);
    return () => clearTimeout(t);
  }, [input]);
  const docs = useInfiniteQuery({
    queryKey: ["layer-doc-picker", corpusId, q],
    queryFn: ({ pageParam }) => api.get<Page<Doc>>(`/corpora/${corpusId}/documents`, { page: pageParam, page_size: DOC_PAGE, ...(q ? { q } : {}) }),
    initialPageParam: 1,
    getNextPageParam: (last, all) => (all.length * DOC_PAGE < last.total ? all.length + 1 : undefined),
    enabled: !!corpusId,
  });
  // titles of chosen documents stay known when a later search no longer lists them
  const titles = useRef(new Map<string, string>());
  const loaded = useMemo(() => docs.data?.pages.flatMap((p) => p.items) ?? [], [docs.data]);
  for (const d of loaded) titles.current.set(d.id, d.title);
  const total = docs.data?.pages[0]?.total;
  const options = [
    ...(value ?? []).filter((id) => !loaded.some((d) => d.id === id)).map((id) => ({ value: id, label: titles.current.get(id) ?? id })),
    ...loaded.map((d) => ({ value: d.id, label: d.title })),
  ];
  return (
    <Select
      mode="multiple"
      allowClear
      showSearch
      filterOption={false}
      searchValue={input}
      onSearch={setInput}
      placeholder="按标题搜索文档"
      loading={docs.isFetching}
      value={value}
      onChange={(v: string[]) => onChange?.(v)}
      options={options}
      maxTagCount="responsive"
      notFoundContent={docs.isFetching ? "加载中" : "没有匹配的文档"}
      onPopupScroll={(e) => {
        const el = e.currentTarget;
        if (el.scrollTop + el.clientHeight >= el.scrollHeight - 24 && docs.hasNextPage && !docs.isFetchingNextPage) void docs.fetchNextPage();
      }}
      popupRender={(menu) => (
        <>
          {menu}
          {total != null && (
            <div className="small muted" style={{ padding: "4px 12px" }}>
              已列出 {fmt(loaded.length)} / {fmt(total)} 篇
            </div>
          )}
        </>
      )}
    />
  );
}

export default function NewLayerDialog({
  open,
  projectId,
  initialCorpus,
  onClose,
  onCreated,
}: {
  open: boolean;
  projectId: string;
  initialCorpus?: string;
  onClose: () => void;
  onCreated: (layer: Layer) => void;
}) {
  const [form] = Form.useForm<Values>();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const jobCreated = useJobCreated();
  const corpora = useCorpora(projectId);
  const labelSets = useLabelSets(projectId);
  const layers = useLayers(projectId);
  const kb = useKbDocuments(open ? projectId : undefined);
  const members = useMembers(open ? projectId : undefined);
  const subcorpora = useSubcorpora(open ? projectId : undefined);
  const corpusId = Form.useWatch("corpus_id", form);
  const kind: LayerKind = Form.useWatch("kind", form) ?? "pos";
  const mode = Form.useWatch("mode", form) ?? "single";
  const tgtId = Form.useWatch("tgt_corpus_id", form);
  const level = Form.useWatch("level", form) ?? "sentence";
  const preannotateMulti = !!Form.useWatch("preannotate", form);
  const labelSetId = Form.useWatch("label_set_id", form);
  const scope = Form.useWatch("scope", form) ?? "all";
  const subcorpusId = Form.useWatch("subcorpus_id", form);
  const documentIds = Form.useWatch("document_ids", form);
  const baseLayerId = Form.useWatch("base_layer_id", form);
  const usable = (corpora.data?.items ?? []).filter((c) => c.status === "ready" || c.status === "stale");
  const corpus = usable.find((c) => c.id === corpusId);
  const tgt = usable.find((c) => c.id === tgtId);
  const tokenKind = kind === "pos" || kind === "dep";
  const usesLabels = kind !== "alignment";
  // the chat model preannotates span / relation layers and word alignments (sentence pairs use the local vector model)
  const usesModel = (kind === "span" || kind === "relation" || (kind === "alignment" && level === "word")) && (mode !== "multi" || preannotateMulti);
  const modelHost = useModelHost(open);

  // relation layers cover the documents of their span layer's corpus
  const scopeCorpusId = kind === "relation" ? (layers.data ?? []).find((l) => l.id === baseLayerId)?.corpus_id : corpusId;
  const subs = (subcorpora.data?.items ?? []).filter((x) => x.corpus_id === scopeCorpusId);
  const scopeBody = () =>
    scope === "subcorpus" && subcorpusId ? { subcorpus_id: subcorpusId } : scope === "documents" && documentIds?.length ? { document_ids: documentIds } : {};

  // Model calls of the pre-annotation for the chosen scope (sentences / batch size), before anything is sent.
  const estimate = useQuery({
    queryKey: ["layer-estimate", projectId, corpusId, kind, level, tgtId, baseLayerId, scope, subcorpusId, documentIds],
    queryFn: () =>
      api.post<Estimate>(`/projects/${projectId}/layers/estimate`, {
        corpus_id: corpusId,
        kind,
        ...(kind === "alignment" ? { level, tgt_corpus_id: tgtId } : {}),
        ...(kind === "relation" ? { base_layer_id: baseLayerId } : {}),
        ...scopeBody(),
      }),
    enabled: open && usesModel && !!corpusId && (kind !== "relation" || !!baseLayerId) && (scope !== "subcorpus" || !!subcorpusId),
    staleTime: 60 * 1000,
  });

  const sets = (labelSets.data ?? []).filter((s) => s.kind === kind);
  const builtin = sets.filter((s) => s.project_id == null);
  const own = sets.filter((s) => s.project_id != null);
  const guidelines = (kb.data ?? []).filter((d) => d.kind === "guideline");
  const baseLayers = (layers.data ?? []).filter((l) => l.kind === "span" && l.corpus_id === corpusId);
  const templates = TEMPLATES.filter((t) => t.kind === kind);
  const chosen = sets.find((s) => s.id === labelSetId);

  // POS layers default to the tag set the corpus already carries (UPOS for UD corpora, jieba for jieba-tagged ones).
  const defaults = useQuery({
    queryKey: ["layer-defaults", projectId, corpusId],
    queryFn: () => api.get<{ pos_label_set: string }>(`/projects/${projectId}/corpora/${corpusId}/layer-defaults`),
    enabled: open && !!corpusId && kind === "pos",
    staleTime: 5 * 60 * 1000,
  });

  // Defaults follow the corpus (its tags, else its language) and the layer kind.
  useEffect(() => {
    if (!open || !usesLabels) return;
    const want = (kind === "pos" && defaults.data?.pos_label_set) || defaultLabelSetName(kind, corpus?.language);
    const pick = sets.find((s) => s.project_id == null && s.name === want) ?? sets[0];
    form.setFieldValue("label_set_id", pick?.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, kind, corpus?.id, labelSets.data, defaults.data]);

  // A guideline linked to the chosen label set (P4 规范 → 关联标签集) is preselected.
  useEffect(() => {
    if (!open || tokenKind || form.getFieldValue("guideline_document_id")) return;
    const g = guidelines.find((d) => d.meta?.label_set_id && d.meta.label_set_id === labelSetId);
    if (g) form.setFieldValue("guideline_document_id", g.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, labelSetId, kb.data, tokenKind]);

  useEffect(() => {
    if (open && !form.getFieldValue("corpus_id")) {
      const first = usable.find((c) => c.id === initialCorpus) ?? usable[0];
      if (first) form.setFieldValue("corpus_id", first.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, corpora.data]);

  useEffect(() => {
    form.setFieldValue("document_ids", []);
    form.setFieldValue("subcorpus_id", undefined);
    form.setFieldValue("base_layer_id", undefined);
  }, [corpusId, form]);

  useEffect(() => {
    if (kind === "relation" && !form.getFieldValue("base_layer_id") && baseLayers[0]) form.setFieldValue("base_layer_id", baseLayers[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, corpusId, layers.data]);

  const copy = useMutation({
    mutationFn: (s: LabelSet) =>
      api.post<LabelSet>(`/projects/${projectId}/label-sets`, { name: `${s.name}（项目）`, kind: s.kind, language: s.language ?? undefined, labels: s.labels, copy_from: s.id }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["label-sets", projectId] });
      form.setFieldValue("label_set_id", s.id);
      message.success(`已复制为项目标签集「${s.name}」`);
    },
    onError: (e) => message.error(errorText(e)),
  });

  const defaultName = () =>
    kind === "alignment"
      ? `${corpus?.name ?? ""}${tgt && tgt.id !== corpus?.id ? ` ↔ ${tgt.name}` : ""} ${level === "word" ? "词级" : "句级"}对齐`.trim()
      :`${corpus?.name ?? ""} ${chosen && !tokenKind ? chosen.name : kindLabels[kind]}`.trim();

  const create = useMutation({
    mutationFn: (v: Values) => {
      const body: Record<string, unknown> = {
        corpus_id: v.corpus_id,
        kind: v.kind,
        name: v.name?.trim() || defaultName(),
        ...(v.scope === "subcorpus" && v.subcorpus_id ? { subcorpus_id: v.subcorpus_id } : {}),
        ...(v.scope === "documents" && v.document_ids?.length ? { document_ids: v.document_ids } : {}),
      };
      if (v.kind !== "alignment") body.label_set_id = v.label_set_id;
      if (!tokenKind) {
        body.mode = v.mode ?? "single";
        if (v.mode === "multi") {
          body.annotators = v.annotators ?? [];
          // multi layers start without suggestions unless asked: shared suggestions bias independent annotation
          body.preannotate = !!v.preannotate;
        }
        // only span / relation layers take a guideline (api: 422 INVALID_GUIDELINE otherwise)
        if (v.guideline_document_id && v.kind !== "alignment") body.guideline_document_id = v.guideline_document_id;
      }
      if (v.kind === "relation") body.base_layer_id = v.base_layer_id;
      if (v.kind === "alignment") Object.assign(body, { src_corpus_id: v.corpus_id, tgt_corpus_id: v.tgt_corpus_id, level: v.level ?? "sentence" });
      return api.post<Layer>(`/projects/${projectId}/layers`, body);
    },
    onSuccess: (layer) => {
      jobCreated(projectId);
      qc.invalidateQueries({ queryKey: ["layers", projectId] });
      form.resetFields();
      onCreated(layer);
    },
  });

  const corpusOptions = usable.map((c) => ({ value: c.id, label: `${c.name} · ${c.language}` }));

  return (
    <Modal
      title="新建标注层"
      open={open}
      onCancel={() => {
        create.reset();
        onClose();
      }}
      footer={null}
      destroyOnHidden
      focusTriggerAfterClose={false}
      width={560}
    >
      <Form form={form} layout="vertical" requiredMark={false} initialValues={{ kind: "pos", mode: "single", level: "sentence", preannotate: false, scope: "all" }} onFinish={(v) => create.mutate(v)}>
        <Form.Item name="kind" hidden>
          <Input />
        </Form.Item>
        <Form.Item label="类型">
          <div className="seg-mini" role="tablist" aria-label="类型">
            {KINDS.map((k) => (
              <button key={k} type="button" role="tab" aria-selected={kind === k} onClick={() => form.setFieldValue("kind", k)}>
                <Icon name={layerIcon[k]} size={14} />
                {kindLabels[k]}
              </button>
            ))}
          </div>
        </Form.Item>
        <Form.Item name="corpus_id" label={kind === "alignment" ? "源语料库" : "语料库"} rules={[{ required: true, message: "选择语料库" }]}>
          <Select placeholder={usable.length ? "选择语料库" : "没有可用语料库"} options={corpusOptions} loading={corpora.isPending} />
        </Form.Item>
        {kind === "alignment" && (
          <div className="row" style={{ gap: 12, alignItems: "flex-start" }}>
            <Form.Item name="tgt_corpus_id" label="目标语料库" style={{ flex: 1 }} rules={[{ required: true, message: "选择目标语料库" }]}>
              <Select placeholder="选择语料库" options={corpusOptions} />
            </Form.Item>
            <Form.Item name="level" label="对齐级别" style={{ width: 140 }}>
              <Select
                options={[
                  { value: "sentence", label: "句级" },
                  { value: "word", label: "词级" },
                ]}
              />
            </Form.Item>
          </div>
        )}
        {kind === "relation" && (
          <Form.Item name="base_layer_id" label="片段层" rules={[{ required: true, message: "选择片段层" }]}>
            <Select placeholder={baseLayers.length ? "选择片段层" : "该语料库还没有片段层"} options={baseLayers.map((l) => ({ value: l.id, label: l.name }))} />
          </Form.Item>
        )}
        <Form.Item name="name" label="名称">
          <Input maxLength={100} placeholder={defaultName()} />
        </Form.Item>
        {usesLabels && (
          <Form.Item label="标签集" required>
            <Form.Item name="label_set_id" noStyle rules={[{ required: true, message: "选择标签集" }]}>
              <Select
                loading={labelSets.isPending}
                aria-label="标签集"
                options={[
                  ...(builtin.length ? [{ label: "内置", options: builtin.map((s) => ({ value: s.id, label: `${s.name} · ${s.labels.length} 个` })) }] : []),
                  ...(own.length ? [{ label: "项目", options: own.map((s) => ({ value: s.id, label: `${s.name} · ${s.labels.length} 个` })) }] : []),
                ]}
              />
            </Form.Item>
            {!tokenKind && (
              <div className="tpl-row">
                {templates.map((t) => {
                  const s = builtin.find((x) => x.name === t.name);
                  return (
                    <button key={t.name} className={`chip ${s && s.id === labelSetId ? "on" : ""}`} type="button" disabled={!s} onClick={() => s && form.setFieldValue("label_set_id", s.id)}>
                      {t.label}
                    </button>
                  );
                })}
                {chosen && chosen.project_id == null && (
                  <button className="btn xs ghost" type="button" disabled={copy.isPending} onClick={() => copy.mutate(chosen)}>
                    <Icon name="copy" size={14} />
                    复制为项目标签集
                  </button>
                )}
              </div>
            )}
          </Form.Item>
        )}
        {!tokenKind && kind !== "alignment" && (
          <Form.Item name="guideline_document_id" label="标注规范">
            <Select allowClear placeholder={guidelines.length ? "不关联" : "知识库没有规范"} loading={kb.isPending} options={guidelines.map((d) => ({ value: d.id, label: d.title }))} />
          </Form.Item>
        )}
        {!tokenKind && (
          <div className="row" style={{ gap: 12, alignItems: "flex-start" }}>
            <Form.Item name="mode" label="标注方式" style={{ width: 140 }}>
              <Select
                options={[
                  { value: "single", label: "单人" },
                  { value: "multi", label: "多人" },
                ]}
              />
            </Form.Item>
            {mode === "multi" && (
              <Form.Item
                name="annotators"
                label="标注者"
                style={{ flex: 1 }}
                rules={[{ validator: (_, v: string[] | undefined) => ((v?.length ?? 0) >= 2 ? Promise.resolve() : Promise.reject(new Error("至少选择两名标注者"))) }]}
              >
                <Select
                  mode="multiple"
                  placeholder="选择项目成员"
                  loading={members.isPending}
                  optionFilterProp="label"
                  options={(members.data?.items ?? []).filter((m) => m.role !== "viewer").map((m) => ({ value: m.user_id, label: m.email }))}
                />
              </Form.Item>
            )}
          </div>
        )}
        {!tokenKind && mode === "multi" && (
          <Form.Item name="preannotate" valuePropName="checked" style={{ marginTop: -8 }}>
            <Checkbox>预标（每位标注者得到同一份模型建议，会影响独立标注和一致性）</Checkbox>
          </Form.Item>
        )}
        <div className="row" style={{ gap: 12, alignItems: "flex-start" }}>
          <Form.Item name="scope" label="范围" style={{ width: 140 }}>
            <Select
              options={[
                { value: "all", label: "全部文档" },
                { value: "subcorpus", label: "子库" },
                { value: "documents", label: "指定文档" },
              ]}
            />
          </Form.Item>
          {scope === "subcorpus" && (
            <Form.Item name="subcorpus_id" label="子库" style={{ flex: 1, minWidth: 0 }} rules={[{ required: true, message: "选择子库" }]}>
              <Select
                placeholder={subs.length ? "选择子库" : "该语料库没有子库"}
                loading={subcorpora.isPending}
                options={subs.map((x) => ({ value: x.id, label: `${x.name} · ${fmt(x.stats.documents)} 篇` }))}
              />
            </Form.Item>
          )}
          {scope === "documents" && (
            <Form.Item name="document_ids" label="文档" style={{ flex: 1, minWidth: 0 }} rules={[{ required: true, message: "选择文档" }]}>
              <DocumentPicker corpusId={scopeCorpusId} />
            </Form.Item>
          )}
        </div>
        {usesModel && (
          <div className="small" style={{ marginBottom: 8 }} aria-live="polite">
            {estimate.data ? (
              <>
                约 <b className="num">{fmt(estimate.data.sentences)}</b> 句，将调用模型约 <b className="num">{fmt(estimate.data.model_calls)}</b> 次（{estimate.data.basis}，每批 {estimate.data.batch_size} 句）
              </>
            ) : estimate.error ? (
              <span className="err-text">{errorText(estimate.error)}</span>
            ) : estimate.isFetching ? (
              "正在估算模型调用次数"
            ) : null}
          </div>
        )}
        {usesModel && <SendNotice what="所选句子" host={modelHost} style={{ marginBottom: 12 }} />}
        <ErrorAlert error={create.error ?? labelSets.error} style={{ marginBottom: 12 }} />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" type="button" onClick={onClose}>
            取消
          </button>
          <button className="btn p" type="submit" disabled={create.isPending}>
            {create.isPending && <span className="spin" />}
            {!tokenKind && mode === "multi" && !preannotateMulti ? "新建" : "新建并预标"}
          </button>
        </div>
      </Form>
    </Modal>
  );
}
