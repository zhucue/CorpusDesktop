import { UploadOutlined } from "@ant-design/icons";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Upload,
  type UploadFile,
} from "antd";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { api, errorText, type Doc, type Job, type Metadata, type Page } from "../api";
import { CorpusStatusTag, fmt, fmtTime, languageOptions, metadataText, useCorpus } from "../corpora";
import { useMe } from "../App";
import { canEdit, useProject, useProjectId } from "../projects";

const PAGE_SIZE = 50;

function parseMetadata(text: string | undefined): Metadata {
  if (!text?.trim()) return {};
  const v: unknown = JSON.parse(text);
  if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error("元数据须为 JSON 对象");
  return v as Metadata;
}

const metadataRule = {
  validator: (_: unknown, v: string | undefined) => {
    try {
      parseMetadata(v);
      return Promise.resolve();
    } catch (e) {
      return Promise.reject(new Error(e instanceof SyntaxError ? "JSON 格式错误" : errorText(e)));
    }
  },
};

export default function CorpusDetail() {
  const projectId = useProjectId();
  const corpusId = useParams().corpusId!;
  const project = useProject();
  const me = useMe();
  const corpus = useCorpus(corpusId);
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [uploading, setUploading] = useState(false);
  const [editing, setEditing] = useState<Doc | null>(null);

  const docs = useQuery({
    queryKey: ["documents", corpusId, q, page],
    queryFn: () => api.get<Page<Doc>>(`/corpora/${corpusId}/documents`, { q, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["documents", corpusId] });
    qc.invalidateQueries({ queryKey: ["corpus", corpusId] });
    qc.invalidateQueries({ queryKey: ["corpora", projectId] });
  };

  const remove = useMutation({
    mutationFn: (docId: string) => api.del(`/corpora/${corpusId}/documents/${docId}`),
    onSuccess: refresh,
    onError: (e) => message.error(errorText(e)),
  });
  const reindex = useMutation({
    mutationFn: () => api.post<Job>(`/corpora/${corpusId}/reindex`),
    onSuccess: () => {
      message.success("已创建索引任务");
      refresh();
    },
    onError: (e) => message.error(errorText(e)),
  });

  if (corpus.isPending) return <Spin />;
  if (corpus.error) return <Alert type="error" showIcon message={errorText(corpus.error)} />;
  const c = corpus.data;
  // Project corpora: owner/editor. Built-in corpora: platform admins may upload and reindex.
  const editable = canEdit(project.data) && c.project_id !== null;
  const canLoad = editable || (c.project_id === null && !!me.data?.is_admin);

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Card
        title={
          <Space>
            <Link to={`/p/${projectId}/corpora`}>语料库</Link>/<span>{c.name}</span>
            {c.project_id === null && <Tag>内置</Tag>}
            {c.parallel && <Tag color="blue">平行</Tag>}
          </Space>
        }
        extra={
          canLoad && (
            <Space>
              {c.status === "stale" && (
                <Button onClick={() => reindex.mutate()} loading={reindex.isPending}>
                  重建索引
                </Button>
              )}
              <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploading(true)}>
                上传文档
              </Button>
            </Space>
          )
        }
      >
        <Descriptions size="small" column={4}>
          <Descriptions.Item label="状态">
            <CorpusStatusTag corpus={c} />
          </Descriptions.Item>
          <Descriptions.Item label="语言">{c.language}</Descriptions.Item>
          <Descriptions.Item label="文档">{fmt(c.stats.documents)}</Descriptions.Item>
          <Descriptions.Item label="句">{fmt(c.stats.sentences)}</Descriptions.Item>
          <Descriptions.Item label="词">{fmt(c.stats.tokens)}</Descriptions.Item>
          <Descriptions.Item label="索引版本">{c.index_version ?? "无"}</Descriptions.Item>
          {c.description && <Descriptions.Item label="描述">{c.description}</Descriptions.Item>}
        </Descriptions>
      </Card>
      <Card
        title="文档"
        extra={
          <Input.Search
            placeholder="标题"
            allowClear
            onSearch={(v) => {
              setQ(v.trim());
              setPage(1);
            }}
            style={{ width: 220 }}
          />
        }
      >
        {docs.error && <Alert type="error" showIcon message={errorText(docs.error)} />}
        <Table<Doc>
          rowKey="id"
          size="small"
          loading={docs.isFetching}
          dataSource={docs.data?.items}
          locale={{ emptyText: "暂无文档" }}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total: docs.data?.total ?? 0,
            showSizeChanger: false,
            showTotal: (t) => `共 ${fmt(t)} 篇`,
            onChange: setPage,
          }}
          columns={[
            { title: "标题", dataIndex: "title" },
            { title: "语言", dataIndex: "language", width: 70 },
            { title: "句", align: "right", width: 90, render: (_, d) => fmt(d.sentences) },
            { title: "词", align: "right", width: 100, render: (_, d) => fmt(d.tokens) },
            { title: "元数据", render: (_, d) => metadataText(d.metadata) },
            { title: "导入时间", width: 160, render: (_, d) => fmtTime(d.created_at) },
            {
              title: "操作",
              width: 120,
              render: (_, d) =>
                editable && (
                  <Space size={0}>
                    <Button type="link" size="small" onClick={() => setEditing(d)}>
                      编辑
                    </Button>
                    <Popconfirm title={`删除「${d.title}」？删除后需重建索引。`} onConfirm={() => remove.mutate(d.id)}>
                      <Button type="link" danger size="small">
                        删除
                      </Button>
                    </Popconfirm>
                  </Space>
                ),
            },
          ]}
        />
      </Card>
      <Modal title="上传文档" open={uploading} footer={null} onCancel={() => setUploading(false)} destroyOnClose>
        <UploadForm
          corpusId={corpusId}
          defaultLanguage={c.language}
          onDone={() => {
            setUploading(false);
            refresh();
          }}
        />
      </Modal>
      <Modal title="编辑文档" open={!!editing} footer={null} onCancel={() => setEditing(null)} destroyOnClose>
        {editing && (
          <EditDocument
            doc={editing}
            onDone={() => {
              setEditing(null);
              refresh();
            }}
          />
        )}
      </Modal>
    </Space>
  );
}

function UploadForm({
  corpusId,
  defaultLanguage,
  onDone,
}: {
  corpusId: string;
  defaultLanguage: string;
  onDone: () => void;
}) {
  const projectId = useProjectId();
  const { message } = App.useApp();
  const [files, setFiles] = useState<UploadFile[]>([]);
  const upload = useMutation({
    mutationFn: (v: { language?: string; metadata?: string }) => {
      const body = new FormData();
      for (const f of files) body.append("files", f.originFileObj as File);
      if (v.language) body.append("language", v.language);
      if (v.metadata?.trim()) body.append("metadata", JSON.stringify(parseMetadata(v.metadata)));
      return api.post<Job>(`/corpora/${corpusId}/documents`, body);
    },
    onSuccess: () => {
      message.success(
        <span>
          已创建导入任务，<Link to={`/p/${projectId}/jobs`}>查看任务</Link>
        </span>,
      );
      onDone();
    },
  });
  return (
    <Form layout="vertical" onFinish={upload.mutate} initialValues={{ language: defaultLanguage }}>
      <Form.Item label="文件" required>
        <Upload
          multiple
          fileList={files}
          beforeUpload={() => false}
          onChange={(info) => setFiles(info.fileList)}
          accept=".txt,.docx,.csv,.tsv,.conllu,.tmx"
        >
          <Button icon={<UploadOutlined />}>选择文件</Button>
        </Upload>
      </Form.Item>
      <Form.Item name="language" label="语言">
        <Select allowClear options={languageOptions} />
      </Form.Item>
      <Form.Item name="metadata" label="元数据（JSON，应用到本批全部文档）" rules={[metadataRule]}>
        <Input.TextArea rows={3} placeholder='{"year": 2020, "genre": "新闻"}' />
      </Form.Item>
      {upload.error && <Alert type="error" showIcon message={errorText(upload.error)} style={{ marginBottom: 12 }} />}
      <Button type="primary" htmlType="submit" loading={upload.isPending} disabled={files.length === 0}>
        上传
      </Button>
    </Form>
  );
}

function EditDocument({ doc, onDone }: { doc: Doc; onDone: () => void }) {
  const save = useMutation({
    mutationFn: (v: { title: string; metadata?: string }) =>
      api.patch<Doc>(`/corpora/${doc.corpus_id}/documents/${doc.id}`, {
        title: v.title.trim(),
        metadata: parseMetadata(v.metadata),
      }),
    onSuccess: onDone,
  });
  return (
    <Form
      layout="vertical"
      onFinish={save.mutate}
      initialValues={{ title: doc.title, metadata: JSON.stringify(doc.metadata, null, 2) }}
    >
      <Form.Item name="title" label="标题" rules={[{ required: true, whitespace: true, message: "请输入标题" }]}>
        <Input />
      </Form.Item>
      <Form.Item name="metadata" label="元数据（JSON）" rules={[metadataRule]}>
        <Input.TextArea rows={8} style={{ fontFamily: "monospace" }} />
      </Form.Item>
      {save.error && <Alert type="error" showIcon message={errorText(save.error)} style={{ marginBottom: 12 }} />}
      <Button type="primary" htmlType="submit" loading={save.isPending}>
        保存
      </Button>
    </Form>
  );
}
