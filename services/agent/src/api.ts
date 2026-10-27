/** Thin client for the business api (contracts/p1.md §二, p2.md §三–五, p4.md §四). */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/** Browser credentials (Cookie + Origin) or the agent token issued for one project. */
export type ApiAuth = { cookie?: string; origin?: string } | { bearer: string };

export interface User { id: string; email: string; display_name: string; is_admin: boolean }
export interface Job {
  id: string; project_id: string | null; kind: string; state: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  progress: { done: number; total: number | null; message: string } | null;
  result: Record<string, unknown> | null; error: { code: string; message: string } | null;
}

export class ApiClient {
  private readonly base: string;
  private readonly auth: ApiAuth;
  constructor(base: string, auth: ApiAuth) {
    this.base = base;
    this.auth = auth;
  }

  async request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if ('bearer' in this.auth) headers.Authorization = `Bearer ${this.auth.bearer}`;
    else {
      if (this.auth.cookie) headers.Cookie = this.auth.cookie;
      if (this.auth.origin) headers.Origin = this.auth.origin;
    }
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    let response: Response;
    try {
      response = await fetch(this.base + path, {
        method, headers, signal, body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (error) {
      if (signal?.aborted) throw error;
      throw new ApiError(502, 'API_UNAVAILABLE', `api 不可用：${(error as Error).message}`);
    }
    if (response.status === 204) return undefined as T;
    const text = await response.text();
    let data: any = null;
    try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON body */ }
    if (!response.ok) {
      const code = data?.error?.code ?? `HTTP_${response.status}`;
      const message = data?.error?.message ?? (text.slice(0, 200) || response.statusText);
      throw new ApiError(response.status, code, message);
    }
    return data as T;
  }

  get<T>(path: string, signal?: AbortSignal) { return this.request<T>('GET', path, undefined, signal); }
  post<T>(path: string, body: unknown = {}, signal?: AbortSignal) { return this.request<T>('POST', path, body, signal); }
  patch<T>(path: string, body: unknown, signal?: AbortSignal) { return this.request<T>('PATCH', path, body, signal); }
}

export function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== null) search.set(key, String(value));
  const text = search.toString();
  return text ? `?${text}` : '';
}
