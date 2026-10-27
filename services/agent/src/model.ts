/** OpenAI-compatible model via Pi's built-in providers (openai-completions / openai-responses). */
import { InMemoryCredentialStore, type Api, type Model } from '@earendil-works/pi-ai';
import { ModelRuntime, type AgentSession } from '@earendil-works/pi-coding-agent';
import type { ModelConfig } from './config.ts';

export const PROVIDER = 'corpus-model';

export type ModelErrorCode = 'MODEL_AUTH_FAILED' | 'MODEL_RATE_LIMITED' | 'MODEL_TIMEOUT' | 'MODEL_REQUEST_FAILED';

export interface ModelHandle {
  config: ModelConfig;
  runtime: ModelRuntime;
  model: Model<Api>;
}

export async function createModel(config: ModelConfig): Promise<ModelHandle> {
  const runtime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(), modelsPath: null, allowModelNetwork: false, refreshOnCreate: false,
  });
  runtime.registerProvider(PROVIDER, {
    api: config.api,
    baseUrl: config.baseUrl,
    models: [{
      id: config.id, name: config.id, input: ['text'], reasoning: config.reasoning,
      contextWindow: config.contextWindow, maxTokens: config.maxTokens,
      ...(config.api === 'openai-completions' ? { compat: { maxTokensField: 'max_tokens' as const } } : {}),
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    }],
  });
  await runtime.setRuntimeApiKey(PROVIDER, config.apiKey);
  const model = runtime.getModel(PROVIDER, config.id);
  if (!model) throw new Error(`model ${config.id} not registered`);
  return { config, runtime, model };
}

/**
 * Records the HTTP status of model requests so a failed run can be mapped to a
 * MODEL_* code. Also disables provider-side retries and applies the timeout.
 */
export function trackModelRequests(session: AgentSession, config: ModelConfig) {
  const seen: { status?: number; error?: unknown } = {};
  const tracked: typeof fetch = async (input, init) => {
    try {
      const response = await fetch(input, init);
      seen.status = response.status;
      return response;
    } catch (error) {
      seen.error = error;
      throw error;
    }
  };
  const original = session.agent.streamFunction;
  session.agent.streamFunction = (model, context, options) =>
    original(model, context, { ...options, fetch: tracked, maxRetries: 0, timeoutMs: config.timeoutMs });

  return function classify(errorMessage: string | undefined): ModelErrorCode {
    if (seen.status === 401 || seen.status === 403) return 'MODEL_AUTH_FAILED';
    if (seen.status === 429) return 'MODEL_RATE_LIMITED';
    const name = (seen.error as Error | undefined)?.name;
    if (name === 'TimeoutError' || /time(d)?\s?out/i.test(errorMessage ?? '')) return 'MODEL_TIMEOUT';
    return 'MODEL_REQUEST_FAILED';
  };
}

export const MODEL_ERROR_TEXT: Record<ModelErrorCode, string> = {
  MODEL_AUTH_FAILED: '模型服务拒绝了密钥，请检查 MODEL_API_KEY',
  MODEL_RATE_LIMITED: '模型服务限流，请稍后重试',
  MODEL_TIMEOUT: '模型服务响应超时，请稍后重试',
  MODEL_REQUEST_FAILED: '模型请求失败',
};
