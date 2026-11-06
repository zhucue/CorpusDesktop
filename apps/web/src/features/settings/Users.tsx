import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Checkbox, Input, Modal, Popconfirm, Table } from "antd";
import { useDeferredValue, useState } from "react";
import { MAX_PAGE_SIZE, api, errorText, type AdminUser, type Page } from "../../api";
import { Avatar, ErrorAlert, RelTime } from "../../components/common";
import { Icon } from "../../components/Icon";
import { useMe } from "../../lib/data";
import { fmt } from "../../lib/format";

/** Shown once after 新建 / 重置密码; the server never returns it again. */
interface Issued {
  email: string;
  password: string;
  created: boolean;
}

function IssuedPassword({ issued, onClose }: { issued: Issued | null; onClose: () => void }) {
  const { message } = App.useApp();
  async function copy() {
    if (!issued) return;
    try {
      await navigator.clipboard.writeText(issued.password);
      message.success("已复制");
    } catch {
      message.error("复制失败，请手动选择");
    }
  }
  return (
    <Modal
      title={issued?.created ? "账号已创建" : "密码已重置"}
      open={!!issued}
      onCancel={onClose}
      footer={
        <button className="btn p" type="button" onClick={onClose}>
          完成
        </button>
      }
      maskClosable={false}
      destroyOnHidden
      width={440}
    >
      {issued && (
        <div className="col" style={{ gap: 12 }}>
          <span className="sm">{issued.email} 的临时密码只显示这一次，登录后须修改：</span>
          <div className="row temp-pw">
            <code className="mono grow">{issued.password}</code>
            <button className="btn s" type="button" onClick={copy}>
              <Icon name="copy" size={14} />
              复制
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

function NewUserDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (i: Issued) => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [admin, setAdmin] = useState(false);
  const create = useMutation({
    mutationFn: () => api.post<{ user: AdminUser; temporary_password: string }>("/admin/users", { email: email.trim(), display_name: name.trim(), is_admin: admin }),
    onSuccess: (r) => {
      setEmail("");
      setName("");
      setAdmin(false);
      onCreated({ email: r.user.email, password: r.temporary_password, created: true });
    },
  });
  const ready = email.trim().includes("@") && name.trim().length > 0;
  return (
    <Modal
      title="新建账号"
      open={open}
      onCancel={() => {
        create.reset();
        onClose();
      }}
      okText="创建"
      cancelText="取消"
      okButtonProps={{ disabled: !ready, loading: create.isPending }}
      onOk={() => create.mutate()}
      destroyOnHidden
      width={440}
    >
      <div className="col" style={{ gap: 14 }}>
        <div className="field">
          <label htmlFor="nu-email">邮箱</label>
          <Input id="nu-email" type="email" value={email} maxLength={254} onChange={(e) => setEmail(e.target.value)} autoFocus />
        </div>
        <div className="field">
          <label htmlFor="nu-name">姓名</label>
          <Input id="nu-name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
        </div>
        <Checkbox checked={admin} onChange={(e) => setAdmin(e.target.checked)}>
          平台管理员
        </Checkbox>
        <ErrorAlert error={create.error} />
      </div>
    </Modal>
  );
}

/** 用户 tab (platform admins): list, search, create, reset password, disable / enable, admin flag. */
export default function Users() {
  const qc = useQueryClient();
  const me = useMe();
  const { message } = App.useApp();
  const [q, setQ] = useState("");
  const query = useDeferredValue(q.trim());
  const [creating, setCreating] = useState(false);
  const [issued, setIssued] = useState<Issued | null>(null);

  const users = useQuery({
    queryKey: ["admin-users", query],
    queryFn: () => api.get<Page<AdminUser>>("/admin/users", { q: query, page_size: MAX_PAGE_SIZE }),
    placeholderData: (prev) => prev,
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["admin-users"] });

  const act = useMutation({
    mutationFn: ({ user, action }: { user: AdminUser; action: "disable" | "enable" | "admin" | "unadmin" }) =>
      action === "admin" || action === "unadmin"
        ? api.post<AdminUser>(`/admin/users/${user.id}/admin`, { is_admin: action === "admin" })
        : api.post<AdminUser>(`/admin/users/${user.id}/${action}`),
    onSuccess: refresh,
    onError: (e) => message.error(errorText(e)),
  });
  const reset = useMutation({
    mutationFn: (user: AdminUser) => api.post<{ temporary_password: string }>(`/admin/users/${user.id}/reset-password`),
    onSuccess: (r, user) => setIssued({ email: user.email, password: r.temporary_password, created: false }),
    onError: (e) => message.error(errorText(e)),
  });

  const confirm = (title: string, ok: string, run: () => void, danger = true) => (
    <Popconfirm title={title} okText={ok} cancelText="取消" okButtonProps={{ danger }} onConfirm={run}>
      <button className={`btn xs ghost ${danger ? "danger" : ""}`} type="button">
        {ok}
      </button>
    </Popconfirm>
  );

  return (
    <section className="card" aria-label="用户">
      <div className="card-head">
        <h2 className="grow">用户</h2>
        <span className="small muted num">{fmt(users.data?.total ?? 0)} 人</span>
        <Input
          allowClear
          size="small"
          placeholder="邮箱或姓名"
          prefix={<Icon name="search" size={14} />}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ width: 200 }}
        />
        <button className="btn s p" type="button" onClick={() => setCreating(true)}>
          <Icon name="plus" size={14} />
          新建
        </button>
      </div>
      <ErrorAlert error={users.error} style={{ margin: 16 }} />
      <Table<AdminUser>
        rowKey="id"
        loading={users.isPending}
        dataSource={users.data?.items}
        pagination={false}
        locale={{ emptyText: query ? "没有匹配的账号" : "暂无账号" }}
        scroll={{ x: 860 }}
        columns={[
          {
            title: "邮箱",
            render: (_, u) => (
              <span className="row">
                <Avatar name={u.display_name || u.email} />
                <span>{u.email}</span>
                {u.id === me.data?.id && <span className="tag t-gray">我</span>}
              </span>
            ),
          },
          { title: "姓名", dataIndex: "display_name", width: 120 },
          {
            title: "管理员",
            width: 80,
            render: (_, u) => (u.is_admin ? <Icon name="check" size={14} label="是" /> : <span className="muted">—</span>),
          },
          {
            title: "状态",
            width: 80,
            render: (_, u) => (u.disabled_at ? <span className="tag t-err">已停用</span> : <span className="tag t-ok">正常</span>),
          },
          {
            title: "最近登录",
            width: 110,
            render: (_, u) => (u.last_login_at ? <RelTime at={u.last_login_at} /> : <span className="muted small">从未</span>),
          },
          { title: "项目", width: 64, align: "right", render: (_, u) => <span className="num">{fmt(u.projects)}</span> },
          {
            title: "",
            width: 250,
            render: (_, u) => {
              // own account: password via 账号 tab; no self-demotion or self-disable from this list
              if (u.id === me.data?.id) return null;
              return (
                <span className="row" style={{ gap: 2, justifyContent: "flex-end" }}>
                  {confirm(`重置 ${u.email} 的密码？其登录会话将失效。`, "重置密码", () => reset.mutate(u))}
                  {u.is_admin
                    ? confirm(`取消 ${u.email} 的管理员？`, "取消管理员", () => act.mutate({ user: u, action: "unadmin" }))
                    : confirm(`将 ${u.email} 设为管理员？`, "设为管理员", () => act.mutate({ user: u, action: "admin" }), false)}
                  {u.disabled_at
                    ? confirm(`启用 ${u.email}？`, "启用", () => act.mutate({ user: u, action: "enable" }), false)
                    : confirm(`停用 ${u.email}？其登录会话立即失效。`, "停用", () => act.mutate({ user: u, action: "disable" }))}
                </span>
              );
            },
          },
        ]}
      />
      <NewUserDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(i) => {
          setCreating(false);
          setIssued(i);
          refresh();
        }}
      />
      <IssuedPassword issued={issued} onClose={() => setIssued(null)} />
    </section>
  );
}
