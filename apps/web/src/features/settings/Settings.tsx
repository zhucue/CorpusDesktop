import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Form, Input, Popconfirm, Select, Table } from "antd";
import { useState } from "react";
import { ApiError, MAX_PAGE_SIZE, api, errorText, roleLabels, type Member, type Page, type Role, type User } from "../../api";
import { Avatar, ErrorAlert } from "../../components/common";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/shell/AppShell";
import { useMe, useProject, useProjectId } from "../../lib/data";
import "./settings.css";

const roleOptions = (Object.keys(roleLabels) as Role[]).map((r) => ({ value: r, label: roleLabels[r] }));

// What each role may do, per the API permission rules (P1/P2 contracts).
const MATRIX: [string, boolean[]][] = [
  ["检索、统计、导出", [true, true, true, true]],
  ["钉住证据", [true, true, true, false]],
  ["上传语料、建子库", [true, true, false, false]],
  ["管理成员", [true, false, false, false]],
];

export default function Settings() {
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
      let user: User;
      try {
        user = await api.get<User>("/users", { email: email.trim() });
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) throw new Error("邮箱不存在");
        throw e;
      }
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
    <>
      <PageHeader title="项目设置" crumbs={1} />
      <div className="content">
        <div className="settings-grid">
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
        </div>
      </div>
    </>
  );
}
