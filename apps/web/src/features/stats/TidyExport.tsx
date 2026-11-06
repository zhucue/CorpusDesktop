import { Checkbox, Form, Input, Modal, Segmented } from "antd";
import { useEffect } from "react";
import type { Scope, TidyExportRequest } from "../../api";
import { ScopeSelect } from "../../components/common/ScopeSelect";
import { useExportJob } from "../../lib/exportJob";
import { scopeRule } from "./formParts";

const MAX_QUERIES = 10;

/** Non-empty query lines of the textarea. */
export function queryLines(text: string | undefined): string[] {
  return (text ?? "")
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
}

/**
 * 导出整洁数据 (contracts/p10.md §三): one row per document, metadata as columns, q{n}_hits / q{n}_pm per query,
 * optional text metrics. Runs as an export job and downloads through the shared download (lib/download).
 */
export function TidyExportDialog({ open, onClose, projectId, scope }: { open: boolean; onClose: () => void; projectId: string; scope: Scope | null }) {
  const [form] = Form.useForm();
  const exporter = useExportJob(projectId);
  useEffect(() => {
    if (open && scope && !form.getFieldValue("scope")) form.setFieldValue("scope", scope);
  }, [open, scope, form]);

  const submit = (v: { scope: Scope; queries?: string; metrics?: boolean; format: "csv" | "xlsx" }) => {
    const queries = queryLines(v.queries);
    const body: TidyExportRequest = { project_id: projectId, scope: v.scope, format: v.format, metrics: !!v.metrics };
    if (queries.length) body.queries = queries;
    exporter.start({ url: "/stats/tidy_export", body, label: `整洁数据 ${v.format.toUpperCase()}` });
    onClose();
  };

  return (
    <Modal title="导出整洁数据" open={open} onCancel={onClose} okText="导出" cancelText="取消" onOk={() => form.submit()} okButtonProps={{ disabled: exporter.busy }} width={480} forceRender>
      <Form form={form} layout="vertical" requiredMark={false} onFinish={submit} initialValues={{ metrics: false, format: "csv" }}>
        <Form.Item name="scope" label="范围" rules={scopeRule()}>
          <ScopeSelect projectId={projectId} value={form.getFieldValue("scope")} onChange={() => {}} width={300} />
        </Form.Item>
        <Form.Item
          name="queries"
          label={`查询式（每行一个，最多 ${MAX_QUERIES} 个）`}
          rules={[{ validator: (_, v?: string) => (queryLines(v).length > MAX_QUERIES ? Promise.reject(new Error(`最多 ${MAX_QUERIES} 个查询式`)) : Promise.resolve()) }]}
        >
          <Input.TextArea className="mono" rows={4} placeholder={"翻译/v\n文化"} aria-label="查询式" />
        </Form.Item>
        <Form.Item name="metrics" valuePropName="checked">
          <Checkbox>附文本指标</Checkbox>
        </Form.Item>
        <Form.Item name="format" label="格式">
          <Segmented
            options={[
              { value: "csv", label: "CSV" },
              { value: "xlsx", label: "XLSX" },
            ]}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
