import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag } from "antd";
import { useState } from "react";
import { Link } from "react-router";
import { api, errorText, type Corpus } from "../api";
import { CorpusStatusTag, fmt, languageOptions, useCorpora } from "../corpora";
import { useMe } from "../App";
import { canEdit, useProject, useProjectId } from "../projects";
import Subcorpora from "./Subcorpora";

export default function Corpora() {
  const projectId = useProjectId();
  const project = useProject();
  const corpora = useCorpora(projectId);
  const qc = useQueryClient();
  const { message } = App.useApp();
  const me = useMe();
  const [creating, setCreating] = useState<"project" | "builtin" | null>(null);
  const editable = canEdit(project.data);
  const isAdmin = !!me.data?.is_admin;

  const create = useMutation({
    mutationFn: (v: { name: string; language: string; description?: string }) =>
      api.post<Corpus>(creating === "builtin" ? "/corpora" : `/projects/${projectId}/corpora`, v),
    onSuccess: () => {
      setCreating(null);
      qc.invalidateQueries({ queryKey: ["corpora", projectId] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/corpora/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["corpora", projectId] }),
    onError: (e) => message.error(errorText(e)),
  });

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Card
        title="语料库"
        extra={
          <Space>
            {isAdmin && <Button onClick={() => setCreating("builtin")}>新建内置语料</Button>}
            {editable && (
              <Button type="primary" onClick={() => setCreating("project")}>
                新建语料库
              </Button>
            )}
          </Space>
        }
      >
        {corpora.error && <Alert type="error" showIcon message={errorText(corpora.error)} />}
        <Table<Corpus>
          rowKey="id"
          size="small"
          loading={corpora.isPending}
          dataSource={corpora.data?.items}
          pagination={false}
          locale={{ emptyText: "暂无语料库" }}
          columns={[
            {
              title: "名称",
              render: (_, c) => (
                <Space>
                  <Link to={`/p/${projectId}/corpora/${c.id}`}>{c.name}</Link>
                  {c.project_id === null && <Tag>内置</Tag>}
                  {c.parallel && <Tag color="blue">平行</Tag>}
                </Space>
              ),
            },
            { title: "语言", dataIndex: "language", width: 80 },
            { title: "状态", render: (_, c) => <CorpusStatusTag corpus={c} /> },
            { title: "文档", align: "right", width: 90, render: (_, c) => fmt(c.stats.documents) },
            { title: "句", align: "right", width: 100, render: (_, c) => fmt(c.stats.sentences) },
            { title: "词", align: "right", width: 110, render: (_, c) => fmt(c.stats.tokens) },
            {
              title: "操作",
              width: 80,
              render: (_, c) =>
                editable &&
                c.project_id !== null && (
                  <Popconfirm title={`删除语料库「${c.name}」？`} onConfirm={() => remove.mutate(c.id)}>
                    <Button type="link" danger size="small">
                      删除
                    </Button>
                  </Popconfirm>
                ),
            },
          ]}
        />
      </Card>
      <Subcorpora corpora={corpora.data?.items ?? []} editable={editable} />
      <Modal
        title={creating === "builtin" ? "新建内置语料" : "新建语料库"}
        open={!!creating}
        footer={null}
        onCancel={() => setCreating(null)}
        destroyOnClose
      >
        <Form layout="vertical" onFinish={create.mutate} initialValues={{ language: "zh" }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, whitespace: true, message: "请输入名称" }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="language" label="语言" rules={[{ required: true }]}>
            <Select options={languageOptions} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          {create.error && <Alert type="error" showIcon message={errorText(create.error)} style={{ marginBottom: 12 }} />}
          <Button type="primary" htmlType="submit" loading={create.isPending}>
            创建
          </Button>
        </Form>
      </Modal>
    </Space>
  );
}
