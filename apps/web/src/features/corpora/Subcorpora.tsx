import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Spin } from "antd";
import { useNavigate } from "react-router";
import { api, errorText, type Corpus, type Filter, type MetadataField, type Subcorpus } from "../../api";
import { Empty, ErrorAlert, Tip } from "../../components/common";
import { Icon } from "../../components/Icon";
import { useShell } from "../../components/shell/shell";
import { useProjectId, useSubcorpora } from "../../lib/data";
import { fmt } from "../../lib/format";

export function filterText(filter: Filter): string {
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

export default function Subcorpora({
  corpora,
  editable,
  creating,
  setCreating,
}: {
  corpora: Corpus[];
  editable: boolean;
  creating: boolean;
  setCreating: (v: boolean) => void;
}) {
  const projectId = useProjectId();
  const list = useSubcorpora(projectId);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { setScope } = useShell();
  const names = new Map(corpora.map((c) => [c.id, c.name]));

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/subcorpora/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["subcorpora", projectId] }),
    onError: (e) => message.error(errorText(e)),
  });
  const items = list.data?.items ?? [];

  return (
    <section className="card" aria-label="子库">
      <div className="card-head">
        <h2 className="grow">子库</h2>
        <span className="small muted num">{items.length} 个</span>
      </div>
      <ErrorAlert error={list.error} style={{ margin: 16 }} />
      {list.isSuccess && items.length === 0 && (
        <Empty icon="filter" text="暂无子库">
          {editable && (
            <button className="btn s" type="button" onClick={() => setCreating(true)}>
              新建子库
            </button>
          )}
        </Empty>
      )}
      {items.length > 0 && (
        <div className="sub-list">
          {items.map((s) => (
            <div className="sub-item" key={s.id}>
              <div className="row">
                <b className="grow ellipsis" style={{ fontWeight: 600 }}>
                  {s.name}
                </b>
                <Tip title="在检索中使用">
                  <button
                    className="btn ghost icon"
                    type="button"
                    aria-label="在检索中使用"
                    onClick={() => {
                      setScope({ subcorpus_id: s.id });
                      navigate(`/p/${projectId}/search`);
                    }}
                  >
                    <Icon name="search" size={14} />
                  </button>
                </Tip>
                {editable && (
                  <Popconfirm title={`删除子库「${s.name}」？`} okText="删除" cancelText="取消" onConfirm={() => remove.mutate(s.id)}>
                    <button className="btn ghost icon danger" type="button" aria-label="删除">
                      <Icon name="trash" size={14} />
                    </button>
                  </Popconfirm>
                )}
              </div>
              <span className="small muted num">
                {names.get(s.corpus_id) ?? s.corpus_id} · {fmt(s.stats.documents)} 篇 · {fmt(s.stats.sentences)} 句 · {fmt(s.stats.tokens)} 词
              </span>
              <code className="q">{Object.keys(s.filter).length ? filterText(s.filter) : "全部文档"}</code>
            </div>
          ))}
        </div>
      )}
      <Modal title="新建子库" open={creating} footer={null} onCancel={() => setCreating(false)} destroyOnHidden width={560}>
        <CreateSubcorpus
          corpora={corpora.filter((c) => c.status === "ready" || c.status === "stale")}
          onDone={(s) => {
            setCreating(false);
            qc.invalidateQueries({ queryKey: ["subcorpora", projectId] });
            message.success(`已创建子库「${s.name}」`);
          }}
        />
      </Modal>
    </section>
  );
}

type FormValues = {
  name: string;
  corpus_id: string;
  fields?: Record<string, (string | number)[] | { gte?: number | null; lte?: number | null } | undefined>;
};

export function buildFilter(fields: MetadataField[], values: FormValues["fields"]): Filter {
  const filter: Filter = {};
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

function CreateSubcorpus({ corpora, onDone }: { corpora: Corpus[]; onDone: (s: Subcorpus) => void }) {
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
    <Form form={form} layout="vertical" onFinish={create.mutate} requiredMark={false}>
      <Form.Item name="name" label="名称" rules={[{ required: true, whitespace: true, message: "请输入名称" }]}>
        <Input maxLength={100} />
      </Form.Item>
      <Form.Item name="corpus_id" label="语料库" rules={[{ required: true, message: "请选择语料库" }]}>
        <Select options={corpora.map((c) => ({ value: c.id, label: c.name }))} onChange={() => form.setFieldValue("fields", undefined)} />
      </Form.Item>
      {fields.isFetching && <Spin />}
      <ErrorAlert error={fields.error} style={{ marginBottom: 12 }} />
      {fields.data && fields.data.length === 0 && <div className="alert info" style={{ marginBottom: 12 }}>该语料库没有元数据字段</div>}
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
      <ErrorAlert error={create.error} style={{ marginBottom: 12 }} />
      <button className="btn p" type="submit" disabled={create.isPending}>
        创建
      </button>
    </Form>
  );
}
