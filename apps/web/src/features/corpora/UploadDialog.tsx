import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Form, Input, Modal, Select, Upload, type UploadFile } from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, errorText, type Corpus, type Job, type Metadata, type TableMapping } from "../../api";
import { CorpusStatusTag, ErrorAlert } from "../../components/common";
import { Icon } from "../../components/Icon";
import { useJobCreated } from "../../lib/data";
import { fmt } from "../../lib/format";
import { emptyMeta, MetadataInput, metadataFromDraft, metaDraftRule, type MetaDraft } from "./MetadataInput";
import { TableMappingFields, useTableMapping } from "./TableMapping";

export const languageOptions = [
  { value: "zh", label: "中文 zh" },
  { value: "en", label: "英语 en" },
];

/** Upload language: "auto" detects each document's language from its text (CSV rows one by one). */
export const AUTO_LANGUAGE = "auto";
export const uploadLanguageOptions = [{ value: AUTO_LANGUAGE, label: "自动（按内容识别）" }, ...languageOptions];

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

/** Same file chosen twice (name and size) is dropped; returns the kept list and the dropped names. */
export function dedupeFiles(list: UploadFile[]): { files: UploadFile[]; dropped: string[] } {
  const seen = new Set<string>();
  const files: UploadFile[] = [];
  const dropped: string[] = [];
  for (const f of list) {
    const k = `${f.name}:${f.size ?? f.originFileObj?.size ?? ""}`;
    if (seen.has(k)) dropped.push(f.name);
    else {
      seen.add(k);
      files.push(f);
    }
  }
  return { files, dropped };
}

/** Upload files into an existing corpus, or create a project corpus first. Returns the import job. */
export async function uploadFiles(
  corpusId: string,
  files: File[],
  language?: string,
  metadata?: Metadata,
  mapping?: TableMapping | null,
): Promise<Job> {
  const body = new FormData();
  for (const f of files) body.append("files", f);
  if (language) body.append("language", language);
  if (metadata && Object.keys(metadata).length) body.append("metadata", JSON.stringify(metadata));
  if (mapping) body.append("mapping", JSON.stringify(mapping));
  return api.post<Job>(`/corpora/${corpusId}/documents`, body);
}

/** File picker shared by the upload dialog and the corpus drawer: duplicates are dropped with a notice. */
export function FilePicker({ files, setFiles, hint }: { files: UploadFile[]; setFiles: (f: UploadFile[]) => void; hint: string }) {
  const { message } = App.useApp();
  return (
    <Upload.Dragger
      multiple
      fileList={files}
      beforeUpload={() => false}
      onChange={(i) => {
        const { files: kept, dropped } = dedupeFiles(i.fileList);
        if (dropped.length) message.warning(`已跳过重复文件：${[...new Set(dropped)].join("、")}`);
        setFiles(kept);
      }}
      accept={ACCEPT}
    >
      <div className="col" style={{ alignItems: "center", gap: 6, padding: "6px 0" }}>
        <Icon name="upload" size={20} />
        <span>拖入文件或点击选择</span>
        <span className="small muted">{hint}</span>
      </div>
    </Upload.Dragger>
  );
}

type Values = { corpus: string; name?: string; language: string; metadata?: MetaDraft };

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
  /** The corpus the user is looking at: preselected; otherwise 新建语料库. */
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
  const current = own.find((c) => c.id === target);
  const table = useTableMapping(files.map((f) => f.originFileObj as File));

  // a closed dialog forgets its files (Esc, 取消 or after upload)
  useEffect(() => {
    if (!open) setFiles([]);
  }, [open]);

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
        metadataFromDraft(v.metadata),
        table.mapping,
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
      width={table.tables.length ? 720 : 560}
      okButtonProps={{ disabled: files.length === 0 || !table.ready, loading: upload.isPending }}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={(v) => upload.mutate(v)}
        initialValues={{ corpus: corpusId && own.some((c) => c.id === corpusId) ? corpusId : NEW, language: AUTO_LANGUAGE, metadata: emptyMeta() }}
        requiredMark={false}
      >
        <Form.Item name="corpus" label="导入到">
          <Select
            aria-label="导入到"
            options={[{ value: NEW, label: "新建语料库" }, ...own.map((c) => ({ value: c.id, label: c.project_id === null ? `${c.name}（内置）` : c.name }))]}
          />
        </Form.Item>
        {target === NEW ? (
          <Form.Item name="name" label="新语料库名称" rules={[{ required: true, whitespace: true, message: "请输入名称" }]}>
            <Input maxLength={100} autoFocus />
          </Form.Item>
        ) : (
          current && (
            <div className="upload-target" role="status">
              <Icon name="db" size={14} />
              <span className="grow">
                追加到「<b>{current.name}</b>」· 已有 {fmt(current.stats.documents)} 篇
              </span>
              <CorpusStatusTag status={current.status} />
            </div>
          )
        )}
        <Form.Item label="文件" required>
          <FilePicker files={files} setFiles={setFiles} hint="TXT · DOCX · CSV/TSV · CoNLL-U · TMX · Tatoeba 三件 TSV" />
        </Form.Item>
        <TableMappingFields state={table} />
        <Form.Item name="language" label="语言">
          <Select options={uploadLanguageOptions} aria-label="语言" />
        </Form.Item>
        <Form.Item name="metadata" label="元数据（应用到本批全部文档）" rules={[metaDraftRule]}>
          <MetadataInput />
        </Form.Item>
        <ErrorAlert error={upload.error} />
      </Form>
    </Modal>
  );
}
