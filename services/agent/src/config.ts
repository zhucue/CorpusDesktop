/** Environment configuration (contracts/p2.md §五 身份与配置). */
import { join } from 'node:path';

export type ModelApi = 'openai-completions' | 'openai-responses';

export interface ModelConfig {
  baseUrl: string;
  apiKey: string;
  id: string;
  api: ModelApi;
  contextWindow: number;
  maxTokens: number;
  timeoutMs: number;
  reasoning: boolean;
}

export interface Config {
  port: number;
  apiBaseUrl: string;
  databaseUrl: string;
  dataDir: string;
  publicOrigin: string | undefined;
  /** null when MODEL_BASE_URL / MODEL_ID are not set: health reports MODEL_NOT_CONFIGURED. */
  model: ModelConfig | null;
  jobPollMs: number;
  jobWaitMs: number;
}

function int(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return value && Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

export function modelConfig(env: NodeJS.ProcessEnv): ModelConfig | null {
  const baseUrl = env.MODEL_BASE_URL?.trim().replace(/\/+$/, '');
  const id = env.MODEL_ID?.trim();
  if (!baseUrl || !id) return null;
  const api = (env.MODEL_API?.trim() || 'openai-completions') as ModelApi;
  if (api !== 'openai-completions' && api !== 'openai-responses') {
    throw new Error(`MODEL_API must be openai-completions or openai-responses, got ${api}`);
  }
  return {
    baseUrl, id, api,
    apiKey: env.MODEL_API_KEY?.trim() || 'none',
    contextWindow: int(env.MODEL_CONTEXT_WINDOW, 128000),
    maxTokens: int(env.MODEL_MAX_TOKENS, 8192),
    timeoutMs: int(env.MODEL_TIMEOUT_MS, 120000),
    reasoning: env.MODEL_REASONING === 'true',
  };
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const apiBaseUrl = env.API_BASE_URL?.trim().replace(/\/+$/, '');
  if (!apiBaseUrl) throw new Error('API_BASE_URL is required, e.g. http://api:8000/api');
  const databaseUrl = env.DATABASE_URL?.trim();
  if (!databaseUrl) throw new Error('DATABASE_URL is required');
  return {
    port: int(env.PORT, 8700),
    apiBaseUrl,
    // compose shares the SQLAlchemy URL (postgresql+psycopg://); pg wants postgresql://
    databaseUrl: databaseUrl.replace(/^postgres(ql)?\+\w+:/, 'postgresql:'),
    dataDir: env.DATA_DIR?.trim() || join(process.cwd(), 'data'),
    publicOrigin: env.PUBLIC_ORIGIN?.trim() || undefined,
    model: modelConfig(env),
    jobPollMs: 2000,
    jobWaitMs: 90000,
  };
}
