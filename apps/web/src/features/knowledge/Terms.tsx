import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Drawer, Dropdown, Form, Input, InputNumber, Modal, Popconfirm, Radio, Select, Table } from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, errorText, type Job, type KbDocument, type Scope, type Term, type TermTranslation } from "../../api";
import { ErrorAlert } from "../../components/common";
import { ScopeSelect } from "../../components/common/ScopeSelect";
import { useEvidence } from "../../components/global/evidence";
import { Icon } from "../../components/Icon";
import { useOptionalShell } from "../../components/shell/shell";
import { useJob, useJobCreated } from "../../lib/data";
import { fmt, fmtShortTime } from "../../lib/format";
import { useDebounced } from "../../lib/useDebounced";
import { languageOptions } from "../corpora/UploadDialog";
import { useTermUpdated, useTerms } from "./data";

const PAGE = 50;

export const termSourceLabels: Record<Term["source"], string> = { manual: "手工", corpus: "语料", literature: "文献", model: "模型" };

export function TermStatusTag({ status }: { status: Term["status"] }) {
  return status === "confirmed" ? <span className="tag t-ok">已确认</span> : <span className="tag t-gray">草稿</span>;
}

function useTermPatch(onDone?: (t: Term) => void) {
  const updated = useTermUpdated();
  const { message } = App.useApp();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<Term> }) => api.patch<Term>(`/kb/terms/${id}`, body),
    onSuccess: (t) => {
      updated(t);
      onDone?.(t);
    },
    onError: (e) => message.error(errorText(e)),
  });
}

/* ---------- term card drawer ---------- */

export function TermDrawer({
  term,
  editable,
  onClose,
  onChange,
}: {
  term: Term | null;
  editable: boolean;
  onClose: () => void;
  onChange: (t: Term) => void;
}) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const ev = useEvidence();
  const [tr, setTr] = useState<TermTranslation[]>([]);
  const [definition, setDefinition] = useState("");
  const [domain, setDomain] = useState("");
  const [evId, setEvId] = useState<string | undefined>();
  const id = term?.id;

  useEffect(() => {
    setTr(term?.translations?.length ? term.translations : [{ language: "en", text: "" }]);
    setDefinition(term?.definition ?? "");
    setDomain(term?.domain ?? "");
    // Reset only when another term opens; saves come back through `term`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const patch = useTermPatch(onChange);
  const addExample = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post<Term>(`/kb/terms/${id}/examples`, body),
    onSuccess: (t) => {
      onChange(t);
      void qc.invalidateQueries({ queryKey: ["kb-terms"] });
      setEvId(undefined);
      message.success("已加入例句");
    },
    onError: (e) => message.error(errorText(e)),
  });
  const del = useMutation({
    mutationFn: () => api.del(`/kb/terms/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["kb-terms"] });
      message.success("已删除");
      onClose();
    },
    onError: (e) => message.error(errorText(e)),
  });

  const hits = (ev?.items ?? []).filter((e) => e.kind === "hit");
  const cleanTr = tr.map((t) => ({ language: t.language.trim(), text: t.text.trim() })).filter((t) => t.text);
  const dirty =
    !!term &&
    (definition !== (term.definition ?? "") || domain !== (term.domain ?? "") || JSON.stringify(cleanTr) !== JSON.stringify(term.translations ?? []));

  return (
    <Drawer
      open={!!term}
      onClose={onClose}
      width={560}
      destroyOnHidden
      title={term && <span>术语</span>}
      extra={
        term &&
        editable && (
          <Popconfirm title="删除这条术语？" okText="删除" cancelText="取消" onConfirm={() => del.mutate()}>
            <button className="btn s danger" type="button">
              <Icon name="trash" size={14} />
              删除
            </button>
          </Popconfirm>
        )
      }
    >
      {term && (
        <article className="col gap-16 term-big" data-testid="term-card">
          <div className="row" style={{ alignItems: "flex-start" }}>
            <div className="grow">
              <h2>{term.term}</h2>
              <div className="mono sub small" style={{ marginTop: 2 }}>
                {term.language} · {termSourceLabels[term.source] ?? term.source}
              </div>
            </div>
            {term.domain && <span className="tag t-gray">{term.domain}</span>}
            <TermStatusTag status={term.status} />
          </div>
          {editable && (
            <div className="row">
              {term.status === "draft" ? (
                <button
                  className="btn s p"
                  type="button"
                  disabled={patch.isPending}
                  onClick={() => patch.mutate({ id: term.id, body: { status: "confirmed" } })}
                >
                  <Icon name="check" size={14} />
                  确认
                </button>
              ) : (
                <button className="btn s" type="button" disabled={patch.isPending} onClick={() => patch.mutate({ id: term.id, body: { status: "draft" } })}>
                  <Icon name="retry" size={14} />
                  撤回确认
                </button>
              )}
              <div className="grow" />
              <button
                className="btn s"
                type="button"
                disabled={!dirty || patch.isPending}
                onClick={() => patch.mutate({ id: term.id, body: { translations: cleanTr, definition: definition.trim(), domain: domain.trim() } })}
              >
                保存修改
              </button>
            </div>
          )}

          <div className="col gap-4">
            <span className="label">译名</span>
            {editable ? (
              <div className="col" style={{ gap: 6 }}>
                {tr.map((t, i) => (
                  <div className="row" key={i}>
                    <Select
                      size="small"
                      style={{ width: 110 }}
                      value={t.language}
                      options={languageOptions}
                      onChange={(v) => setTr(tr.map((x, k) => (k === i ? { ...x, language: v } : x)))}
                      aria-label="译名语言"
                    />
                    <Input size="small" value={t.text} onChange={(e) => setTr(tr.map((x, k) => (k === i ? { ...x, text: e.target.value } : x)))} aria-label="译名" />
                    <button className="btn ghost icon" type="button" aria-label="删除译名" onClick={() => setTr(tr.filter((_, k) => k !== i))}>
                      <Icon name="x" size={14} />
                    </button>
                  </div>
                ))}
                <button className="btn xs" type="button" style={{ alignSelf: "flex-start" }} onClick={() => setTr([...tr, { language: "en", text: "" }])}>
                  <Icon name="plus" size={14} />
                  添加译名
                </button>
              </div>
            ) : (
              <div className="row wrap">
                {(term.translations ?? []).map((t, i) => (
                  <span key={i} className={`tag ${i ? "t-line" : "t-accent-line"}`}>
                    {t.text}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="col gap-4">
            <span className="label">定义</span>
            {editable ? (
              <Input.TextArea rows={3} value={definition} onChange={(e) => setDefinition(e.target.value)} aria-label="定义" />
            ) : (
              <p style={{ lineHeight: 1.8 }}>{term.definition || <span className="muted">—</span>}</p>
            )}
          </div>

          <div className="col gap-4">
            <span className="label">领域</span>
            {editable ? <Input value={domain} onChange={(e) => setDomain(e.target.value)} aria-label="领域" /> : <span>{term.domain || "—"}</span>}
          </div>

          <div className="col" style={{ gap: 8 }}>
            <span className="label">语料例句 · {fmt(term.examples?.length ?? 0)}</span>
            {(term.examples ?? []).map((x, i) => (
              <div className="ex" key={i}>
                {x.text}
                <span className="mono small muted"> {x.source}</span>
                {editable && (
                  <button
                    className="pin-btn"
                    type="button"
                    aria-label="移除例句"
                    style={{ float: "right" }}
                    onClick={() => patch.mutate({ id: term.id, body: { examples: term.examples.filter((_, k) => k !== i) } })}
                  >
                    <Icon name="x" />
                  </button>
                )}
              </div>
            ))}
            {editable && (
              <div className="row">
                <Select
                  size="small"
                  className="grow"
                  placeholder={hits.length ? "从证据篮选择命中" : "证据篮里没有命中"}
                  disabled={!hits.length}
                  value={evId}
                  onChange={setEvId}
                  options={hits.map((h) => ({ value: h.id, label: `${h.text.slice(0, 40)} · ${h.source}` }))}
                  aria-label="证据篮命中"
                />
                <button
                  className="btn xs"
                  type="button"
                  disabled={!evId || addExample.isPending}
                  onClick={() => {
                    const h = hits.find((x) => x.id === evId);
                    if (h)
                      addExample.mutate({
                        hit_id: h.ref.hit_id,
                        document_id: h.ref.document_id,
                        start_cp: h.ref.start_cp,
                        end_cp: h.ref.end_cp,
                        text: h.text,
                        source: h.source,
                      });
                  }}
                >
                  <Icon name="plus" size={14} />
                  加入例句
                </button>
              </div>
            )}
          </div>
        </article>
      )}
    </Drawer>
  );
}

/* ---------- dialogs ---------- */

function NewTermDialog({ projectId, open, onClose, onCreated }: { projectId: string; open: boolean; onClose: () => void; onCreated: (t: Term) => void }) {
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const create = useMutation({
    mutationFn: (v: { term: string; language: string; tr_language: string; tr_text?: string; definition?: string; domain?: string }) =>
      api.post<Term>(`/projects/${projectId}/kb/terms`, {
        term: v.term.trim(),
        language: v.language,
        translations: v.tr_text?.trim() ? [{ language: v.tr_language, text: v.tr_text.trim() }] : [],
        definition: v.definition?.trim() ?? "",
        domain: v.domain?.trim() ?? "",
        source: "manual",
      }),
    onSuccess: (t) => {
      void qc.invalidateQueries({ queryKey: ["kb-terms"] });
      form.resetFields();
      onCreated(t);
      onClose();
    },
  });
  return (
    <Modal title="新建术语" open={open} onCancel={onClose} okText="创建" cancelText="取消" onOk={() => form.submit()} okButtonProps={{ loading: create.isPending }} destroyOnHidden>
      <Form form={form} layout="vertical" requiredMark={false} initialValues={{ language: "zh", tr_language: "en" }} onFinish={(v) => create.mutate(v)}>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <Form.Item name="term" label="术语" className="grow" rules={[{ required: true, whitespace: true, message: "请输入术语" }]}>
            <Input maxLength={200} autoFocus />
          </Form.Item>
          <Form.Item name="language" label="语言">
            <Select options={languageOptions} style={{ width: 120 }} />
          </Form.Item>
        </div>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <Form.Item name="tr_text" label="译名" className="grow">
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="tr_language" label="译名语言">
            <Select options={languageOptions} style={{ width: 120 }} />
          </Form.Item>
        </div>
        <Form.Item name="definition" label="定义">
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item name="domain" label="领域">
          <Input maxLength={100} />
        </Form.Item>
        <ErrorAlert error={create.error} />
      </Form>
    </Modal>
  );
}

function ExtractDialog({
  projectId,
  open,
  docs,
  onClose,
  onStarted,
}: {
  projectId: string;
  open: boolean;
  docs: KbDocument[];
  onClose: () => void;
  onStarted: (job: Job) => void;
}) {
  const shell = useOptionalShell();
  const [source, setSource] = useState<"corpus" | "literature">("corpus");
  const [scope, setScope] = useState<Scope | null>(shell?.scope ?? null);
  const [method, setMethod] = useState<"pos_pattern" | "model">("pos_pattern");
  const [top, setTop] = useState(100);
  const [docIds, setDocIds] = useState<string[]>([]);
  const lit = docs.filter((d) => (d.kind === "literature" || d.kind === "url") && d.status === "ready");
  const start = useMutation({
    mutationFn: () =>
      api.post<Job>(
        `/projects/${projectId}/kb/terms/extract`,
        source === "corpus" ? { source, scope, method, top } : { source, document_ids: docIds, method: "model" },
      ),
    onSuccess: (job) => {
      onStarted(job);
      onClose();
    },
  });
  const ok = source === "corpus" ? !!scope : docIds.length > 0;
  return (
    <Modal title="抽取术语" open={open} onCancel={onClose} okText="开始抽取" cancelText="取消" onOk={() => start.mutate()} okButtonProps={{ disabled: !ok, loading: start.isPending }} destroyOnHidden>
      <div className="col" style={{ gap: 14 }}>
        <div className="field">
          <span className="label">来源</span>
          <Radio.Group value={source} onChange={(e) => setSource(e.target.value)}>
            <Radio.Button value="corpus">语料</Radio.Button>
            <Radio.Button value="literature">文献</Radio.Button>
          </Radio.Group>
        </div>
        {source === "corpus" ? (
          <>
            <div className="field">
              <span className="label">范围</span>
              <ScopeSelect projectId={projectId} value={scope} onChange={setScope} width={320} />
            </div>
            <div className="field">
              <span className="label">方法</span>
              <Radio.Group value={method} onChange={(e) => setMethod(e.target.value)}>
                <Radio value="pos_pattern">词性模式</Radio>
                <Radio value="model">对话模型</Radio>
              </Radio.Group>
            </div>
            <div className="field">
              <span className="label">候选数</span>
              <InputNumber min={1} max={1000} value={top} onChange={(v) => setTop(v ?? 100)} />
            </div>
          </>
        ) : (
          <>
            <div className="field">
              <span className="label">文献</span>
              <Select
                mode="multiple"
                value={docIds}
                onChange={setDocIds}
                placeholder={lit.length ? "选择文献" : "没有可检索的文献"}
                options={lit.map((d) => ({ value: d.id, label: d.title }))}
                optionFilterProp="label"
              />
            </div>
            <div className="small muted">方法：对话模型</div>
          </>
        )}
        <ErrorAlert error={start.error} />
      </div>
    </Modal>
  );
}

/** Watches an extraction job; toasts the result and refreshes the term lists. */
function ExtractWatcher({ jobId, onDone }: { jobId: string; onDone: () => void }) {
  const job = useJob(jobId, 1500);
  const qc = useQueryClient();
  const { message } = App.useApp();
  const state = job.data?.state;
  useEffect(() => {
    if (!state || state === "queued" || state === "running") return;
    if (state === "succeeded") {
      const r = job.data?.result ?? {};
      message.success(`抽取完成：新增 ${fmt(Number(r.created ?? 0))} 条草稿，跳过 ${fmt(Number(r.skipped ?? 0))} 条`);
      void qc.invalidateQueries({ queryKey: ["kb-terms"] });
    } else if (state === "failed") message.error(`抽取失败：${job.data?.error?.message ?? ""}`);
    onDone();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);
  return (
    <span className="tag t-run">
      <span className="spin" style={{ width: 9, height: 9 }} />
      抽取中{job.data?.progress.total ? ` ${fmt(job.data.progress.done)} / ${fmt(job.data.progress.total)}` : ""}
    </span>
  );
}

export function useTermExport(projectId: string) {
  const { message } = App.useApp();
  const jobCreated = useJobCreated();
  return useMutation({
    mutationFn: (format: "csv" | "xlsx" | "tbx") => api.post<Job>(`/projects/${projectId}/kb/terms/export`, { format }),
    onSuccess: () => {
      jobCreated(projectId);
      message.success(
        <span>
          已创建导出任务，<Link to={`/p/${projectId}/jobs`}>查看任务</Link>
        </span>,
      );
    },
    onError: (e) => message.error(errorText(e)),
  });
}

/* ---------- tab ---------- */

export default function TermsTab({
  projectId,
  editable,
  docs,
  openTermId,
  initialQ,
  onOpenTerm,
}: {
  projectId: string;
  editable: boolean;
  docs: KbDocument[];
  openTermId: string | null;
  initialQ: string;
  onOpenTerm: (id: string | null) => void;
}) {
  const [q, setQ] = useState(initialQ);
  const [status, setStatus] = useState<string>("");
  const [language, setLanguage] = useState<string | undefined>();
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractJob, setExtractJob] = useState<string | null>(null);
  const [current, setCurrent] = useState<Term | null>(null);
  const jobCreated = useJobCreated();
  const exportJob = useTermExport(projectId);
  const dq = useDebounced(q.trim(), 300);
  useEffect(() => setQ(initialQ), [initialQ]);
  useEffect(() => setPage(1), [dq, status, language]);
  const terms = useTerms(projectId, { q: dq, status: status || undefined, language, page, page_size: PAGE });
  const patch = useTermPatch();
  const items = terms.data?.items ?? [];

  // Open the term named in the URL once it is in the list.
  useEffect(() => {
    if (!openTermId) return setCurrent(null);
    const t = items.find((x) => x.id === openTermId);
    if (t) setCurrent(t);
  }, [openTermId, items]);

  return (
    <section className="card">
      <div className="card-head" style={{ flexWrap: "wrap", gap: 8, paddingTop: 10, paddingBottom: 10 }}>
        <input className="input s" style={{ width: 200 }} placeholder="筛选术语" aria-label="筛选术语" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="seg-mini" role="tablist" aria-label="状态">
          {[
            ["", "全部"],
            ["draft", "草稿"],
            ["confirmed", "已确认"],
          ].map(([v, l]) => (
            <button key={v} type="button" role="tab" aria-selected={status === v} onClick={() => setStatus(v)}>
              {l}
            </button>
          ))}
        </div>
        <Select size="small" allowClear placeholder="语言" style={{ width: 110 }} value={language} onChange={setLanguage} options={languageOptions} aria-label="语言" />
        <div className="grow" />
        {extractJob && <ExtractWatcher jobId={extractJob} onDone={() => setExtractJob(null)} />}
        {editable && (
          <>
            <button className="btn s" type="button" onClick={() => setExtracting(true)} disabled={!!extractJob}>
              <Icon name="spark" size={14} />
              抽取
            </button>
            <button className="btn s" type="button" onClick={() => setCreating(true)}>
              <Icon name="plus" size={14} />
              新建术语
            </button>
          </>
        )}
        <Dropdown
          trigger={["click"]}
          menu={{
            items: [
              { key: "csv", label: "CSV" },
              { key: "xlsx", label: "XLSX" },
              { key: "tbx", label: "TBX" },
            ],
            onClick: ({ key }) => exportJob.mutate(key as "csv" | "xlsx" | "tbx"),
          }}
        >
          <button className="btn s" type="button" disabled={exportJob.isPending}>
            <Icon name="download" size={14} />
            导出
          </button>
        </Dropdown>
      </div>
      <ErrorAlert error={terms.error} style={{ margin: 16 }} />
      <Table<Term>
        rowKey="id"
        size="middle"
        loading={terms.isPending}
        dataSource={items}
        locale={{ emptyText: dq || status || language ? "没有匹配的术语" : "还没有术语，可新建或从语料、文献抽取" }}
        onRow={(t) => ({ onClick: () => onOpenTerm(t.id), style: { cursor: "pointer" } })}
        pagination={
          (terms.data?.total ?? 0) > PAGE
            ? { current: page, pageSize: PAGE, total: terms.data?.total, showSizeChanger: false, onChange: setPage }
            : false
        }
        columns={[
          {
            title: "术语",
            key: "term",
            render: (_, t) => (
              <span className="row" style={{ gap: 6 }}>
                <b style={{ fontWeight: 600 }}>{t.term}</b>
                <span className="mono small muted">{t.language}</span>
              </span>
            ),
          },
          {
            title: "译名",
            key: "tr",
            render: (_, t) => (
              <span className="row wrap" style={{ gap: 4 }}>
                {(t.translations ?? []).slice(0, 3).map((x, i) => (
                  <span key={i} className={`tag ${i ? "t-line" : "t-accent-line"}`}>
                    {x.text}
                  </span>
                ))}
              </span>
            ),
          },
          { title: "领域", dataIndex: "domain", key: "domain" },
          { title: "来源", key: "source", render: (_, t) => termSourceLabels[t.source] ?? t.source },
          { title: "例句", key: "ex", align: "right", className: "num-col", render: (_, t) => fmt(t.examples?.length ?? 0) },
          { title: "更新", key: "updated", className: "num-col", render: (_, t) => <span className="small muted">{fmtShortTime(t.updated_at)}</span> },
          {
            title: "状态",
            key: "status",
            render: (_, t) => (
              <span className="row" style={{ gap: 6 }}>
                <TermStatusTag status={t.status} />
                {editable && t.status === "draft" && (
                  <button
                    className="btn xs"
                    type="button"
                    disabled={patch.isPending}
                    onClick={(e) => {
                      e.stopPropagation();
                      patch.mutate({ id: t.id, body: { status: "confirmed" } });
                    }}
                  >
                    确认
                  </button>
                )}
              </span>
            ),
          },
        ]}
      />
      <TermDrawer term={current} editable={editable} onClose={() => onOpenTerm(null)} onChange={setCurrent} />
      <NewTermDialog projectId={projectId} open={creating} onClose={() => setCreating(false)} onCreated={(t) => { setCurrent(t); onOpenTerm(t.id); }} />
      <ExtractDialog
        projectId={projectId}
        open={extracting}
        docs={docs}
        onClose={() => setExtracting(false)}
        onStarted={(job) => {
          setExtractJob(job.id);
          jobCreated(projectId);
        }}
      />
    </section>
  );
}
