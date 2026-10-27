import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Spin, Table } from "antd";
import { useState } from "react";
import {
  MAX_PAGE_SIZE,
  api,
  errorText,
  type Corpus,
  type FilterValue,
  type MetadataField,
  type Page,
  type Subcorpus,
} from "../api";
import { fmt } from "../corpora";
import { useProjectId } from "../projects";

export function useSubcorpora(projectId: string) {
  return useQuery({
    queryKey: ["subcorpora", projectId],
    queryFn: () => api.get<Page<Subcorpus>>(`/projects/${projectId}/subcorpora`, { page_size: MAX_PAGE_SIZE }),
  });
}

export function filterText(filter: Record<string, FilterValue>): string {
  return Object.entries(filter)
    .map(([k, v]) => {
      if (Array.isArray(v)) return `${k} ∈ ${v.join("、")}`;
      if (v && typeof v === "object") {
        const parts = [];
        if (v.gte !== undefined) parts.push(`≥ ${v.gte}`);
        if (v.lte !== undefined) parts.push(`≤ ${v.lte}`);
        return `${k} ${parts.join(" 且 ")}`;
      }
      return `${k} = ${v}`;
    })
    .join("；");
}

export default function Subcorpora({ corpora, editable }: { corpora: Corpus[]; editable: boolean }) {
  const projectId = useProjectId();
  const list = useSubcorpora(projectId);
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [creating, setCreating] = useState(false);
  const names = new Map(corpora.map((c) => [c.id, c.name]));

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/subcorpora/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["subcorpora", projectId] }),
    onError: (e) => message.error(errorText(e)),
  });

  return (
    <Card
      title="子库"
      extra={
        editable && (
          <Button onClick={() => setCreating(true)} disabled={corpora.length === 0}>
            新建子库
          </Button>
        )
      }
    >
      {list.error && <Alert type="error" showIcon message={errorText(list.error)} />}
      <Table<Subcorpus>
        rowKey="id"
        size="small"
        loading={list.isPending}
        dataSource={list.data?.items}
        pagination={false}
        locale={{ emptyText: "暂无子库" }}
        columns={[
          { title: "名称", dataIndex: "name" },
          { title: "语料库", render: (_, s) => names.get(s.corpus_id) ?? s.corpus_id },
          { title: "筛选条件", render: (_, s) => filterText(s.filter) },
          { title: "文档", align: "right", width: 90, render: (_, s) => fmt(s.stats.documents) },
          { title: "句", align: "right", width: 100, render: (_, s) => fmt(s.stats.sentences) },
          { title: "词", align: "right", width: 110, render: (_, s) => fmt(s.stats.tokens) },
          {
            title: "操作",
            width: 80,
            render: (_, s) =>
              editable && (
                <Popconfirm title={`删除子库「${s.name}」？`} onConfirm={() => remove.mutate(s.id)}>
                  <Button type="link" danger size="small">
                    删除
                  </Button>
                </Popconfirm>
              ),
          },
        ]}
      />
      <Modal title="新建子库" open={creating} footer={null} onCancel={() => setCreating(false)} destroyOnClose width={560}>
        <CreateSubcorpus
          corpora={corpora.filter((c) => c.status === "ready" || c.status === "stale")}
          onDone={() => {
            setCreating(false);
            qc.invalidateQueries({ queryKey: ["subcorpora", projectId] });
          }}
        />
      </Modal>
    </Card>
  );
}

type FormValues = {
  name: string;
  corpus_id: string;
  fields?: Record<string, (string | number)[] | { gte?: number | null; lte?: number | null } | undefined>;
};

function buildFilter(fields: MetadataField[], values: FormValues["fields"]): Record<string, FilterValue> {
  const filter: Record<string, FilterValue> = {};
  for (const f of fields) {
    const v = values?.[f.field];
    if (!v) continue;
    if (Array.isArray(v)) {
      if (v.length) filter[f.field] = v;
    } else {
      const range: { gte?: number; lte?: number } = {};
      if (v.gte != null) range.gte = v.gte;
      if (v.lte != null) range.lte = v.lte;
      if (Object.keys(range).length) filter[f.field] = range;
    }
  }
  return filter;
}

function CreateSubcorpus({ corpora, onDone }: { corpora: Corpus[]; onDone: () => void }) {
  const projectId = useProjectId();
  const [form] = Form.useForm<FormValues>();
  const corpusId = Form.useWatch("corpus_id", form);
  const fields = useQuery({
    queryKey: ["metadata-fields", corpusId],
    queryFn: () => api.get<MetadataField[]>(`/corpora/${corpusId}/metadata-fields`),
    enabled: !!corpusId,
  });
  const create = useMutation({
    mutationFn: (v: FormValues) =>
      api.post<Subcorpus>(`/projects/${projectId}/subcorpora`, {
        name: v.name.trim(),
        corpus_id: v.corpus_id,
        filter: buildFilter(fields.data ?? [], v.fields),
      }),
    onSuccess: onDone,
  });

  return (
    <Form form={form} layout="vertical" onFinish={create.mutate}>
      <Form.Item name="name" label="名称" rules={[{ required: true, whitespace: true, message: "请输入名称" }]}>
        <Input maxLength={100} />
      </Form.Item>
      <Form.Item name="corpus_id" label="语料库" rules={[{ required: true, message: "请选择语料库" }]}>
        <Select
          options={corpora.map((c) => ({ value: c.id, label: c.name }))}
          onChange={() => form.setFieldValue("fields", undefined)}
        />
      </Form.Item>
      {fields.isFetching && <Spin />}
      {fields.error && <Alert type="error" showIcon message={errorText(fields.error)} style={{ marginBottom: 12 }} />}
      {fields.data && fields.data.length === 0 && (
        <Alert type="info" message="该语料库没有元数据字段" style={{ marginBottom: 12 }} />
      )}
      {fields.data?.map((f) =>
        f.type === "number" ? (
          <Form.Item key={f.field} label={f.field}>
            <Space>
              <Form.Item name={["fields", f.field, "gte"]} noStyle>
                <InputNumber placeholder="最小" />
              </Form.Item>
              至
              <Form.Item name={["fields", f.field, "lte"]} noStyle>
                <InputNumber placeholder="最大" />
              </Form.Item>
            </Space>
          </Form.Item>
        ) : (
          <Form.Item key={f.field} name={["fields", f.field]} label={f.field}>
            <Select mode="multiple" allowClear options={(f.values ?? []).map((v) => ({ value: v, label: String(v) }))} />
          </Form.Item>
        ),
      )}
      {create.error && <Alert type="error" showIcon message={errorText(create.error)} style={{ marginBottom: 12 }} />}
      <Button type="primary" htmlType="submit" loading={create.isPending}>
        创建
      </Button>
    </Form>
  );
}
