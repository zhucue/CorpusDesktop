import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Form, Input } from "antd";
import { useNavigate } from "react-router";
import { api, errorText, type Project } from "./api";

export default function CreateProject({ onDone }: { onDone?: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const create = useMutation({
    mutationFn: (name: string) => api.post<Project>("/projects", { name }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      onDone?.();
      navigate(`/p/${p.id}/corpora`);
    },
  });
  return (
    <Form layout="vertical" onFinish={(v: { name: string }) => create.mutate(v.name.trim())}>
      <Form.Item name="name" label="项目名称" rules={[{ required: true, whitespace: true, message: "请输入项目名称" }]}>
        <Input maxLength={100} />
      </Form.Item>
      {create.error && <Alert type="error" showIcon message={errorText(create.error)} style={{ marginBottom: 12 }} />}
      <Button type="primary" htmlType="submit" loading={create.isPending}>
        创建项目
      </Button>
    </Form>
  );
}
