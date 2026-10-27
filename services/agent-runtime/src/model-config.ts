/** Server-owned model configuration. No credential is included in its identity. */
import { createHash } from 'node:crypto';
import { RUNTIME_MANIFEST, type RuntimeManifest } from './s1-run-client.ts';

export interface ModelConfiguration {
  api: 'openai-completions' | 'openai-responses'; baseUrl: string; model: string;
  contextWindow: number; maxOutputTokens: number; requestTimeoutMs: number;
  allowLoopbackHttp: boolean; sha256: string; configId: string; manifest: RuntimeManifest;
}
function invalid(): never { throw new Error('MODEL_CONFIGURATION_INVALID'); }
function integer(value: string | undefined, fallback: number, minimum: number, maximum: number) {
  if (value === undefined) return fallback;
  if (!/^[0-9]+$/.test(value)) invalid();
  const result = Number(value);
  if (!Number.isSafeInteger(result) || result < minimum || result > maximum) invalid();
  return result;
}
export function modelConfiguration(env: NodeJS.ProcessEnv): ModelConfiguration {
  const rawApi = env.AGENT_MODEL_API ?? '';
  if (!/^[\x00-\x7f]*$/.test(rawApi)) invalid();
  const api = rawApi.trim();
  if (api !== 'openai-completions' && api !== 'openai-responses') invalid();
  const rawUrl = env.AGENT_MODEL_BASE_URL ?? '';
  const rawModel = env.AGENT_MODEL_ID ?? '';
  if (!/^[\x00-\x7f]*$/.test(rawUrl + rawModel)) invalid();
  const baseUrl = rawUrl.trim().replace(/\/+$/, '');
  const model = env.AGENT_MODEL_ID?.trim() ?? '';
  if (!baseUrl || !model || !/^[\x21-\x7e]+$/.test(baseUrl) || !/^[\x20-\x7e]+$/.test(model) ||
      /[\\?#]/.test(baseUrl) || !/^https?:\/\//i.test(baseUrl)) invalid();
  const authority = baseUrl.split('://')[1]?.split('/')[0] ?? '';
  if (authority.includes('@')) invalid();
  const rawHost = authority.startsWith('[') ? authority.slice(0, authority.indexOf(']') + 1) : authority.split(':')[0];
  const allowValue = env.AGENT_MODEL_ALLOW_LOOPBACK_HTTP ?? 'false';
  if (!['true', 'false'].includes(allowValue)) invalid();
  const allowLoopbackHttp = allowValue === 'true';
  let url: URL;
  try { url = new URL(baseUrl); } catch { return invalid(); }
  if (url.username || url.password || !url.hostname ||
      !(url.protocol === 'https:' || (allowLoopbackHttp && url.protocol === 'http:' &&
        ['127.0.0.1', '[::1]', 'localhost'].includes(rawHost.toLowerCase())))) invalid();
  const contextWindow = integer(env.AGENT_MODEL_CONTEXT_WINDOW, 8192, 1024, 1048576);
  const maxOutputTokens = integer(env.AGENT_MODEL_MAX_OUTPUT_TOKENS, 1024, 1, contextWindow);
  if (maxOutputTokens > contextWindow) invalid();
  const requestTimeoutMs = integer(env.AGENT_MODEL_REQUEST_TIMEOUT_MS, 60000, 1000, 120000);
  const sha256 = createHash('sha256').update(JSON.stringify(['openai-compatible-v1', api, baseUrl, model,
    contextWindow, maxOutputTokens, requestTimeoutMs, allowLoopbackHttp])).digest('hex');
  return { api, baseUrl, model, contextWindow, maxOutputTokens, requestTimeoutMs, allowLoopbackHttp,
    sha256, configId: `openai-${sha256.slice(0, 48)}`,
    manifest: { ...RUNTIME_MANIFEST, host_policy: 'corpus-k09-openai-v1', provider: 'corpus-openai-compatible',
      model, resource_config: 'corpus-explicit-resources-v1', model_api: api, model_config_sha256: sha256 } };
}
