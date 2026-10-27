import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Form, Input, Popconfirm, Select, Table } from "antd";
import {
  ApiError,
  MAX_PAGE_SIZE,
  api,
  errorText,
  roleLabels,
  type Member,
  type Page,
  type Role,
  type User,
} from "../api";
import { useMe } from "../App";
import { useProject, useProjectId } from "../projects";

const roleOptions = (Object.keys(roleLabels) as Role[]).map((r) => ({ value: r, label: roleLabels[r] }));

export default function Settings() {
  const projectId = useProjectId();
  const project = useProject();
  const me = useMe();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [form] = Form.useForm<{ email: string; role: Role }>();
  const isOwner = project.data?.role === "owner";

  const members = useQuery({
    queryKey: ["members", projectId],
    queryFn: () => api.get<Page<Member>>(`/projects/${projectId}/members`, { page_size: MAX_PAGE_SIZE }),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["members", projectId] });

  const setRole = useMutation({
    mutationFn: ({ user_id, role }: { user_id: string; role: Role }) =>
      api.put<Member>(`/projects/${projectId}/members/${encodeURIComponent(user_id)}`, { role }),
    onSuccess: refresh,
    onError: (e) => message.error(errorText(e)),
  });
  const addMember = useMutation({
    mutationFn: async ({ email, role }: { email: string; role: Role }) => {
      let user: User;
      try {
        user = await api.get<User>("/users", { email: email.trim() });
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) throw new Error("用户不存在");
        throw e;
      }
      return api.put<Member>(`/projects/${projectId}/members/${encodeURIComponent(user.id)}`, { role });
    },
    onSuccess: () => {
      form.resetFields();
      refresh();
    },
    onError: (e) => message.error(errorText(e)),
  });
  const remove = useMutation({
    mutationFn: (userId: string) => api.del(`/projects/${projectId}/members/${userId}`),
    onSuccess: refresh,
    onError: (e) => message.error(errorText(e)),
  });

  return (
    <Card title={`项目设置 · ${project.data?.name ?? ""}`}>
      {members.error && <Alert type="error" showIcon message={errorText(members.error)} />}
      {isOwner && (
        <Form form={form} layout="inline" onFinish={addMember.mutate} initialValues={{ role: "viewer" }} style={{ marginBottom: 16 }}>
          <Form.Item name="email" rules={[{ required: true, type: "email", message: "请输入邮箱" }]}>
            <Input placeholder="邮箱" style={{ width: 280 }} />
          </Form.Item>
          <Form.Item name="role">
            <Select options={roleOptions} style={{ width: 110 }} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={addMember.isPending}>
            添加成员
          </Button>
        </Form>
      )}
      <Table<Member>
        rowKey="user_id"
        size="small"
        loading={members.isPending}
        dataSource={members.data?.items}
        pagination={false}
        locale={{ emptyText: "暂无成员" }}
        columns={[
          { title: "邮箱", dataIndex: "email" },
          {
            title: "角色",
            width: 140,
            render: (_, m) =>
              isOwner && m.user_id !== me.data?.id ? (
                <Select
                  size="small"
                  value={m.role}
                  options={roleOptions}
                  style={{ width: 110 }}
                  onChange={(role) => setRole.mutate({ user_id: m.user_id, role })}
                />
              ) : (
                roleLabels[m.role] ?? m.role
              ),
          },
          {
            title: "操作",
            width: 80,
            render: (_, m) =>
              isOwner &&
              m.user_id !== me.data?.id && (
                <Popconfirm title={`移除 ${m.email}？`} onConfirm={() => remove.mutate(m.user_id)}>
                  <Button type="link" danger size="small">
                    移除
                  </Button>
                </Popconfirm>
              ),
          },
        ]}
      />
    </Card>
  );
}
