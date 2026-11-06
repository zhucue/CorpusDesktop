import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Form, Input, Modal, Progress, Select, Upload, type UploadFile } from "antd";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { api, ApiError, errorFromResponse, errorText, unavailableText, type Corpus, type CorpusMeta, type Job, type Metadata } from "../../api";
import { CorpusStatusTag, ErrorAlert } from "../../components/common";
import { Icon } from "../../components/Icon";
import { isActiveJob, useJob, useJobCreated } from "../../lib/data";
import { fmt } from "../../lib/format";
import { emptyMeta, MetadataInput, metadataFromDraft, metaDraftRule, type MetaDraft } from "./MetadataInput";
import { TableMappingFields, useTableMapping, type ImportMapping } from "./TableMapping";

/** Languages with automatic annotation (engine.nlp.SUPPORTED). */
export const languageOptions = [
  { value: "zh", label: "中文 zh" },
  { value: "en", label: "英语 en" },
  { value: "ja", label: "日语 ja" },
  { value: "fr", label: "法语 fr" },
  { value: "de", label: "德语 de" },
  { value: "es", label: "西班牙语 es" },
  { value: "ru", label: "俄语 ru" },
];

/** Upload language: "auto" detects each document's language from its text (CSV rows one by one). */
export const AUTO_LANGUAGE = "auto";
export const uploadLanguageOptions = [{ value: AUTO_LANGUAGE, label: "自动（按内容识别）" }, ...languageOptions];

export const ACCEPT = ".txt,.docx,.pdf,.csv,.tsv,.xlsx,.jsonl,.conllu,.tmx";
export const FORMATS_HINT = "TXT · DOCX · PDF · CSV/TSV · XLSX · JSONL · CoNLL-U · TMX";

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

/** Source and license fields of the upload dialog (Corpus.meta; the export source line uses them). */
export const SOURCE_FIELDS: ["license" | "attribution" | "source_url", string, number][] = [
  ["license", "许可", 200],
  ["attribution", "署名", 2000],
  ["source_url", "来源链接", 1000],
];
export type SourceValues = Partial<Record<"license" | "attribution" | "source_url", string>>;

export interface UploadOptions {
  /** Corpus source and license: a filled field is set, an empty one removed. */
  source?: SourceValues;
  onProgress?: (loaded: number, total: number) => void;
  signal?: AbortSignal;
}

/** POST a form with XMLHttpRequest for upload progress; errors as from `request` (ApiError), abort as AbortError. */
export function postForm<T>(path: string, body: FormData, { onProgress, signal }: UploadOptions = {}): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException("已取消上传", "AbortError"));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api${path}`);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(e.loaded, e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as T);
        } catch {
          reject(new ApiError(xhr.status, "http_error", "响应格式错误"));
        }
        return;
      }
      void errorFromResponse(new Response(xhr.responseText, { status: xhr.status, statusText: xhr.statusText }), "POST").then(reject);
    };
    xhr.onerror = () => reject(new ApiError(0, "UNAVAILABLE", unavailableText("POST")));
    xhr.onabort = () => reject(new DOMException("已取消上传", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(body);
  });
}

/** Upload files into an existing corpus. Returns the import job. */
export async function uploadFiles(
  corpusId: string,
  files: File[],
  language?: string,
  metadata?: Metadata,
  mapping?: ImportMapping | null,
  options: UploadOptions = {},
): Promise<Job> {
  const body = new FormData();
  for (const f of files) body.append("files", f);
  if (language) body.append("language", language);
  if (metadata && Object.keys(metadata).length) body.append("metadata", JSON.stringify(metadata));
  if (mapping) body.append("mapping", JSON.stringify(mapping));
  if (options.source) body.append("source", JSON.stringify(options.source));
  return postForm<Job>(`/corpora/${corpusId}/documents`, body, options);
}

/** Form values → the source body: every field trimmed (empty removes it); undefined when nothing changed. */
export function sourceBody(values: SourceValues | undefined, current: CorpusMeta | undefined): SourceValues | undefined {
  const out: SourceValues = {};
  let changed = false;
  for (const [k] of SOURCE_FIELDS) {
    const v = values?.[k]?.trim() ?? "";
    out[k] = v;
    if (v !== (current?.[k] ?? "")) changed = true;
  }
  return changed ? out : undefined;
}

export const isAbort = (e: unknown) => e instanceof DOMException && e.name === "AbortError";

function mb(n: number): string {
  return (n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0);
}

/** "导入完成：3 篇，跳过重复 2 篇（a.csv #4、b.txt）" from an import job result. */
export function importSummary(job: Job): string {
  const r = job.result ?? {};
  const skipped = Number(r.skipped_duplicates ?? 0);
  const names = Array.isArray(r.duplicates) ? (r.duplicates as string[]) : [];
  let text = `导入完成：${fmt(Number(r.documents ?? 0))} 篇`;
  if (skipped) text += `，跳过重复 ${fmt(skipped)} 篇${names.length ? `（${names.slice(0, 3).join("、")}${skipped > 3 ? " 等" : ""}）` : ""}`;
  return text;
}

/** Watch an import job after upload; when it succeeds, tell how many documents came in and how many were duplicates. */
export function useImportNotice(): (job: Job) => void {
  const { message } = App.useApp();
  const [id, setId] = useState<string | null>(null);
  const job = useJob(id, 2000);
  useEffect(() => {
    const j = job.data;
    if (!j || isActiveJob(j)) return;
    setId(null);
    if (j.state === "succeeded") message.success(importSummary(j), 6);
  }, [job.data, message]);
  return (j: Job) => setId(j.id);
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

type Values = { corpus: string; name?: string; language: string; metadata?: MetaDraft; source?: SourceValues };

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
  const watchImport = useImportNotice();
  const [progress, setProgress] = useState<{ loaded: number; total: number } | null>(null);
  const abort = useRef<AbortController | null>(null);

  // a closed dialog forgets its files (Esc, 取消 or after upload)
  useEffect(() => {
    if (!open) setFiles([]);
  }, [open]);

  // the source fields show the chosen corpus's values (empty for a new corpus)
  const currentMeta = current?.meta;
  const currentId = current?.id;
  useEffect(() => {
    if (!open) return;
    form.setFieldsValue({ source: Object.fromEntries(SOURCE_FIELDS.map(([k]) => [k, currentMeta?.[k] ?? ""])) as SourceValues });
    // only when the dialog opens or the target corpus changes: a corpus list refresh keeps what was typed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, currentId, form]);

  const upload = useMutation({
    mutationFn: async (v: Values) => {
      const ctrl = new AbortController();
      abort.current = ctrl;
      setProgress({ loaded: 0, total: files.reduce((n, f) => n + (f.size ?? 0), 0) });
      let id = v.corpus;
      let created: string | null = null;
      if (id === NEW) {
        const filled = Object.fromEntries(Object.entries(sourceBody(v.source, undefined) ?? {}).filter(([, x]) => x));
        const c = await api.post<Corpus>(`/projects/${projectId}/corpora`, {
          name: v.name!.trim(),
          language: v.language,
          ...(Object.keys(filled).length ? { meta: filled } : {}),
        });
        id = created = c.id;
      }
      try {
        return await uploadFiles(id, files.map((f) => f.originFileObj as File), v.language, metadataFromDraft(v.metadata), table.mapping, {
          source: created ? undefined : sourceBody(v.source, currentMeta),
          signal: ctrl.signal,
          onProgress: (loaded, total) => setProgress({ loaded, total }),
        });
      } catch (e) {
        // a corpus made for this upload is kept only when the upload got through
        if (created) await api.del(`/corpora/${created}`).catch(() => undefined);
        throw e;
      }
    },
    onSettled: () => {
      abort.current = null;
      setProgress(null);
    },
    onError: (e) => {
      if (isAbort(e)) message.info("已取消上传");
    },
    onSuccess: (job: Job) => {
      qc.invalidateQueries({ queryKey: ["corpora", projectId] });
      jobCreated(projectId);
      watchImport(job);
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

  const uploading = upload.isPending;
  const percent = progress && progress.total ? Math.min(100, Math.floor((progress.loaded / progress.total) * 100)) : 0;
  return (
    <Modal
      title="上传语料"
      open={open}
      onCancel={() => (uploading ? abort.current?.abort() : onClose())}
      okText="上传"
      cancelText={uploading ? "取消上传" : "取消"}
      width={table.tables.length ? 720 : 560}
      okButtonProps={{ disabled: files.length === 0 || !table.ready, loading: uploading }}
      onOk={() => form.submit()}
      maskClosable={!uploading}
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
          <FilePicker files={files} setFiles={setFiles} hint={`${FORMATS_HINT} · Tatoeba 三件 TSV`} />
        </Form.Item>
        <TableMappingFields state={table} />
        <Form.Item name="language" label="语言">
          <Select options={uploadLanguageOptions} aria-label="语言" />
        </Form.Item>
        <Form.Item name="metadata" label="元数据（应用到本批全部文档）" rules={[metaDraftRule]}>
          <MetadataInput />
        </Form.Item>
        <div className="upload-source" role="group" aria-label="来源与许可">
          {SOURCE_FIELDS.map(([k, label, max]) => (
            <Form.Item key={k} name={["source", k]} label={label}>
              <Input maxLength={max} allowClear aria-label={label} />
            </Form.Item>
          ))}
        </div>
        {progress && (
          <div className="upload-progress" role="status">
            <Progress percent={percent} size="small" status="active" />
            <span className="num">{percent < 100 ? `已上传 ${mb(progress.loaded)} / ${mb(progress.total)} MB` : "上传完成，正在创建导入任务"}</span>
          </div>
        )}
        {!isAbort(upload.error) && <ErrorAlert error={upload.error} />}
      </Form>
    </Modal>
  );
}
