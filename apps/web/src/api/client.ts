import type { Role } from "./types";

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
  PARSE_ERROR: { label: "文件解析失败", detail: true },
  INVALID_MAPPING: { label: "列映射无效", detail: true },
  TOO_LARGE: { label: "文件超过 500 MB" },
  SESSION_BUSY: { label: "该会话正在运行" },
  MODEL_NOT_CONFIGURED: { label: "未配置对话模型" },
  LABEL_SET_IN_USE: { label: "标签集正被标注层使用" },
  EMBED_UNAVAILABLE: { label: "向量模型未就绪，已改用关键词检索" },
};

export function codeLabel(code: string, message: string): string {
  const known = codeLabels[code];
  if (!known) return message;
  return known.detail && message && message !== known.label ? `${known.label}：${message}` : known.label;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(codeLabel(code, message));
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

/** Gateway errors and failed connections (backend restarting): one Chinese message saying whether a write was lost. */
const UNAVAILABLE_STATUS = new Set([502, 503, 504]);
export function unavailableText(method = "GET"): string {
  return method === "GET" ? "服务暂时不可用，请稍后重试" : "服务暂时不可用，本次修改未保存，请重试";
}

export async function errorFromResponse(res: Response, method?: string): Promise<ApiError> {
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
  if (code === "http_error" && UNAVAILABLE_STATUS.has(res.status)) return new ApiError(res.status, "UNAVAILABLE", unavailableText(method));
  return new ApiError(res.status, code, message);
}

export function buildInit(method: string, body?: unknown): RequestInit {
  const init: RequestInit = { method, credentials: "include", headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  return init;
}

function redirectToLogin() {
  if (window.location.pathname === "/login") return;
  const next = window.location.pathname + window.location.search;
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

export async function request<T>(method: string, path: string, body?: unknown, query?: Query, base = "/api"): Promise<T> {
  let res: Response;
  try {
    res = await fetch(withQuery(`${base}${path}`, query), buildInit(method, body));
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "UNAVAILABLE", unavailableText(method));
  }
  if (res.status === 401 && path !== "/auth/login" && path !== "/auth/me") redirectToLogin();
  if (!res.ok) throw await errorFromResponse(res, method);
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

/** The agent service is mounted at /agent (nginx and the Vite proxy forward it). */
export const agentApi = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, undefined, query, "/agent"),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}, undefined, "/agent"),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body, undefined, "/agent"),
  del: (path: string) => request<void>("DELETE", path, undefined, undefined, "/agent"),
};

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function errorCode(e: unknown): string | null {
  return e instanceof ApiError && e.code !== "http_error" ? e.code : null;
}

export const MAX_PAGE_SIZE = 200;

export const roleLabels: Record<Role, string> = {
  owner: "负责人",
  editor: "编辑者",
  annotator: "标注者",
  viewer: "查看者",
};
