/** Trusted host transport. Tokens and URLs are never part of a model tool schema. */
import { randomUUID } from 'node:crypto';

export type Scope = { scope_kind: 'account' | 'platform' } | {
  scope_kind: 'project'; project_id: string; snapshot_ids: string[];
  material_revision_ids: string[]; alignment_overlay_revision: null;
};
export interface Grant {
  run_id: string; session_id: string; state: string; scope: Scope;
  scope_digest: string; lease_epoch: number; allowed_tools: string[];
  runtime_manifest: RuntimeManifest; base_checkpoint: Checkpoint | null;
  user_message?: string; config_id?: string; continuation_message?: string | null;
  resume_checkpoint?: Checkpoint | null;
  waiting_jobs?: WaitingJob[];
}
export interface WaitingJob {
  invocation_id: string; job_id: string; kind: string; state: string;
  report_tool: string; report_arguments: Record<string, unknown>;
}
export const RUNTIME_MANIFEST = {
  sdk_package: '@earendil-works/pi-coding-agent', sdk_version: '1.3.0', session_version: 3,
  host_policy: 'corpus-k09-linear-v1', provider: 'corpus-s1-fixed', model: 'fixed-project-v1',
  tool_schema: 's3-outcomes-tools-v1', resource_config: 'corpus-empty-resources-v1',
} as const;
export interface RuntimeManifest {
  sdk_package: string; sdk_version: string; session_version: number;
  host_policy: string; provider: string; model: string; tool_schema: string; resource_config: string;
  model_api?: 'openai-completions' | 'openai-responses'; model_config_sha256?: string;
}
export interface Checkpoint {
  checkpoint_id: string; sha256: string; byte_size: number; sdk_session_id: string;
  leaf_id: string; runtime_manifest: RuntimeManifest;
}
export interface CheckpointDownload { checkpoint: Checkpoint | null; session_jsonl: string | null }
export interface InvocationOutput {
  result: { invocation_id: string; action_id: string | null; status: string; [key: string]: unknown };
  data: unknown;
}

export class RunProtocolError extends Error {
  status: number;
  constructor(code: string, status: number) { super(code); this.status = status; }
}

export class S1RunClient {
  #base: string;
  #hostKey: string;
  #token = '';
  #grant?: Grant;
  #fetch: typeof fetch;
  #registrations = new Map<string, string>();

  constructor(config: { baseUrl: string; hostKey: string; fetcher?: typeof fetch; allowInternalApi?: boolean }) {
    const url = new URL(config.baseUrl);
    if (url.username || url.password || url.search || url.hash || url.pathname !== '/' ||
        !(url.protocol === 'https:' || (url.protocol === 'http:' &&
          (['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) ||
           (config.allowInternalApi === true && url.origin === 'http://api:8000'))))) {
      throw new Error('TRUSTED_API_ORIGIN_REQUIRED');
    }
    this.#base = url.origin;
    this.#hostKey = config.hostKey;
    this.#fetch = config.fetcher ?? globalThis.fetch.bind(globalThis);
  }

  async #request<T>(path: string, credential: string, body?: unknown): Promise<T> {
    const response = await this.#fetch(this.#base + path, {
      method: body === undefined ? 'GET' : 'POST', redirect: 'error', credentials: 'omit',
      headers: { Authorization: `Bearer ${credential}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ code: 'AGENT_HTTP_ERROR' })) as { code?: string };
      throw new RunProtocolError(error.code ?? 'AGENT_HTTP_ERROR', response.status);
    }
    return await response.json() as T;
  }

  async #retryRequest<T>(path: string, body: unknown): Promise<T> {
    // Retry only the same registered request after an ambiguous transport failure.
    // Authorization, validation and conflict responses are never automatically retried.
    for (let attempt = 0; ; attempt++) {
      try { return await this.#request<T>(path, this.#token, body); }
      catch (error) { if (attempt >= 1 || error instanceof RunProtocolError) throw error; }
    }
  }

  async claim(runId: string): Promise<Grant> {
    if (this.#grant) throw new Error('HOST_ALREADY_CLAIMED');
    const result = await this.#request<Grant & { execution_token: string }>(
      `/internal/agent/runs/${encodeURIComponent(runId)}/claim`, this.#hostKey, { host_id: randomUUID() });
    const { execution_token, ...grant } = result;
    this.#token = execution_token;
    this.#hostKey = '';
    this.#grant = grant;
    return structuredClone(grant);
  }

  async claimNext(hostId: string, configId = 'local-fixture-v1'): Promise<Grant | null> {
    if (this.#grant) throw new Error('HOST_ALREADY_CLAIMED');
    const result = await this.#request<{ grant: (Grant & { execution_token: string }) | null }>(
      '/internal/agent/claim-next', this.#hostKey, { host_id: hostId, config_id: configId });
    if (!result.grant) return null;
    const { execution_token, ...grant } = result.grant;
    this.#token = execution_token; this.#hostKey = ''; this.#grant = grant;
    return structuredClone(grant);
  }

  #path(suffix: string) {
    if (!this.#grant || !this.#token) throw new Error('HOST_NOT_CLAIMED');
    return `/internal/agent/runs/${encodeURIComponent(this.#grant.run_id)}/${suffix}`;
  }

  async invoke(toolCallId: string, tool: string, args: unknown): Promise<InvocationOutput> {
    if (!this.#grant?.allowed_tools.includes(tool)) throw new Error('TOOL_NOT_GRANTED');
    let requestKey = this.#registrations.get(toolCallId);
    if (!requestKey) { requestKey = randomUUID(); this.#registrations.set(toolCallId, requestKey); }
    const body = { request_key: requestKey, tool_call_id: toolCallId, tool_name: tool, arguments: args };
    // A restarted host never reconstructs registration keys from tool-call IDs.
    return this.#retryRequest<InvocationOutput>(this.#path('invocations'), body);
  }

  async reconcile(invocationId: string) {
    return this.#request<InvocationOutput>(this.#path(`invocations/${encodeURIComponent(invocationId)}`), this.#token);
  }
  async heartbeat() { return this.#request(this.#path('heartbeat'), this.#token, {}); }
  async renew() {
    const value = await this.#retryRequest<{ execution_token: string; credential_expires_at: string }>(this.#path('renew'), {});
    this.#token = value.execution_token;
    return { credential_expires_at: value.credential_expires_at };
  }
  async event(kind: 'sdk.agent_end' | 'sdk.agent_settled') {
    return this.#retryRequest(this.#path('events'), { event_id: randomUUID(), kind });
  }
  async downloadCheckpoint() {
    return this.#request<CheckpointDownload>(this.#path('checkpoint'), this.#token);
  }
  async uploadCheckpoint(sessionJsonl: string): Promise<Checkpoint> {
    if (new TextEncoder().encode(sessionJsonl).byteLength > 8 * 1024 * 1024) throw new Error('CHECKPOINT_TOO_LARGE');
    return this.#retryRequest<Checkpoint>(this.#path('checkpoint'), {
      request_key: randomUUID(), base_checkpoint_id: this.#grant?.base_checkpoint?.checkpoint_id ?? null,
      runtime_manifest: this.#grant?.runtime_manifest, session_jsonl: sessionJsonl,
    });
  }
  async settle(checkpointId: string | null = null) {
    return this.#retryRequest<{ state: string; reason: string | null }>(this.#path('settle'), { checkpoint_id: checkpointId });
  }
  async suspend(checkpointId: string) {
    return this.#retryRequest<{ state: string; reason: string | null }>(this.#path('suspend'), { checkpoint_id: checkpointId });
  }
  async review(reason: 'CHECKPOINT_RESTORE_FAILED' | 'SDK_CONTEXT_UNCERTAIN' | 'JOB_NOT_SUCCEEDED' | 'MODEL_AUTH_FAILED' | 'MODEL_RATE_LIMITED' | 'MODEL_TIMEOUT' | 'MODEL_REQUEST_FAILED' | 'MODEL_RESPONSE_INVALID') {
    return this.#request<{ state: string; reason: string }>(this.#path('review'), this.#token, { reason });
  }
  dispose() { this.#token = ''; this.#hostKey = ''; this.#registrations.clear(); }
}
