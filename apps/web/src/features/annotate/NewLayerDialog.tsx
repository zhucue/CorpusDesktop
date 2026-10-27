import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Form, Input, Modal, Select } from "antd";
import { useEffect } from "react";
import { MAX_PAGE_SIZE, api, type Doc, type Layer, type LayerKind, type Page } from "../../api";
import { ErrorAlert } from "../../components/common";
import { useCorpora, useJobCreated } from "../../lib/data";
import { useLabelSets } from "./data";

interface Values {
  corpus_id: string;
  kind: LayerKind;
  name?: string;
  label_set_id: string;
  document_ids?: string[];
}

export const kindLabels: Record<LayerKind, string> = { pos: "词性", dep: "依存" };

/** Built-in label set for a new layer: jieba for Chinese POS, UPOS otherwise; UD relations for dependencies. */
export function defaultLabelSetName(kind: LayerKind, language: string | undefined): string {
  if (kind === "dep") return "ud-deprel";
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
  const jobCreated = useJobCreated();
  const corpora = useCorpora(projectId);
  const labelSets = useLabelSets(projectId);
  const corpusId = Form.useWatch("corpus_id", form);
  const kind = Form.useWatch("kind", form) ?? "pos";
  const usable = (corpora.data?.items ?? []).filter((c) => c.status === "ready" || c.status === "stale");
  const corpus = usable.find((c) => c.id === corpusId);

  const docs = useQuery({
    queryKey: ["documents", corpusId, "", 1, "all"],
    queryFn: () => api.get<Page<Doc>>(`/corpora/${corpusId}/documents`, { page: 1, page_size: MAX_PAGE_SIZE }),
    enabled: open && !!corpusId,
  });

  const sets = (labelSets.data ?? []).filter((s) => s.kind === kind);
  const builtin = sets.filter((s) => s.project_id == null);
  const own = sets.filter((s) => s.project_id != null);

  // Defaults follow the corpus language and the layer kind.
  useEffect(() => {
    if (!open) return;
    const want = defaultLabelSetName(kind, corpus?.language);
    const pick = sets.find((s) => s.project_id == null && s.name === want) ?? sets[0];
    form.setFieldValue("label_set_id", pick?.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, kind, corpus?.id, labelSets.data]);

  useEffect(() => {
    if (open && !form.getFieldValue("corpus_id")) {
      const first = usable.find((c) => c.id === initialCorpus) ?? usable[0];
      if (first) form.setFieldValue("corpus_id", first.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, corpora.data]);

  useEffect(() => {
    form.setFieldValue("document_ids", []);
  }, [corpusId, form]);

  const create = useMutation({
    mutationFn: (v: Values) =>
      api.post<Layer>(`/projects/${projectId}/layers`, {
        corpus_id: v.corpus_id,
        kind: v.kind,
        name: v.name?.trim() || `${corpus?.name ?? ""} ${kindLabels[v.kind]}`.trim(),
        label_set_id: v.label_set_id,
        ...(v.document_ids?.length ? { document_ids: v.document_ids } : {}),
      }),
    onSuccess: (layer) => {
      jobCreated(projectId);
      qc.invalidateQueries({ queryKey: ["layers", projectId] });
      form.resetFields();
      onCreated(layer);
    },
  });

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
      width={520}
    >
      <Form form={form} layout="vertical" requiredMark={false} initialValues={{ kind: "pos" }} onFinish={(v) => create.mutate(v)}>
        <Form.Item name="corpus_id" label="语料库" rules={[{ required: true, message: "选择语料库" }]}>
          <Select
            placeholder={usable.length ? "选择语料库" : "没有可用语料库"}
            options={usable.map((c) => ({ value: c.id, label: `${c.name} · ${c.language}` }))}
            loading={corpora.isPending}
          />
        </Form.Item>
        <Form.Item name="kind" hidden>
          <Input />
        </Form.Item>
        <Form.Item label="类型">
          <div className="seg-mini" role="tablist" aria-label="类型">
            {(["pos", "dep"] as LayerKind[]).map((k) => (
              <button key={k} type="button" role="tab" aria-selected={kind === k} onClick={() => form.setFieldValue("kind", k)}>
                {kindLabels[k]}
              </button>
            ))}
          </div>
        </Form.Item>
        <Form.Item name="name" label="名称">
          <Input maxLength={100} placeholder={`${corpus?.name ?? ""} ${kindLabels[kind as LayerKind]}`.trim()} />
        </Form.Item>
        <Form.Item name="label_set_id" label="标签集" rules={[{ required: true, message: "选择标签集" }]}>
          <Select
            loading={labelSets.isPending}
            options={[
              ...(builtin.length ? [{ label: "内置", options: builtin.map((s) => ({ value: s.id, label: `${s.name} · ${s.labels.length} 个` })) }] : []),
              ...(own.length ? [{ label: "项目", options: own.map((s) => ({ value: s.id, label: `${s.name} · ${s.labels.length} 个` })) }] : []),
            ]}
          />
        </Form.Item>
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
            新建并预标
          </button>
        </div>
      </Form>
    </Modal>
  );
}
