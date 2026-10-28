import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Checkbox, Form, Input, Modal, Select } from "antd";
import { useEffect } from "react";
import { MAX_PAGE_SIZE, api, errorText, type Doc, type LabelSet, type Layer, type LayerKind, type Page } from "../../api";
import { ErrorAlert } from "../../components/common";
import { Icon } from "../../components/Icon";
import { layerIcon } from "../../components/iconSets";
import { useCorpora, useJobCreated } from "../../lib/data";
import { useKbDocuments } from "../knowledge/data";
import { useLabelSets, useLayers } from "./data";
import { useMembers } from "./spanData";

interface Values {
  corpus_id: string;
  kind: LayerKind;
  name?: string;
  label_set_id?: string;
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
  const corpusId = Form.useWatch("corpus_id", form);
  const kind: LayerKind = Form.useWatch("kind", form) ?? "pos";
  const mode = Form.useWatch("mode", form) ?? "single";
  const tgtId = Form.useWatch("tgt_corpus_id", form);
  const level = Form.useWatch("level", form) ?? "sentence";
  const preannotateMulti = !!Form.useWatch("preannotate", form);
  const labelSetId = Form.useWatch("label_set_id", form);
  const usable = (corpora.data?.items ?? []).filter((c) => c.status === "ready" || c.status === "stale");
  const corpus = usable.find((c) => c.id === corpusId);
  const tgt = usable.find((c) => c.id === tgtId);
  const tokenKind = kind === "pos" || kind === "dep";
  const usesLabels = kind !== "alignment";

  const docs = useQuery({
    queryKey: ["documents", corpusId, "", 1, "all"],
    queryFn: () => api.get<Page<Doc>>(`/corpora/${corpusId}/documents`, { page: 1, page_size: MAX_PAGE_SIZE }),
    enabled: open && !!corpusId,
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
        ...(v.document_ids?.length ? { document_ids: v.document_ids } : {}),
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
      <Form form={form} layout="vertical" requiredMark={false} initialValues={{ kind: "pos", mode: "single", level: "sentence", preannotate: false }} onFinish={(v) => create.mutate(v)}>
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
        <Form.Item name="document_ids" label="文档（不选为全部）">
          <Select
            mode="multiple"
            allowClear
            placeholder="全部文档"
            loading={docs.isFetching}
            optionFilterProp="label"
            options={(docs.data?.items ?? []).map((d) => ({ value: d.id, label: d.title }))}
            maxTagCount="responsive"
          />
        </Form.Item>
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
