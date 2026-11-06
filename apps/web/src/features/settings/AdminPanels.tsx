import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Input, Modal, Popconfirm, Segmented, Select, Spin, Table } from "antd";
import { useDeferredValue, useState } from "react";
import {
  MAX_PAGE_SIZE,
  api,
  errorText,
  type AdminJob,
  type AdminProject,
  type AdminSystem,
  type AdminUser,
  type AuditEntry,
  type FeedbackItem,
  type FeedbackStatus,
  type JobState,
  type LlmUsageReport,
  type Page,
} from "../../api";
import { ErrorAlert, JobStateTag, RelTime, jobStateView } from "../../components/common";
import { jobKindLabels } from "../../components/global/TaskTray";
import { Icon } from "../../components/Icon";
import { isActiveJob, pageOf } from "../../lib/data";
import { fmt, fmtBytes, fmtTime } from "../../lib/format";
import { AuditTable, auditActionLabels } from "./audit";

const PAGE_SIZE = 50;

/* ---------- 项目 ---------- */

function OwnerDialog({ project, onClose }: { project: AdminProject | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [q, setQ] = useState("");
  const query = useDeferredValue(q.trim());
  const [userId, setUserId] = useState<string | null>(null);
  const users = useQuery({
    queryKey: ["admin-users", query],
    queryFn: () => api.get<Page<AdminUser>>("/admin/users", { q: query, page_size: MAX_PAGE_SIZE }),
    enabled: !!project,
    placeholderData: keepPreviousData,
  });
  const save = useMutation({
    mutationFn: () => api.post(`/admin/projects/${project!.id}/owner`, { user_id: userId }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["admin-projects"] });
      message.success("已改派负责人");
      setUserId(null);
      onClose();
    },
  });
  const options = (users.data?.items ?? [])
    .filter((u) => !u.disabled_at && u.id !== project?.owner?.id)
    .map((u) => ({ value: u.id, label: u.display_name ? `${u.display_name} · ${u.email}` : u.email }));
  return (
    <Modal
      title={project ? `改派「${project.name}」的负责人` : ""}
      open={!!project}
      onCancel={() => {
        save.reset();
        setUserId(null);
        onClose();
      }}
      okText="改派"
      cancelText="取消"
      okButtonProps={{ disabled: !userId, loading: save.isPending }}
      onOk={() => save.mutate()}
      destroyOnHidden
      width={440}
    >
      <div className="col" style={{ gap: 12 }}>
        <span className="sm">当前负责人：{project?.owner?.email ?? "无"}；改派后原负责人改为编辑者。</span>
        <Select
          aria-label="新负责人"
          showSearch
          filterOption={false}
          onSearch={setQ}
          value={userId ?? undefined}
          onChange={setUserId}
          options={options}
          loading={users.isFetching}
          placeholder="邮箱或姓名"
          notFoundContent={users.isPending ? <Spin size="small" /> : "没有匹配的账号"}
        />
        <ErrorAlert error={save.error} />
      </div>
    </Modal>
  );
}

export function AdminProjects() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [q, setQ] = useState("");
  const query = useDeferredValue(q.trim());
  const [deleted, setDeleted] = useState(false);
  const [owning, setOwning] = useState<AdminProject | null>(null);
  const projects = useQuery({
    queryKey: ["admin-projects", query, deleted],
    queryFn: () => api.get<Page<AdminProject>>("/admin/projects", { q: query, deleted: deleted ? 1 : 0, page_size: MAX_PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const restore = useMutation({
    mutationFn: (p: AdminProject) => api.post(`/projects/${p.id}/restore`),
    onSuccess: (_, p) => {
      void qc.invalidateQueries({ queryKey: ["admin-projects"] });
      void qc.invalidateQueries({ queryKey: ["projects"] });
      message.success(`已恢复项目「${p.name}」`);
    },
    onError: (e) => message.error(errorText(e)),
  });
  return (
    <section className="card" aria-label="全部项目">
      <div className="card-head">
        <h2 className="grow">项目</h2>
        <span className="small muted num">{fmt(projects.data?.total ?? 0)} 个</span>
        <Segmented
          size="small"
          value={deleted ? "deleted" : "live"}
          onChange={(v) => setDeleted(v === "deleted")}
          options={[
            { value: "live", label: "使用中" },
            { value: "deleted", label: "已删除" },
          ]}
        />
        <Input
          allowClear
          size="small"
          placeholder="项目名或负责人邮箱"
          prefix={<Icon name="search" size={14} />}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ width: 200 }}
        />
      </div>
      <ErrorAlert error={projects.error} style={{ margin: 16 }} />
      <Table<AdminProject>
        rowKey="id"
        loading={projects.isPending}
        dataSource={projects.data?.items}
        pagination={false}
        locale={{ emptyText: query ? "没有匹配的项目" : deleted ? "没有已删除的项目" : "暂无项目" }}
        scroll={{ x: 900 }}
        columns={[
          { title: "项目", dataIndex: "name" },
          { title: "负责人", width: 200, render: (_, p) => p.owner?.email ?? <span className="muted">—</span> },
          { title: "成员", width: 64, align: "right", render: (_, p) => <span className="num">{fmt(p.members)}</span> },
          { title: "语料库", width: 72, align: "right", render: (_, p) => <span className="num">{fmt(p.corpora)}</span> },
          { title: "标注层", width: 72, align: "right", render: (_, p) => <span className="num">{fmt(p.layers)}</span> },
          { title: "文献", width: 64, align: "right", render: (_, p) => <span className="num">{fmt(p.kb_documents)}</span> },
          { title: "占用", width: 90, align: "right", render: (_, p) => <span className="num">{fmtBytes(p.disk_bytes)}</span> },
          deleted
            ? { title: "删除于", width: 110, render: (_, p) => <RelTime at={p.deleted_at} /> }
            : { title: "创建", width: 110, render: (_, p) => <RelTime at={p.created_at} /> },
          {
            title: "",
            width: 110,
            render: (_, p) =>
              p.deleted_at ? (
                <Popconfirm title={`恢复项目「${p.name}」？`} okText="恢复" cancelText="取消" onConfirm={() => restore.mutate(p)}>
                  <button className="btn xs" type="button" disabled={restore.isPending}>
                    <Icon name="restore" size={14} />
                    恢复
                  </button>
                </Popconfirm>
              ) : (
                <button className="btn xs ghost" type="button" onClick={() => setOwning(p)}>
                  改派负责人
                </button>
              ),
          },
        ]}
      />
      <OwnerDialog project={owning} onClose={() => setOwning(null)} />
    </section>
  );
}

/* ---------- 任务 ---------- */

const stateOptions = [{ value: "", label: "全部状态" }, ...(Object.keys(jobStateView) as JobState[]).map((s) => ({ value: s, label: jobStateView[s].label }))];
const kindOptions = [{ value: "", label: "全部类型" }, ...Object.entries(jobKindLabels).map(([k, label]) => ({ value: k, label }))];

export function AdminJobs() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [state, setState] = useState("");
  const [kind, setKind] = useState("");
  const [page, setPage] = useState(1);
  const jobs = useQuery({
    queryKey: ["admin-jobs", state, kind, page],
    queryFn: () => api.get<Page<AdminJob>>("/admin/jobs", { state, kind, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items.some(isActiveJob) ? 3000 : false),
  });
  const cancel = useMutation({
    mutationFn: (j: AdminJob) => api.post(`/jobs/${j.id}/cancel`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["admin-jobs"] });
      message.success("已取消");
    },
    onError: (e) => message.error(errorText(e)),
  });
  const total = jobs.data?.total ?? 0;
  return (
    <section className="card" aria-label="全部任务">
      <div className="card-head">
        <h2 className="grow">任务</h2>
        <span className="small muted num">{fmt(total)} 个</span>
        <Select
          size="small"
          aria-label="状态"
          value={state}
          options={stateOptions}
          onChange={(v) => {
            setState(v);
            setPage(1);
          }}
          style={{ width: 110 }}
        />
        <Select
          size="small"
          aria-label="类型"
          value={kind}
          options={kindOptions}
          onChange={(v) => {
            setKind(v);
            setPage(1);
          }}
          style={{ width: 120 }}
        />
      </div>
      <ErrorAlert error={jobs.error} style={{ margin: 16 }} />
      <Table<AdminJob>
        rowKey="id"
        loading={jobs.isPending}
        dataSource={jobs.data?.items}
        pagination={total > PAGE_SIZE ? { current: page, pageSize: PAGE_SIZE, total, showSizeChanger: false, onChange: setPage } : false}
        locale={{ emptyText: "暂无任务" }}
        scroll={{ x: 900 }}
        columns={[
          { title: "类型", width: 90, render: (_, j) => jobKindLabels[j.kind] ?? j.kind },
          { title: "对象", render: (_, j) => <span className="ellipsis">{j.summary ?? ""}</span> },
          {
            title: "项目",
            width: 150,
            render: (_, j) => (j.project_id ? (j.project_name ?? <span className="mono small">{j.project_id.slice(0, 8)}</span>) : <span className="tag t-gray">内置</span>),
          },
          { title: "发起人", width: 180, render: (_, j) => j.owner_email ?? <span className="muted">—</span> },
          { title: "状态", width: 90, render: (_, j) => <JobStateTag state={j.state} /> },
          {
            title: "错误",
            width: 200,
            render: (_, j) => (j.error ? <span className="err-text small">{j.error.message}</span> : null),
          },
          { title: "创建", width: 100, render: (_, j) => <RelTime at={j.created_at} /> },
          {
            title: "",
            width: 70,
            render: (_, j) =>
              isActiveJob(j) && (
                <Popconfirm title="取消该任务？" okText="取消任务" cancelText="返回" okButtonProps={{ danger: true }} onConfirm={() => cancel.mutate(j)}>
                  <button className="btn xs" type="button" disabled={cancel.isPending}>
                    取消
                  </button>
                </Popconfirm>
              ),
          },
        ]}
      />
    </section>
  );
}

/* ---------- 用量 ---------- */

function thisMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function AdminUsage() {
  const [group, setGroup] = useState<"user" | "project">("user");
  const [month, setMonth] = useState(thisMonth);
  const usage = useQuery({
    queryKey: ["admin-llm-usage", month, group],
    queryFn: () => api.get<LlmUsageReport>("/admin/llm-usage", { month, group }),
    enabled: /^\d{4}-\d{2}$/.test(month),
    placeholderData: keepPreviousData,
  });
  return (
    <section className="card" aria-label="模型用量">
      <div className="card-head">
        <h2 className="grow">模型用量</h2>
        <Segmented
          size="small"
          value={group}
          onChange={(v) => setGroup(v as "user" | "project")}
          options={[
            { value: "user", label: "按用户" },
            { value: "project", label: "按项目" },
          ]}
        />
        <Input size="small" type="month" aria-label="月份" value={month} onChange={(e) => setMonth(e.target.value)} style={{ width: 150 }} />
      </div>
      <ErrorAlert error={usage.error} style={{ margin: 16 }} />
      <Table
        rowKey="key"
        loading={usage.isPending}
        dataSource={usage.data?.items}
        pagination={false}
        locale={{ emptyText: "该月无用量" }}
        columns={[
          { title: group === "user" ? "用户" : "项目", render: (_, r) => r.name || <span className="mono small">{r.key}</span> },
          { title: "总 token", width: 140, align: "right", render: (_, r) => <span className="num">{fmt(r.total_tokens)}</span> },
          {
            title: "提示 / 生成",
            width: 200,
            align: "right",
            render: (_, r) => (
              <span className="num">
                {fmt(r.prompt_tokens)} / {fmt(r.completion_tokens)}
              </span>
            ),
          },
          { title: "调用次数", width: 100, align: "right", render: (_, r) => <span className="num">{fmt(r.calls)}</span> },
        ]}
      />
    </section>
  );
}

/* ---------- 审计 ---------- */

const actionOptions = [{ value: "", label: "全部操作" }, ...Object.entries(auditActionLabels).map(([value, label]) => ({ value, label }))];

/** Project names for the 审计 filter and column: without `deleted` the API lists live and deleted projects. */
function useProjectNames() {
  const all = useQuery({
    queryKey: ["admin-projects", "all"],
    queryFn: () => api.get<Page<AdminProject>>("/admin/projects", { page_size: MAX_PAGE_SIZE }),
  });
  return all.data?.items ?? [];
}

export function AdminAudit() {
  const [actor, setActor] = useState("");
  const actorQ = useDeferredValue(actor.trim());
  const [action, setAction] = useState("");
  const [projectId, setProjectId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const projects = useProjectNames();
  const names = new Map(projects.map((p) => [p.id, p.name]));
  const audit = useQuery({
    queryKey: ["admin-audit", actorQ, action, projectId, from, to, page],
    queryFn: () => api.get<Page<AuditEntry>>("/admin/audit", { actor: actorQ, action, project_id: projectId, from, to, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setPage(1);
  };
  return (
    <section className="card" aria-label="审计">
      <div className="card-head wrap">
        <h2 className="grow">审计</h2>
        <Input allowClear size="small" aria-label="操作人" placeholder="操作人邮箱" value={actor} onChange={(e) => reset(setActor)(e.target.value)} style={{ width: 170 }} />
        <Select size="small" aria-label="操作" value={action} options={actionOptions} onChange={reset(setAction)} style={{ width: 140 }} />
        <Select
          size="small"
          aria-label="项目"
          showSearch
          optionFilterProp="label"
          value={projectId}
          options={[{ value: "", label: "全部项目" }, ...projects.map((p) => ({ value: p.id, label: p.name }))]}
          onChange={reset(setProjectId)}
          style={{ width: 150 }}
        />
        <Input size="small" type="date" aria-label="起始日期" value={from} onChange={(e) => reset(setFrom)(e.target.value)} style={{ width: 140 }} />
        <span className="muted">至</span>
        <Input size="small" type="date" aria-label="结束日期" value={to} onChange={(e) => reset(setTo)(e.target.value)} style={{ width: 140 }} />
      </div>
      <ErrorAlert error={audit.error} style={{ margin: 16 }} />
      <AuditTable
        items={audit.data?.items}
        total={audit.data?.total ?? 0}
        page={page}
        pageSize={PAGE_SIZE}
        loading={audit.isPending}
        onPage={setPage}
        projectName={(e) => (e.project_id ? (e.project_name ?? names.get(e.project_id) ?? e.project_id.slice(0, 8)) : "")}
        showIp
      />
    </section>
  );
}

/* ---------- 反馈 ---------- */

function HandleDialog({ item, onClose }: { item: FeedbackItem; onClose: () => void }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [status, setStatus] = useState<FeedbackStatus>("done");
  const [note, setNote] = useState(item.admin_note ?? "");
  const save = useMutation({
    mutationFn: () => api.patch(`/admin/feedback/${item.id}`, { status, admin_note: note.trim() }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["admin-feedback"] });
      message.success(status === "done" ? "已标记处理" : "已保存");
      onClose();
    },
  });
  return (
    <Modal
      title="处理反馈"
      open
      onCancel={onClose}
      okText="保存"
      cancelText="取消"
      okButtonProps={{ loading: save.isPending }}
      onOk={() => save.mutate()}
      destroyOnHidden
      width={480}
    >
      <div className="col" style={{ gap: 12 }}>
        <div className="sm fb-text">{item.text}</div>
        <Segmented
          value={status}
          onChange={(v) => setStatus(v as FeedbackStatus)}
          options={[
            { value: "done", label: "已处理" },
            { value: "open", label: "未处理" },
          ]}
        />
        <div className="field">
          <label htmlFor="fb-note">备注</label>
          <Input.TextArea id="fb-note" rows={3} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <ErrorAlert error={save.error} />
      </div>
    </Modal>
  );
}

export function AdminFeedback() {
  const [status, setStatus] = useState<FeedbackStatus | "">("open");
  const [handling, setHandling] = useState<FeedbackItem | null>(null);
  const feedback = useQuery({
    queryKey: ["admin-feedback", status],
    queryFn: () => api.get<Page<FeedbackItem> | FeedbackItem[]>("/admin/feedback", { status, page_size: MAX_PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const data = feedback.data ? pageOf(feedback.data) : undefined;
  return (
    <section className="card" aria-label="反馈">
      <div className="card-head">
        <h2 className="grow">反馈</h2>
        <span className="small muted num">{fmt(data?.total ?? 0)} 条</span>
        <Segmented
          size="small"
          value={status}
          onChange={(v) => setStatus(v as FeedbackStatus | "")}
          options={[
            { value: "open", label: "未处理" },
            { value: "done", label: "已处理" },
            { value: "", label: "全部" },
          ]}
        />
      </div>
      <ErrorAlert error={feedback.error} style={{ margin: 16 }} />
      <Table<FeedbackItem>
        rowKey="id"
        loading={feedback.isPending}
        dataSource={data?.items}
        pagination={false}
        locale={{ emptyText: status === "open" ? "没有未处理的反馈" : "暂无反馈" }}
        scroll={{ x: 900 }}
        columns={[
          { title: "时间", width: 110, render: (_, f) => <RelTime at={f.created_at} /> },
          { title: "用户", width: 180, render: (_, f) => f.user?.email ?? <span className="muted">—</span> },
          {
            title: "页面",
            width: 180,
            render: (_, f) => (
              <span className="col" style={{ gap: 2 }}>
                <span className="mono small ellipsis">{f.page}</span>
                {f.app_version && <span className="small muted">版本 {f.app_version}</span>}
              </span>
            ),
          },
          { title: "内容", render: (_, f) => <span className="fb-text">{f.text}</span> },
          {
            title: "状态",
            width: 160,
            render: (_, f) => (
              <span className="col" style={{ gap: 2 }}>
                {f.status === "done" ? <span className="tag t-ok">已处理</span> : <span className="tag t-run">未处理</span>}
                {f.admin_note && <span className="small">{f.admin_note}</span>}
              </span>
            ),
          },
          {
            title: "",
            width: 70,
            render: (_, f) => (
              <button className="btn xs" type="button" onClick={() => setHandling(f)}>
                处理
              </button>
            ),
          },
        ]}
      />
      {handling && <HandleDialog key={handling.id} item={handling} onClose={() => setHandling(null)} />}
    </section>
  );
}

/* ---------- 系统 ---------- */

function modelText(m: AdminSystem["model"]): string {
  if (!m) return "未配置";
  if (typeof m === "string") return m;
  if (!m.configured) return "未配置";
  return [m.host, m.model_id].filter(Boolean).join(" · ") || "已配置";
}

function embedText(e: AdminSystem["embed"]): string {
  if (!e) return "未配置";
  if (typeof e === "string") return e;
  const where = e.mode === "remote" ? `远程 ${e.host ?? ""}`.trim() : "本机";
  return [where, e.model, e.ready ? null : "未就绪"].filter(Boolean).join(" · ");
}

export function AdminSystemPanel() {
  const sys = useQuery({ queryKey: ["admin-system"], queryFn: () => api.get<AdminSystem>("/admin/system"), refetchInterval: 30_000 });
  const d = sys.data;
  return (
    <section className="card" aria-label="系统">
      <div className="card-head">
        <h2 className="grow">系统</h2>
      </div>
      <ErrorAlert error={sys.error} style={{ margin: 16 }} />
      {sys.isPending ? (
        <Spin style={{ display: "block", margin: 24 }} />
      ) : (
        d && (
          <dl className="privacy">
            <dt>版本</dt>
            <dd className="mono">{d.version}</dd>
            <dt>对话模型</dt>
            <dd>{modelText(d.model)}</dd>
            <dt>向量模型</dt>
            <dd>{embedText(d.embed)}</dd>
            <dt>Worker</dt>
            <dd>
              {d.workers.length === 0 ? (
                <span className="err-text">没有 worker 上报</span>
              ) : (
                <table className="tbl mid">
                  <tbody>
                    {d.workers.map((w) => (
                      <tr key={w.id}>
                        <td className="mono small">{w.id}</td>
                        <td className="small">{Array.isArray(w.kinds) ? w.kinds.join("、") : (w.kinds ?? "")}</td>
                        <td>{w.last_seen ? <RelTime at={w.last_seen} /> : <span className="muted small">—</span>}</td>
                        <td>{w.healthy ? <span className="tag t-ok">正常</span> : <span className="tag t-err">无响应</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </dd>
            <dt>磁盘</dt>
            <dd>
              {d.disk?.total != null && d.disk.free != null ? (
                <span className="num">
                  <span className="mono">{d.disk.path}</span> 可用 {fmtBytes(d.disk.free)} / 共 {fmtBytes(d.disk.total)}
                </span>
              ) : (
                "—"
              )}
            </dd>
            <dt>数据目录</dt>
            <dd className="num">{fmtBytes(d.data_bytes)}</dd>
            <dt>检索缓存</dt>
            <dd className="num">{fmtBytes(d.search_cache_bytes)}</dd>
            <dt>最近备份</dt>
            <dd>{d.last_backup_at ? fmtTime(d.last_backup_at) : "未找到"}</dd>
          </dl>
        )
      )}
    </section>
  );
}
