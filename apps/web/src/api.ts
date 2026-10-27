export type Role = "owner" | "editor" | "annotator" | "viewer";

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_admin: boolean;
}

export interface Project {
  id: string;
  name: string;
  role: Role;
  created_at: string;
}

export interface Member {
  user_id: string;
  email: string;
  role: Role;
}

export type CorpusStatus = "empty" | "importing" | "indexing" | "ready" | "stale" | "failed";

export interface Stats {
  documents: number;
  sentences: number;
  tokens: number;
}

export interface Corpus {
  id: string;
  project_id: string | null;
  name: string;
  language: string;
  description: string;
  parallel: boolean;
  status: CorpusStatus;
  error: string | null;
  stats: Stats;
  index_version: number | string | null;
  created_at: string;
}

export type Metadata = Record<string, unknown>;

export interface Doc {
  id: string;
  corpus_id: string;
  title: string;
  language: string;
  metadata: Metadata;
  sentences: number;
  tokens: number;
  created_at: string;
}

export interface MetadataField {
  field: string;
  type: "string" | "number";
  values?: (string | number)[];
}

export type FilterValue = string | number | (string | number)[] | { gte?: number; lte?: number };

export interface Subcorpus {
  id: string;
  project_id: string;
  corpus_id: string;
  name: string;
  filter: Record<string, FilterValue>;
  stats: Stats;
}

export type Scope = { corpus_id: string } | { subcorpus_id: string };

export interface SearchRequest {
  scope: Scope;
  query: string;
  context: { unit: "char" | "sentence" | "paragraph"; size: number };
  sort: "position" | "left" | "right" | "random";
  seed?: number;
  page: number;
  page_size: number;
  search_id?: string;
}

export interface ParseResult {
  ok: boolean;
  anchor: string;
  conditions: { op: "+" | "-"; text: string }[];
  tokens: { kind: string; text: string }[];
  error: { position: number; message: string } | null;
}

export interface Hit {
  hit_id: string;
  document_id: string;
  document_title: string;
  sentence_index: number;
  left: string;
  match: string;
  right: string;
  start_cp: number;
  end_cp: number;
  metadata: Metadata;
  aligned: { language: string; text: string }[];
}

export interface SearchResult {
  search_id: string;
  parse: ParseResult;
  counts: { hits: number; sentences: number; documents: number; complete: boolean };
  items: Hit[];
  page: number;
  page_size: number;
}

export interface ContextResult {
  document: Doc;
  sentences: { index: number; text: string; highlight: [number, number] | null }[];
}

export interface SavedQuery {
  id: string;
  project_id: string;
  name: string;
  query: string;
  scope: Scope;
  created_at: string;
}

export type JobState = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface Job {
  id: string;
  project_id: string;
  kind: "import" | "index" | "export";
  state: JobState;
  progress: { done: number; total: number | null; message: string };
  /** export: {rows, hits, filename} */
  result: { rows?: number; hits?: number; filename?: string; [k: string]: unknown } | null;
  error: { code: string; message: string } | null;
  created_at: string;
  finished_at: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
}

// Codes whose backend message carries the specifics (position, field, format) keep it after the label.
const codeLabels: Record<string, { label: string; detail?: boolean }> = {
  CORPUS_NOT_READY: { label: "语料库尚未就绪" },
  SEARCH_EXPIRED: { label: "结果已过期，重新检索" },
  JOB_IN_PROGRESS: { label: "任务仍在进行" },
  JOB_FINISHED: { label: "任务已结束" },
  LAST_OWNER: { label: "不能移除最后一位负责人" },
  QUERY_INVALID: { label: "查询式无效", detail: true },
  INVALID_FILTER: { label: "筛选条件无效", detail: true },
  UNSUPPORTED_FORMAT: { label: "不支持的文件格式", detail: true },
  TOO_LARGE: { label: "文件超过 500 MB" },
};

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    const known = codeLabels[code];
    super(!known ? message : known.detail && message && message !== known.label ? `${known.label}：${message}` : known.label);
  }
}

type Query = Record<string, string | number | undefined>;

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== "") params.set(k, String(v));
  const s = params.toString();
  return s ? `${path}?${s}` : path;
}

export async function request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
  const init: RequestInit = { method, credentials: "include", headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await fetch(withQuery(`/api${path}`, query), init);
  if (res.status === 401 && path !== "/auth/login" && path !== "/auth/me") {
    if (window.location.pathname !== "/login") window.location.assign("/login");
  }
  if (!res.ok) {
    let code = "http_error";
    let message = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      if (data?.error) {
        code = data.error.code ?? code;
        message = data.error.message ?? message;
      }
    } catch {
      /* non-JSON body */
    }
    if (res.status === 413) code = "TOO_LARGE";
    throw new ApiError(res.status, code, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, undefined, query),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: (path: string) => request<void>("DELETE", path),
};

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export const MAX_PAGE_SIZE = 200;

export const roleLabels: Record<Role, string> = {
  owner: "所有者",
  editor: "编辑者",
  annotator: "标注者",
  viewer: "查看者",
};
