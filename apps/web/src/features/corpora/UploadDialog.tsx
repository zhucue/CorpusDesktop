import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Form, Input, Modal, Select, Upload, type UploadFile } from "antd";
import { useState } from "react";
import { Link } from "react-router";
import { api, errorText, type Corpus, type Job, type Metadata } from "../../api";
import { ErrorAlert } from "../../components/common";
import { Icon } from "../../components/Icon";
import { useJobCreated } from "../../lib/data";

export const languageOptions = [
  { value: "zh", label: "中文 zh" },
  { value: "en", label: "英语 en" },
];

export const ACCEPT = ".txt,.docx,.csv,.tsv,.conllu,.tmx";

export function parseMetadata(text: string | undefined): Metadata {
  if (!text?.trim()) return {};
  const v: unknown = JSON.parse(text);
  if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error("元数据须为 JSON 对象");
  return v as Metadata;
}

export const metadataRule = {
  validator: (_: unknown, v: string | undefined) => {
    try {
      parseMetadata(v);
      return Promise.resolve();
    } catch (e) {
      return Promise.reject(new Error(e instanceof SyntaxError ? "JSON 格式错误" : errorText(e)));
    }
  },
};

const NEW = "__new__";

/** Upload files into an existing corpus, or create a project corpus first. Returns the import job. */
export async function uploadFiles(corpusId: string, files: File[], language?: string, metadata?: Metadata): Promise<Job> {
  const body = new FormData();
  for (const f of files) body.append("files", f);
  if (language) body.append("language", language);
  if (metadata && Object.keys(metadata).length) body.append("metadata", JSON.stringify(metadata));
  return api.post<Job>(`/corpora/${corpusId}/documents`, body);
}

type Values = { corpus: string; name?: string; language: string; metadata?: string };

export default function UploadDialog({
  open,
  projectId,
  corpora,
  corpusId,
  isAdmin,
  onClose,
}: {
  open: boolean;
  projectId: string;
  corpora: Corpus[];
  corpusId?: string;
  isAdmin?: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const jobCreated = useJobCreated();
  const [form] = Form.useForm<Values>();
  const [files, setFiles] = useState<UploadFile[]>([]);
  const target = Form.useWatch("corpus", form);
  const own = corpora.filter((c) => c.project_id === projectId || (isAdmin && c.project_id === null));

  const upload = useMutation({
    mutationFn: async (v: Values) => {
      let id = v.corpus;
      if (id === NEW) {
        const c = await api.post<Corpus>(`/projects/${projectId}/corpora`, { name: v.name!.trim(), language: v.language });
        id = c.id;
      }
      return uploadFiles(
        id,
        files.map((f) => f.originFileObj as File),
        v.language,
        parseMetadata(v.metadata),
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["corpora", projectId] });
      jobCreated(projectId);
      message.success(
        <span>
          已创建导入任务，<Link to={`/p/${projectId}/jobs`}>查看任务</Link>
        </span>,
      );
      setFiles([]);
      form.resetFields();
      onClose();
    },
  });

  return (
    <Modal
      title="上传语料"
      open={open}
      onCancel={onClose}
      okText="上传"
      cancelText="取消"
      width={560}
      okButtonProps={{ disabled: files.length === 0, loading: upload.isPending }}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={(v) => upload.mutate(v)}
        initialValues={{ corpus: corpusId ?? own[0]?.id ?? NEW, language: "zh" }}
        requiredMark={false}
      >
        <Form.Item name="corpus" label="语料库">
          <Select
            options={[...own.map((c) => ({ value: c.id, label: c.name })), { value: NEW, label: "新建语料库" }]}
            onChange={(id) => {
              const c = own.find((x) => x.id === id);
              if (c) form.setFieldValue("language", c.language);
            }}
          />
        </Form.Item>
        {target === NEW && (
          <Form.Item name="name" label="名称" rules={[{ required: true, whitespace: true, message: "请输入名称" }]}>
            <Input maxLength={100} />
          </Form.Item>
        )}
        <Form.Item label="文件" required>
          <Upload.Dragger multiple fileList={files} beforeUpload={() => false} onChange={(i) => setFiles(i.fileList)} accept={ACCEPT}>
            <div className="col" style={{ alignItems: "center", gap: 6, padding: "6px 0" }}>
              <Icon name="upload" size={20} />
              <span>拖入文件或点击选择</span>
              <span className="small muted">TXT · DOCX · CSV/TSV · CoNLL-U · TMX · Tatoeba 三件 TSV</span>
            </div>
          </Upload.Dragger>
        </Form.Item>
        <Form.Item name="language" label="语言">
          <Select options={languageOptions} />
        </Form.Item>
        <Form.Item name="metadata" label="元数据（JSON，应用到本批全部文档）" rules={[metadataRule]}>
          <Input.TextArea rows={2} placeholder='{"year": 2020, "genre": "新闻"}' style={{ fontFamily: "var(--mono)" }} />
        </Form.Item>
        <ErrorAlert error={upload.error} />
      </Form>
    </Modal>
  );
}
