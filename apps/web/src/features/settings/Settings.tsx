import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Form, Input, Modal, Popconfirm, Select, Spin, Table } from "antd";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { MAX_PAGE_SIZE, api, errorText, roleLabels, type AuditEntry, type DeletedProject, type Member, type Page, type Project, type Role, type User } from "../../api";
import { Avatar, ErrorAlert, RelTime } from "../../components/common";
import { Icon, type IconName } from "../../components/Icon";
import { PageHeader } from "../../components/shell/AppShell";
import { listOf, useMe, useProject, useProjectId } from "../../lib/data";
import { fmt } from "../../lib/format";
import { LlmUsageCard, PasswordCard, PrivacyCard } from "./AccountPanels";
import { AdminAudit, AdminFeedback, AdminJobs, AdminProjects, AdminSystemPanel, AdminUsage } from "./AdminPanels";
import { AuditTable } from "./audit";
import { MAX_PROJECT_NAME } from "./project";
import Users from "./Users";
import "./settings.css";

/** GET /projects/{id}/usage: what deleting the project removes. */
interface ProjectUsage {
  corpora: number;
  layers: number;
  notes: number;
  kb_documents: number;
  terms: number;
  members: number;
}

const roleOptions = (Object.keys(roleLabels) as Role[]).map((r) => ({ value: r, label: roleLabels[r] }));

// What each role may do, per the API permission rules (contracts p1–p5: READ / ANNOTATE / WRITE / owner).
const MATRIX: [string, boolean[]][] = [
  ["检索、统计、导出", [true, true, true, true]],
  ["钉住证据", [true, true, true, false]],
  ["标注校对", [true, true, true, false]],
  ["编辑知识库", [true, true, true, false]],
  ["上传语料、建子库", [true, true, false, false]],
  ["建标注层、仲裁", [true, true, false, false]],
  ["管理成员", [true, false, false, false]],
];

const USAGE_LABELS: [keyof ProjectUsage, string, string][] = [
  ["corpora", "语料库", "个"],
  ["layers", "标注层", "个"],
  ["notes", "笔记", "篇"],
  ["kb_documents", "文献与规范", "篇"],
  ["terms", "术语", "条"],
  ["members", "成员", "人"],
];

/** Name (owner renames), 新建项目, and delete with the counts of what goes with the project. */
function ProjectCard({ project, isOwner }: { project: Project; isOwner: boolean }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [name, setName] = useState(project.name);
  const [deleting, setDeleting] = useState(false);
  const usage = useQuery({
    queryKey: ["project-usage", project.id],
    queryFn: () => api.get<ProjectUsage>(`/projects/${project.id}/usage`),
    enabled: deleting,
  });
  const rename = useMutation({
    mutationFn: () => api.patch<Project>(`/projects/${project.id}`, { name: name.trim() }),
    onSuccess: (p) => {
      qc.setQueryData(["project", project.id], p);
      void qc.invalidateQueries({ queryKey: ["projects"] });
      message.success("已改名");
    },
    onError: (e) => message.error(errorText(e)),
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/projects/${project.id}`),
    onSuccess: () => {
      try {
        localStorage.removeItem("last-project");
      } catch {
        /* storage unavailable */
      }
      qc.clear();
      message.success(`已删除项目「${project.name}」`);
      navigate("/", { replace: true });
    },
  });
  const changed = name.trim() !== project.name && name.trim().length > 0;
  return (
    <section className="card" aria-label="项目">
      <div className="card-head">
        <h2 className="grow">项目</h2>
        <Link className="btn s" to="/onboarding">
          <Icon name="plus" size={14} />
          新建项目
        </Link>
      </div>
      <form
        className="proj-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (changed) rename.mutate();
        }}
      >
        <div className="field">
          <label htmlFor="proj-name" className="row between">
            项目名称
            {isOwner && (
              <span className="small muted num">
                {Array.from(name).length} / {MAX_PROJECT_NAME}
              </span>
            )}
          </label>
          <div className="row">
            <Input id="proj-name" value={name} maxLength={MAX_PROJECT_NAME} disabled={!isOwner} onChange={(e) => setName(e.target.value)} />
            {isOwner && (
              <button className="btn p" type="submit" disabled={!changed || rename.isPending}>
                保存
              </button>
            )}
          </div>
        </div>
      </form>
      {isOwner && (
        <div className="danger-zone">
          <div className="grow" />
          <button className="btn s danger" type="button" onClick={() => setDeleting(true)}>
            <Icon name="trash" size={14} />
            删除项目
          </button>
        </div>
      )}
      <Modal
        title={`删除项目「${project.name}」？`}
        open={deleting}
        onCancel={() => setDeleting(false)}
        okText="删除"
        cancelText="取消"
        okButtonProps={{ danger: true, loading: remove.isPending, disabled: !usage.data }}
        onOk={() => remove.mutate()}
        destroyOnHidden
        width={440}
      >
        <div className="col" style={{ gap: 12 }}>
          <span className="sm">以下内容会一并删除，7 天内可由负责人或管理员恢复：</span>
          {usage.isPending ? (
            <Spin />
          ) : (
            usage.data && (
              <table className="tbl mid">
                <tbody>
                  {USAGE_LABELS.map(([k, label, unit]) => (
                    <tr key={k}>
                      <td className="sm">{label}</td>
                      <td className="r num">
                        {fmt(usage.data[k])} {unit}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          )}
          <ErrorAlert error={usage.error ?? remove.error} />
        </div>
      </Modal>
    </section>
  );
}

/** GET /me/deleted-projects: own projects deleted in the last 7 days, with 恢复. Hidden when there are none. */
function DeletedProjects() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const deleted = useQuery({
    queryKey: ["deleted-projects"],
    queryFn: () => api.get<Page<DeletedProject> | DeletedProject[]>("/me/deleted-projects"),
  });
  const restore = useMutation({
    mutationFn: (p: DeletedProject) => api.post<Project>(`/projects/${p.id}/restore`),
    onSuccess: (_, p) => {
      void qc.invalidateQueries({ queryKey: ["deleted-projects"] });
      void qc.invalidateQueries({ queryKey: ["projects"] });
      message.success(`已恢复项目「${p.name}」`);
    },
    onError: (e) => message.error(errorText(e)),
  });
  const items = listOf(deleted.data);
  if (!deleted.error && items.length === 0) return null;
  return (
    <section className="card" aria-label="最近删除">
      <div className="card-head">
        <h2 className="grow">最近删除</h2>
      </div>
      <ErrorAlert error={deleted.error} style={{ margin: 16 }} />
      {items.length > 0 && (
        <table className="tbl mid">
          <tbody>
            {items.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td>
                  <RelTime at={p.deleted_at} />
                </td>
                <td className="r">
                  <button className="btn xs" type="button" disabled={restore.isPending} onClick={() => restore.mutate(p)}>
                    <Icon name="restore" size={14} />
                    恢复
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

const AUDIT_PAGE = 20;

/** GET /projects/{id}/audit: the project's own entries, for its owners. */
function ProjectAudit({ projectId }: { projectId: string }) {
  const [page, setPage] = useState(1);
  const audit = useQuery({
    queryKey: ["project-audit", projectId, page],
    queryFn: () => api.get<Page<AuditEntry>>(`/projects/${projectId}/audit`, { page, page_size: AUDIT_PAGE }),
  });
  return (
    <section className="card span-2" aria-label="项目审计">
      <div className="card-head">
        <h2 className="grow">审计</h2>
        <span className="small muted num">{fmt(audit.data?.total ?? 0)} 条</span>
      </div>
      <ErrorAlert error={audit.error} style={{ margin: 16 }} />
      <AuditTable items={audit.data?.items} total={audit.data?.total ?? 0} page={page} pageSize={AUDIT_PAGE} loading={audit.isPending} onPage={setPage} />
    </section>
  );
}

function ProjectSettings() {
  const projectId = useProjectId();
  const project = useProject();
  const me = useMe();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [form] = Form.useForm<{ email: string; role: Role }>();
  const [added, setAdded] = useState<string | null>(null);
  const isOwner = project.data?.role === "owner";

  const members = useQuery({
    queryKey: ["members", projectId],
    queryFn: () => api.get<Page<Member>>(`/projects/${projectId}/members`, { page_size: MAX_PAGE_SIZE }),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["members", projectId] });

  const setRole = useMutation({
    mutationFn: ({ user_id, role }: { user_id: string; role: Role }) => api.put<Member>(`/projects/${projectId}/members/${encodeURIComponent(user_id)}`, { role }),
    onSuccess: refresh,
    onError: (e) => message.error(errorText(e)),
  });
  const addMember = useMutation({
    mutationFn: async ({ email, role }: { email: string; role: Role }) => {
      const found = await api.get<{ items: Pick<User, "id" | "email" | "display_name">[] }>("/users", { email: email.trim(), project_id: projectId });
      const user = found.items[0];
      if (!user) throw new Error("邮箱不存在");
      return api.put<Member>(`/projects/${projectId}/members/${encodeURIComponent(user.id)}`, { role });
    },
    onSuccess: (m) => {
      form.resetFields();
      setAdded(m.user_id);
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (userId: string) => api.del(`/projects/${projectId}/members/${userId}`),
    onSuccess: refresh,
    onError: (e) => message.error(errorText(e)),
  });

  return (
    <div className="settings-grid">
      {project.data && <ProjectCard key={project.data.id} project={project.data} isOwner={isOwner} />}
      <div>
        <DeletedProjects />
      </div>
      <section className="card">
        <div className="card-head">
          <h2 className="grow">成员</h2>
          <span className="small muted num">{members.data?.total ?? 0} 人</span>
        </div>
        {isOwner && (
          <div className="add-member">
            <Form form={form} layout="inline" onFinish={addMember.mutate} initialValues={{ role: "viewer" }}>
              <Form.Item name="email" rules={[{ required: true, type: "email", message: "请输入邮箱" }]}>
                <Input placeholder="邮箱" style={{ width: 280 }} prefix={<Icon name="mail" size={14} />} />
              </Form.Item>
              <Form.Item name="role">
                <Select options={roleOptions} style={{ width: 110 }} />
              </Form.Item>
              <button className="btn p" type="submit" disabled={addMember.isPending}>
                <Icon name="plus" size={14} />
                添加
              </button>
            </Form>
            <ErrorAlert error={addMember.error} style={{ marginTop: 10 }} />
          </div>
        )}
        <ErrorAlert error={members.error} style={{ margin: 16 }} />
        <Table<Member>
          rowKey="user_id"
          loading={members.isPending}
          dataSource={members.data?.items}
          pagination={false}
          rowClassName={(m) => (m.user_id === added ? "row-new" : "")}
          locale={{ emptyText: "暂无成员" }}
          columns={[
            {
              title: "成员",
              render: (_, m) => (
                <span className="row">
                  <Avatar name={m.email} />
                  <span>{m.email}</span>
                  {m.user_id === me.data?.id && <span className="tag t-gray">我</span>}
                </span>
              ),
            },
            {
              title: "角色",
              width: 150,
              render: (_, m) =>
                isOwner && m.user_id !== me.data?.id ? (
                  <Select size="small" value={m.role} options={roleOptions} style={{ width: 110 }} onChange={(role) => setRole.mutate({ user_id: m.user_id, role })} />
                ) : (
                  (roleLabels[m.role] ?? m.role)
                ),
            },
            {
              title: "",
              width: 80,
              render: (_, m) =>
                isOwner &&
                m.user_id !== me.data?.id && (
                  <Popconfirm title={`移除 ${m.email}？`} okText="移除" cancelText="取消" onConfirm={() => remove.mutate(m.user_id)}>
                    <button className="btn xs ghost danger" type="button">
                      移除
                    </button>
                  </Popconfirm>
                ),
            },
          ]}
        />
      </section>
      <section className="card" aria-label="角色权限">
        <div className="card-head">
          <h2>角色权限</h2>
        </div>
        <table className="tbl mid">
          <thead>
            <tr>
              <th />
              {(Object.keys(roleLabels) as Role[]).map((r) => (
                <th key={r} style={{ textAlign: "center" }}>
                  {roleLabels[r]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {MATRIX.map(([label, flags]) => (
              <tr key={label}>
                <td className="sm">{label}</td>
                {flags.map((f, i) => (
                  <td key={i} style={{ textAlign: "center", color: f ? "var(--success)" : "var(--text-4)" }}>
                    {f ? <Icon name="check" size={14} label="可" /> : "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {isOwner && <ProjectAudit projectId={projectId} />}
    </div>
  );
}

type Tab = "project" | "account" | "privacy" | "admin";
type AdminTab = "users" | "projects" | "jobs" | "usage" | "audit" | "feedback" | "system";

const ADMIN_TABS: [AdminTab, string, IconName][] = [
  ["users", "用户", "users"],
  ["projects", "项目", "folder"],
  ["jobs", "任务", "listchecks"],
  ["usage", "用量", "coins"],
  ["audit", "审计", "scrolltext"],
  ["feedback", "反馈", "feedback"],
  ["system", "系统", "server"],
];

/** 管理 (platform admins): users and the cross-project views; the sub tab is kept in `?admin=`. */
function Admin({ sub, onSub }: { sub: AdminTab; onSub: (t: AdminTab) => void }) {
  return (
    <>
      <div className="set-tabs sub" role="tablist" aria-label="管理">
        {ADMIN_TABS.map(([k, label, icon]) => (
          <button key={k} type="button" role="tab" aria-selected={sub === k} onClick={() => onSub(k)}>
            <Icon name={icon} size={14} /> {label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {sub === "users" && <Users />}
        {sub === "projects" && <AdminProjects />}
        {sub === "jobs" && <AdminJobs />}
        {sub === "usage" && <AdminUsage />}
        {sub === "audit" && <AdminAudit />}
        {sub === "feedback" && <AdminFeedback />}
        {sub === "system" && <AdminSystemPanel />}
      </div>
    </>
  );
}

export default function Settings() {
  const me = useMe();
  const [params, setParams] = useSearchParams();
  const tabs: [Tab, string, IconName][] = [
    ["project", "项目", "folder"],
    ["account", "账号", "key"],
    ["privacy", "数据与隐私", "shield"],
    ...(me.data?.is_admin ? ([["admin", "管理", "shield"]] as [Tab, string, IconName][]) : []),
  ];
  // ?tab=users (P7 links) opens 管理 · 用户
  const raw = params.get("tab");
  const asked = (raw === "users" ? "admin" : raw) as Tab | null;
  const tab = tabs.some(([k]) => k === asked) ? (asked as Tab) : "project";
  const askedSub = (raw === "users" ? "users" : params.get("admin")) as AdminTab | null;
  const sub = ADMIN_TABS.some(([k]) => k === askedSub) ? (askedSub as AdminTab) : "users";
  const go = (t: Tab, admin?: AdminTab) =>
    setParams(
      (p) => {
        p.set("tab", t);
        if (admin) p.set("admin", admin);
        else p.delete("admin");
        return p;
      },
      { replace: true },
    );
  return (
    <>
      <PageHeader title="设置" crumbs={1} />
      <div className="content">
        <div className="set-tabs" role="tablist" aria-label="设置">
          {tabs.map(([k, label, icon]) => (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={tab === k}
              onClick={() => go(k)}
            >
              <Icon name={icon} size={14} /> {label}
            </button>
          ))}
        </div>
        <div role="tabpanel">
          {tab === "project" && <ProjectSettings />}
          {tab === "account" && (
            <div className="settings-narrow">
              <PasswordCard />
              <LlmUsageCard />
            </div>
          )}
          {tab === "privacy" && (
            <div className="settings-narrow">
              <PrivacyCard />
            </div>
          )}
          {tab === "admin" && <Admin sub={sub} onSub={(t) => go("admin", t)} />}
        </div>
      </div>
    </>
  );
}
