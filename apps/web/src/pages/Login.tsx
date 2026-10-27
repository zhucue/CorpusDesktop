import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Form, Input } from "antd";
import { useNavigate } from "react-router";
import { api, errorText, type User } from "../api";

export default function Login() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const login = useMutation({
    mutationFn: (v: { email: string; password: string }) => api.post<User>("/auth/login", v),
    onSuccess: (user) => {
      qc.clear();
      qc.setQueryData(["me"], user);
      navigate("/", { replace: true });
    },
  });
  return (
    <Card title="登录" style={{ maxWidth: 360, margin: "120px auto" }}>
      <Form layout="vertical" onFinish={login.mutate}>
        <Form.Item name="email" label="邮箱" rules={[{ required: true, type: "email", message: "请输入邮箱" }]}>
          <Input autoComplete="username" autoFocus />
        </Form.Item>
        <Form.Item name="password" label="密码" rules={[{ required: true, message: "请输入密码" }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        {login.error && <Alert type="error" showIcon message={errorText(login.error)} style={{ marginBottom: 12 }} />}
        <Button type="primary" htmlType="submit" block loading={login.isPending}>
          登录
        </Button>
      </Form>
    </Card>
  );
}
