import { Table } from "antd";
import type { AuditEntry } from "../../api";
import { fmtTime } from "../../lib/format";

/** Audit actions (contracts/p9.md §四) in Chinese. */
export const auditActionLabels: Record<string, string> = {
  login: "登录",
  login_failed: "登录失败",
  password_change: "修改密码",
  password_reset: "重置密码",
  user_create: "新建账号",
  user_disable: "停用账号",
  user_enable: "启用账号",
  admin_grant: "设为管理员",
  admin_revoke: "取消管理员",
  member_add: "添加成员",
  member_remove: "移除成员",
  member_role: "修改成员角色",
  project_delete: "删除项目",
  project_restore: "恢复项目",
  project_purge: "清除项目",
  project_owner: "改派负责人",
  corpus_delete: "删除语料库",
  document_delete: "删除文档",
  subcorpus_delete: "删除子库",
  layer_delete: "删除标注层",
  kb_document_delete: "删除文献",
  job_cancel_admin: "管理员取消任务",
};

const targetTypeLabels: Record<string, string> = {
  user: "账号",
  project: "项目",
  member: "成员",
  corpus: "语料库",
  document: "文档",
  subcorpus: "子库",
  layer: "标注层",
  kb_document: "文献",
  job: "任务",
};

export const actionLabel = (a: string) => auditActionLabels[a] ?? a;

/** Who did it; failed logins have no actor but keep the email in detail. */
function actorText(e: AuditEntry): string {
  if (e.actor_email) return e.actor_email;
  const email = e.detail?.email;
  return typeof email === "string" ? email : e.actor_id ? e.actor_id.slice(0, 8) : "系统";
}

function targetText(e: AuditEntry): string {
  const name = e.target_name || e.target_id || "";
  const type = e.target_type ? (targetTypeLabels[e.target_type] ?? e.target_type) : "";
  return [type, name].filter(Boolean).join(" · ");
}

export function AuditTable({
  items,
  total,
  page,
  pageSize,
  loading,
  onPage,
  projectName,
  showIp,
}: {
  items: AuditEntry[] | undefined;
  total: number;
  page: number;
  pageSize: number;
  loading: boolean;
  onPage: (p: number) => void;
  /** Admin view: the 项目 column; resolves a project id to its name. */
  projectName?: (e: AuditEntry) => string;
  showIp?: boolean;
}) {
  return (
    <Table<AuditEntry>
      rowKey="id"
      size="small"
      loading={loading}
      dataSource={items}
      locale={{ emptyText: "暂无记录" }}
      pagination={total > pageSize ? { current: page, pageSize, total, showSizeChanger: false, onChange: onPage } : false}
      scroll={{ x: 760 }}
      columns={[
        { title: "时间", width: 170, render: (_, e) => <span className="num small">{fmtTime(e.at)}</span> },
        { title: "操作人", width: 200, render: (_, e) => <span className="ellipsis">{actorText(e)}</span> },
        { title: "操作", width: 130, render: (_, e) => actionLabel(e.action) },
        { title: "对象", render: (_, e) => targetText(e) },
        ...(projectName ? [{ title: "项目", width: 160, render: (_: unknown, e: AuditEntry) => projectName(e) }] : []),
        ...(showIp ? [{ title: "IP", width: 130, render: (_: unknown, e: AuditEntry) => <span className="mono small">{e.ip ?? ""}</span> }] : []),
      ]}
    />
  );
}
