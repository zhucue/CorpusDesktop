/** OpenAI-compatible model via Pi's built-in providers (openai-completions / openai-responses). */
import { InMemoryCredentialStore, type Api, type AssistantMessage, type Model } from '@earendil-works/pi-ai';
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

/** Token counts of one model call (contracts/p9.md §二); `estimated` when the response carried no usage. */
export interface CallUsage { prompt_tokens: number; completion_tokens: number; total_tokens: number; estimated: boolean }

/** Characters of message content: text, thinking, tool name and arguments (images count 0). */
function contentChars(content: unknown): number {
  if (typeof content === 'string') return content.length;
  if (!Array.isArray(content)) return 0;
  return content.reduce((sum: number, block: any) => sum + (
    block?.type === 'text' ? String(block.text ?? '').length
      : block?.type === 'thinking' ? String(block.thinking ?? '').length
        : block?.type === 'toolCall' ? String(block.name ?? '').length + JSON.stringify(block.arguments ?? {}).length
          : 0), 0);
}

/** Characters of the request: every message's content, plus prompt sections and tool schemas of system messages. */
function promptChars(messages: unknown): number {
  if (!Array.isArray(messages)) return 0;
  return messages.reduce((sum: number, message: any) => sum + contentChars(message?.content)
    + Object.values(message?.sections ?? {}).reduce((n: number, text) => n + (typeof text === 'string' ? text.length : 0), 0)
    + (message?.toolsAdded ? JSON.stringify(message.toolsAdded).length : 0), 0);
}

/**
 * Usage of one call: the provider's `usage` (Pi asks for it with stream_options.include_usage on
 * openai-completions and reads it from response.completed on openai-responses); without it,
 * characters / 2. null when the call produced and reported nothing (failed or stopped before any
 * output): no row is written.
 */
export function callUsage(messages: unknown, message: AssistantMessage): CallUsage | null {
  const usage = message.usage;
  if (usage && usage.totalTokens > 0) {
    const prompt = usage.input + usage.cacheRead + usage.cacheWrite;
    return { prompt_tokens: prompt, completion_tokens: usage.output, total_tokens: prompt + usage.output, estimated: false };
  }
  const output = contentChars(message.content);
  if (!output) return null;
  const prompt = Math.ceil(promptChars(messages) / 2);
  const completion = Math.ceil(output / 2);
  return { prompt_tokens: prompt, completion_tokens: completion, total_tokens: prompt + completion, estimated: true };
}

/**
 * Records the HTTP status of model requests so a failed run can be mapped to a
 * MODEL_* code. Also disables provider-side retries and applies the timeout.
 * `onCall` receives the usage of every finished model call of the session.
 */
export function trackModelRequests(session: AgentSession, config: ModelConfig, onCall?: (usage: CallUsage, model: string) => void) {
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
  session.agent.streamFunction = async (model, context, options) => {
    const stream = await original(model, context, { ...options, fetch: tracked, maxRetries: 0, timeoutMs: config.timeoutMs });
    if (onCall) {
      stream.result().then(message => {
        const usage = callUsage(context.messages, message);
        if (usage) onCall(usage, message.model || model.id);
      }).catch(error => console.error('model usage', error));
    }
    return stream;
  };

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
