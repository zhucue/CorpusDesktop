import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Form, Input, Modal, Popconfirm, Segmented, Select, Table } from "antd";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { api, errorText, type Corpus, type CorpusMeta, type Job } from "../../api";
import { ErrorAlert, RelTime, Tip } from "../../components/common";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/shell/AppShell";
import { useShell } from "../../components/shell/shell";
import { canEdit, useCorpora, useJobCreated, useMe, useProject, useProjectId } from "../../lib/data";
import { fmt } from "../../lib/format";
import "./corpora.css";
import CorpusDrawer from "./CorpusDrawer";
import { corpusLanguages, metaEntries, metaFromForm, scriptLabels, tagsetLabels } from "./CorpusMeta";
import { StatusCell } from "./StatusCell";
import Subcorpora from "./Subcorpora";
import UploadDialog, { languageOptions } from "./UploadDialog";

type Filter = "all" | "builtin" | "project";

export default function Corpora() {
  const projectId = useProjectId();
  const { corpusId } = useParams();
  const navigate = useNavigate();
  const project = useProject();
  const corpora = useCorpora(projectId);
  const me = useMe();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const { setScope } = useShell();
  const jobCreated = useJobCreated();
  const [filter, setFilter] = useState<Filter>("all");
  const [uploading, setUploading] = useState(false);
  const [creatingSub, setCreatingSub] = useState(false);
  const [creatingBuiltin, setCreatingBuiltin] = useState(false);
  const editable = canEdit(project.data);
  const isAdmin = !!me.data?.is_admin;

  const items = corpora.data?.items ?? [];
  const own = items.filter((c) => c.project_id !== null);
  const builtin = items.filter((c) => c.project_id === null);
  const shown = filter === "builtin" ? builtin : filter === "project" ? own : items;

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/corpora/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["corpora", projectId] }),
    onError: (e) => message.error(errorText(e)),
  });
  const reindex = useMutation({
    mutationFn: (id: string) => api.post<Job>(`/corpora/${id}/reindex`),
    onSuccess: () => {
      message.success("已创建索引任务");
      jobCreated(projectId);
      qc.invalidateQueries({ queryKey: ["corpora", projectId] });
    },
    onError: (e) => message.error(errorText(e)),
  });
  const retry = useMutation({
    mutationFn: (id: string) => api.post<Job>(`/corpora/${id}/retry`),
    onSuccess: () => {
      message.success("已重新排队");
      jobCreated(projectId);
      qc.invalidateQueries({ queryKey: ["corpora", projectId] });
    },
    onError: (e) => message.error(errorText(e)),
  });
  const createBuiltin = useMutation({
    mutationFn: ({ name, language, description, ...m }: { name: string; language: string; description?: string } & Partial<Record<keyof CorpusMeta, string>>) =>
      api.post<Corpus>("/corpora", { name, language, description, meta: metaFromForm(m) }),
    onSuccess: () => {
      setCreatingBuiltin(false);
      qc.invalidateQueries({ queryKey: ["corpora", projectId] });
    },
  });

  const canUpload = editable || isAdmin;
  const openGuide = () => navigate(`/onboarding?project=${projectId}`);

  return (
    <>
      <PageHeader
        title="语料库"
        crumbs={1}
        actions={
          <>
            <Segmented<Filter>
              size="small"
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: <SegCount label="全部" n={items.length} ready={corpora.isSuccess} /> },
                { value: "builtin", label: <SegCount label="内置" n={builtin.length} ready={corpora.isSuccess} /> },
                { value: "project", label: <SegCount label="项目" n={own.length} ready={corpora.isSuccess} /> },
              ]}
            />
            {isAdmin && (
              <button className="btn s" type="button" onClick={() => setCreatingBuiltin(true)}>
                <Icon name="plus" size={14} />
                <span className="lbl">新建内置语料</span>
              </button>
            )}
            {editable && (
              <button className="btn s" type="button" onClick={() => setCreatingSub(true)} disabled={!items.some((c) => c.status === "ready" || c.status === "stale")}>
                <Icon name="filter" size={14} />
                <span className="lbl">新建子库</span>
              </button>
            )}
            {canUpload && (
              <button className="btn s p" type="button" onClick={() => setUploading(true)}>
                <Icon name="upload" size={14} />
                上传语料
              </button>
            )}
          </>
        }
      />
      <div className="content">
        {corpora.isSuccess && items.length === 0 && (
          <section className="card empty-hero dotgrid" aria-label="新项目">
            <span className="eh-ic">
              <Icon name="db" />
            </span>
            <h3>项目还没有语料</h3>
            <div className="row">
              {canUpload && (
                <button className="btn p" type="button" onClick={() => setUploading(true)}>
                  <Icon name="box" size={14} />
                  导入示例语料
                </button>
              )}
              {canUpload && (
                <button className="btn" type="button" onClick={() => setUploading(true)}>
                  <Icon name="upload" size={14} />
                  上传文件
                </button>
              )}
              <button className="btn ghost" type="button" onClick={openGuide}>
                <Icon name="compass" size={14} />
                打开引导
              </button>
            </div>
            {builtin.length > 0 && (
              <div className="samples">
                {builtin.slice(0, 3).map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    className="card sample lift"
                    onClick={() => {
                      setScope({ corpus_id: c.id });
                      navigate(`/p/${projectId}/search`);
                    }}
                  >
                    <span className="row">
                      <b className="grow ellipsis">{c.name}</b>
                      <span className="tag t-gray">内置</span>
                    </span>
                    <span className="small muted num">
                      {fmt(c.stats.sentences)} 句 · {fmt(c.stats.tokens)} 词 · {corpusLanguages(c)}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </section>
        )}

        <section className="card" aria-label="语料库列表">
          <ErrorAlert error={corpora.error} style={{ margin: 16 }} />
          <Table<Corpus>
            className="corp"
            scroll={{ x: 1120 }}
            rowKey="id"
            loading={corpora.isPending}
            dataSource={shown}
            pagination={false}
            locale={{ emptyText: <span className="muted">暂无语料库</span> }}
            onRow={(c) => ({ onClick: () => navigate(`/p/${projectId}/corpora/${c.id}`), style: { cursor: "pointer" } })}
            columns={[
              {
                title: "名称",
                width: 220,
                render: (_, c) => (
                  <div className="cname">
                    <span>{c.name}</span>
                    {c.project_id === null ? <span className="tag t-gray">内置</span> : <span className="tag t-line">项目</span>}
                    {c.parallel && <span className="tag t-info">平行</span>}
                  </div>
                ),
              },
              {
                title: "许可",
                width: 110,
                ellipsis: true,
                render: (_, c) => {
                  const rows = metaEntries(c.meta);
                  if (!rows.length) return null;
                  return (
                    <Tip
                      title={rows.map(([k, label, v]) => (
                        <div key={k}>
                          {label}：{v}
                        </div>
                      ))}
                    >
                      <span className="small">{c.meta?.license?.trim() || "见署名"}</span>
                    </Tip>
                  );
                },
              },
              {
                title: "语言 · 词性",
                width: 120,
                render: (_, c) => (
                  <span className="col" style={{ gap: 2 }}>
                    <span className="mono">{corpusLanguages(c)}</span>
                    {(c.meta?.script || c.meta?.tagset) && (
                      <span className="small muted">{[c.meta.script && (scriptLabels[c.meta.script] ?? c.meta.script), c.meta.tagset && (tagsetLabels[c.meta.tagset] ?? c.meta.tagset)].filter(Boolean).join(" · ")}</span>
                    )}
                  </span>
                ),
              },
              {
                title: "文档",
                width: 96,
                align: "right",
                className: "num-col",
                render: (_, c) =>
                  c.parallel && c.stats.pairs != null ? (
                    <Tip title={`${fmt(c.stats.documents)} 个文档（每种语言一个）`}>
                      <span>{fmt(c.stats.pairs)} 句对</span>
                    </Tip>
                  ) : (
                    fmt(c.stats.documents)
                  ),
              },
              { title: "句", width: 84, align: "right", className: "num-col", render: (_, c) => fmt(c.stats.sentences) },
              { title: "词", width: 96, align: "right", className: "num-col", render: (_, c) => fmt(c.stats.tokens) },
              { title: "状态", width: 130, render: (_, c) => <StatusCell c={c} /> },
              {
                title: "索引更新",
                width: 96,
                render: (_, c) =>
                  c.index_version == null ? (
                    <span className="muted">—</span>
                  ) : c.meta?.indexed_at ? (
                    <RelTime at={c.meta.indexed_at} />
                  ) : (
                    <span>已建</span>
                  ),
              },
              { title: "创建", width: 90, render: (_, c) => <RelTime at={c.created_at} /> },
              {
                title: "",
                width: 80,
                align: "right",
                render: (_, c) => {
                  const mine = c.project_id !== null ? editable : isAdmin;
                  if (!mine) return null;
                  return (
                    <span className="row" style={{ justifyContent: "flex-end", gap: 4 }} onClick={(e) => e.stopPropagation()}>
                      {c.status === "stale" && (
                        <button className="btn xs" type="button" onClick={() => reindex.mutate(c.id)} disabled={reindex.isPending}>
                          重建
                        </button>
                      )}
                      {(c.status === "failed" || (!c.updating && !!c.error)) && (
                        <button className="btn xs" type="button" onClick={() => retry.mutate(c.id)} disabled={retry.isPending}>
                          重试
                        </button>
                      )}
                      {c.project_id !== null && (
                        <Popconfirm title={`删除语料库「${c.name}」？`} okText="删除" cancelText="取消" onConfirm={() => remove.mutate(c.id)}>
                          <Tip title="删除语料库">
                            <button className="btn ghost icon danger" type="button" aria-label={`删除语料库「${c.name}」`}>
                              <Icon name="trash" size={14} />
                            </button>
                          </Tip>
                        </Popconfirm>
                      )}
                    </span>
                  );
                },
              },
            ]}
          />
        </section>

        <Subcorpora corpora={items} editable={editable} creating={creatingSub} setCreating={setCreatingSub} />
      </div>

      <UploadDialog open={uploading} projectId={projectId} corpora={items} corpusId={corpusId} isAdmin={isAdmin} onClose={() => setUploading(false)} />
      <CorpusDrawer corpusId={corpusId ?? null} onClose={() => navigate(`/p/${projectId}/corpora`)} />
      <Modal title="新建内置语料" open={creatingBuiltin} onCancel={() => setCreatingBuiltin(false)} footer={null} destroyOnHidden>
        <Form layout="vertical" onFinish={(v) => createBuiltin.mutate(v)} initialValues={{ language: "zh" }} requiredMark={false}>
          <Form.Item name="name" label="名称" rules={[{ required: true, whitespace: true, message: "请输入名称" }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="language" label="语言">
            <Select options={languageOptions} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="license" label="许可">
            <Input maxLength={200} placeholder="CC BY 2.0 FR" />
          </Form.Item>
          <Form.Item name="attribution" label="署名">
            <Input.TextArea rows={2} maxLength={2000} />
          </Form.Item>
          <Form.Item name="source_url" label="来源链接">
            <Input maxLength={1000} placeholder="https://" />
          </Form.Item>
          <Form.Item name="version" label="版本">
            <Input maxLength={200} />
          </Form.Item>
          <ErrorAlert error={createBuiltin.error} style={{ marginBottom: 12 }} />
          <button className="btn p" type="submit" disabled={createBuiltin.isPending}>
            创建
          </button>
        </Form>
      </Modal>
    </>
  );
}

function SegCount({ label, n, ready }: { label: string; n: number; ready: boolean }) {
  return (
    <span>
      {label}
      {ready && <span className="num seg-n">{fmt(n)}</span>}
    </span>
  );
}
