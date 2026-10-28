import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Drawer, Form, Input, Modal, Popconfirm, Select, Table, Tabs, type UploadFile } from "antd";
import { useState } from "react";
import { Link } from "react-router";
import { api, errorText, type Doc, type DocSentence, type Job, type MetadataField, type Page } from "../../api";
import { Empty, ErrorAlert, Skeleton, Tip } from "../../components/common";
import { Icon } from "../../components/Icon";
import { canEdit, useCorpus, useJobCreated, useMe, useProject, useProjectId } from "../../lib/data";
import { fmt, fmtRelative, fmtTime, fmtVersion, metadataText } from "../../lib/format";
import { CorpusMetaList, corpusProfile } from "./CorpusMeta";
import { draftFrom, emptyMeta, MetadataInput, metadataFromDraft, metaDraftRule, type MetaDraft } from "./MetadataInput";
import { StatusCell } from "./StatusCell";
import { TableMappingFields, useTableMapping } from "./TableMapping";
import { AUTO_LANGUAGE, FilePicker, uploadFiles, uploadLanguageOptions } from "./UploadDialog";

const PAGE_SIZE = 50;
const SENTENCE_PAGE = 50;

export default function CorpusDrawer({ corpusId, onClose }: { corpusId: string | null; onClose: () => void }) {
  const corpus = useCorpus(corpusId ?? undefined);
  const project = useProject();
  const me = useMe();
  const c = corpus.data;
  const editable = !!c && ((canEdit(project.data) && c.project_id !== null) || (c.project_id === null && !!me.data?.is_admin));

  return (
    <Drawer
      open={!!corpusId}
      onClose={onClose}
      width={640}
      title={
        c && (
          <span className="row">
            <span>{c.name}</span>
            {c.project_id === null ? <span className="tag t-gray">内置</span> : <span className="tag t-line">项目</span>}
            {c.parallel && <span className="tag t-info">平行</span>}
          </span>
        )
      }
      destroyOnHidden
    >
      {corpus.isPending && <Skeleton />}
      <ErrorAlert error={corpus.error} />
      {c && (
        <div className="col gap-20">
          <div className="counts-row">
            {c.parallel && c.stats.pairs != null ? (
              <div title={`${fmt(c.stats.documents)} 个文档（每种语言一个）`}>
                <div className="stat-label">句对</div>
                <div className="count">
                  {fmt(c.stats.pairs)}
                  <span className="unit">对</span>
                </div>
              </div>
            ) : (
              <div>
                <div className="stat-label">文档</div>
                <div className="count">
                  {fmt(c.stats.documents)}
                  <span className="unit">篇</span>
                </div>
              </div>
            )}
            <div>
              <div className="stat-label">句</div>
              <div className="count">
                {fmt(c.stats.sentences)}
                <span className="unit">句</span>
              </div>
            </div>
            <div>
              <div className="stat-label">词</div>
              <div className="count">
                {fmt(c.stats.tokens)}
                <span className="unit">词</span>
              </div>
            </div>
            <div title={c.index_version != null ? `版本 ${fmtVersion(c.index_version)}` : undefined}>
              <div className="stat-label">索引更新</div>
              <div className="count">{c.index_version == null ? "—" : c.meta?.indexed_at ? fmtRelative(c.meta.indexed_at) : "已建"}</div>
            </div>
          </div>
          <div className="row">
            <StatusCell c={c} />
            <div className="grow" />
            <span className="small muted">
              {corpusProfile(c).join(" · ")} · 创建于 {fmtTime(c.created_at)}
            </span>
          </div>
          {c.description && <p className="sm sub">{c.description}</p>}
          <CorpusMetaList meta={c.meta} />
          <Tabs
            items={[
              { key: "docs", label: "文档", children: <Documents corpusId={c.id} editable={editable} /> },
              ...(editable ? [{ key: "upload", label: "上传", children: <UploadTab corpusId={c.id} /> }] : []),
              { key: "meta", label: "元数据", children: <MetadataFields corpusId={c.id} /> },
            ]}
          />
        </div>
      )}
    </Drawer>
  );
}

function Documents({ corpusId, editable }: { corpusId: string; editable: boolean }) {
  const projectId = useProjectId();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<Doc | null>(null);
  const [viewing, setViewing] = useState<Doc | null>(null);
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

  return (
    <>
      <div className="docs-tools">
        <Input.Search
          placeholder="标题"
          allowClear
          size="small"
          onSearch={(v) => {
            setQ(v.trim());
            setPage(1);
          }}
          style={{ width: 220 }}
        />
        <div className="grow" />
        <span className="small muted num">{fmt(docs.data?.total ?? 0)} 篇</span>
      </div>
      <ErrorAlert error={docs.error} style={{ marginBottom: 12 }} />
      <Table<Doc>
        rowKey="id"
        size="small"
        loading={docs.isFetching}
        dataSource={docs.data?.items}
        locale={{ emptyText: "暂无文档" }}
        onRow={(d) => ({ onClick: () => setViewing(d), style: { cursor: "pointer" } })}
        pagination={{ current: page, pageSize: PAGE_SIZE, total: docs.data?.total ?? 0, showSizeChanger: false, onChange: setPage, size: "small" }}
        columns={[
          { title: "标题", dataIndex: "title", ellipsis: true },
          { title: "句", width: 80, align: "right", className: "num-col", render: (_, d) => fmt(d.sentences) },
          { title: "词", width: 90, align: "right", className: "num-col", render: (_, d) => fmt(d.tokens) },
          { title: "元数据", ellipsis: true, render: (_, d) => <span className="small muted">{metadataText(d.metadata)}</span> },
          {
            title: "",
            width: 76,
            render: (_, d) =>
              editable && (
                <span className="row" style={{ gap: 2 }} onClick={(e) => e.stopPropagation()}>
                  <Tip title="编辑文档">
                    <button className="btn ghost icon" type="button" aria-label={`编辑文档「${d.title}」`} onClick={() => setEditing(d)}>
                      <Icon name="edit" size={14} />
                    </button>
                  </Tip>
                  <Popconfirm title={`删除「${d.title}」？删除后需重建索引。`} okText="删除" cancelText="取消" onConfirm={() => remove.mutate(d.id)}>
                    <Tip title="删除文档">
                      <button className="btn ghost icon danger" type="button" aria-label={`删除文档「${d.title}」`}>
                        <Icon name="trash" size={14} />
                      </button>
                    </Tip>
                  </Popconfirm>
                </span>
              ),
          },
        ]}
      />
      <Modal title={viewing?.title} open={!!viewing} footer={null} onCancel={() => setViewing(null)} width={760} destroyOnHidden>
        {viewing && <DocumentView doc={viewing} />}
      </Modal>
      <Modal title="编辑文档" open={!!editing} footer={null} onCancel={() => setEditing(null)} destroyOnHidden>
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
    </>
  );
}

/** One document: its metadata and stored sentences (the import's sentence split); aligned sentences in parallel corpora. */
function DocumentView({ doc }: { doc: Doc }) {
  const [page, setPage] = useState(1);
  const sentences = useQuery({
    queryKey: ["doc-sentences", doc.id, page],
    queryFn: () => api.get<Page<DocSentence>>(`/corpora/${doc.corpus_id}/documents/${doc.id}/sentences`, { page, page_size: SENTENCE_PAGE }),
    placeholderData: keepPreviousData,
  });
  const meta = Object.entries(doc.metadata ?? {});
  const total = sentences.data?.total ?? 0;
  return (
    <div className="col gap-12">
      <dl className="kv doc-kv">
        <dt>语言</dt>
        <dd className="mono">{doc.language || "—"}</dd>
        <dt>规模</dt>
        <dd className="num">
          {fmt(doc.sentences)} 句 · {fmt(doc.tokens)} 词
        </dd>
        {meta.map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt className="mono">{k}</dt>
            <dd>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
          </div>
        ))}
      </dl>
      <ErrorAlert error={sentences.error} />
      {sentences.isPending && <Skeleton rows={4} />}
      {sentences.data && total === 0 && <Empty icon="filetext" text="没有句子" />}
      {sentences.data && total > 0 && (
        <>
          <ol className="doc-sents" aria-label="句子">
            {sentences.data.items.map((s) => (
              <li key={s.idx}>
                <span className="ds-n num">{s.idx + 1}</span>
                <span className="ds-t">
                  {s.text}
                  {s.aligned.map((a, i) => (
                    <span className="ds-a" key={i}>
                      <b className="mono">{a.language}</b> {a.text}
                    </span>
                  ))}
                </span>
              </li>
            ))}
          </ol>
          {total > SENTENCE_PAGE && (
            <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
              <span className="small muted num">
                第 {fmt((page - 1) * SENTENCE_PAGE + 1)}–{fmt(Math.min(page * SENTENCE_PAGE, total))} 句，共 {fmt(total)} 句
              </span>
              <button className="btn xs" type="button" disabled={page === 1} onClick={() => setPage(page - 1)}>
                上一页
              </button>
              <button className="btn xs" type="button" disabled={page * SENTENCE_PAGE >= total} onClick={() => setPage(page + 1)}>
                下一页
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function EditDocument({ doc, onDone }: { doc: Doc; onDone: () => void }) {
  const save = useMutation({
    mutationFn: (v: { title: string; metadata?: MetaDraft }) =>
      api.patch<Doc>(`/corpora/${doc.corpus_id}/documents/${doc.id}`, { title: v.title.trim(), metadata: metadataFromDraft(v.metadata) }),
    onSuccess: onDone,
  });
  return (
    <Form layout="vertical" onFinish={save.mutate} initialValues={{ title: doc.title, metadata: draftFrom(doc.metadata) }} requiredMark={false}>
      <Form.Item name="title" label="标题" rules={[{ required: true, whitespace: true, message: "请输入标题" }]}>
        <Input />
      </Form.Item>
      <Form.Item name="metadata" label="元数据" rules={[metaDraftRule]}>
        <MetadataInput />
      </Form.Item>
      <ErrorAlert error={save.error} style={{ marginBottom: 12 }} />
      <button className="btn p" type="submit" disabled={save.isPending}>
        保存
      </button>
    </Form>
  );
}

function UploadTab({ corpusId }: { corpusId: string }) {
  const projectId = useProjectId();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const jobCreated = useJobCreated();
  const [files, setFiles] = useState<UploadFile[]>([]);
  const table = useTableMapping(files.map((f) => f.originFileObj as File));
  const upload = useMutation({
    mutationFn: (v: { language?: string; metadata?: MetaDraft }) =>
      uploadFiles(
        corpusId,
        files.map((f) => f.originFileObj as File),
        v.language,
        metadataFromDraft(v.metadata),
        table.mapping,
      ),
    onSuccess: (job: Job) => {
      setFiles([]);
      jobCreated(projectId);
      qc.invalidateQueries({ queryKey: ["corpus", corpusId] });
      qc.invalidateQueries({ queryKey: ["corpora", projectId] });
      message.success(
        <span>
          已创建导入任务 #{job.id.slice(0, 8)}，<Link to={`/p/${projectId}/jobs`}>查看任务</Link>
        </span>,
      );
    },
  });
  return (
    <Form layout="vertical" onFinish={upload.mutate} initialValues={{ language: AUTO_LANGUAGE, metadata: emptyMeta() }}>
      <Form.Item>
        <FilePicker files={files} setFiles={setFiles} hint="TXT · DOCX · CSV/TSV · CoNLL-U · TMX" />
      </Form.Item>
      <TableMappingFields state={table} />
      <Form.Item name="language" label="语言">
        <Select options={uploadLanguageOptions} aria-label="语言" />
      </Form.Item>
      <Form.Item name="metadata" label="元数据（应用到本批全部文档）" rules={[metaDraftRule]}>
        <MetadataInput />
      </Form.Item>
      <ErrorAlert error={upload.error} style={{ marginBottom: 12 }} />
      <button className="btn p" type="submit" disabled={upload.isPending || files.length === 0 || !table.ready}>
        <Icon name="upload" size={14} />
        上传
      </button>
    </Form>
  );
}

function MetadataFields({ corpusId }: { corpusId: string }) {
  const fields = useQuery({
    queryKey: ["metadata-fields", corpusId],
    queryFn: () => api.get<MetadataField[]>(`/corpora/${corpusId}/metadata-fields`),
  });
  if (fields.isPending) return <Skeleton rows={3} />;
  if (fields.error) return <ErrorAlert error={fields.error} />;
  if (!fields.data.length) return <div className="empty sm">没有元数据字段</div>;
  return (
    <table className="tbl mid">
      <thead>
        <tr>
          <th>字段</th>
          <th>类型</th>
          <th>取值</th>
        </tr>
      </thead>
      <tbody>
        {fields.data.map((f) => (
          <tr key={f.field}>
            <td className="mono">{f.field}</td>
            <td>
              <span className="tag t-gray">{f.type === "number" ? "数值" : "文本"}</span>
            </td>
            <td className="small sub">{(f.values ?? []).slice(0, 12).join("、") + ((f.values?.length ?? 0) > 12 ? " …" : "")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
