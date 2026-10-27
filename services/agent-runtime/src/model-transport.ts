/** Guard the SDK's built-in HTTP adapters; no custom protocol or SSE parser. */
import { createAssistantMessageEventStream, type AssistantMessage, type Model, type Api } from '@earendil-works/pi-ai';
import type { AgentSession } from '@earendil-works/pi-coding-agent';
import type { ModelConfiguration } from './model-config.ts';

export type ModelFailureCode = 'MODEL_AUTH_FAILED' | 'MODEL_RATE_LIMITED' | 'MODEL_TIMEOUT' | 'MODEL_REQUEST_FAILED' | 'MODEL_RESPONSE_INVALID';
export class ModelRequestError extends Error {
  readonly code: ModelFailureCode;
  constructor(code: ModelFailureCode) { super(code); this.code = code; }
}
function blank(model: Model<Api>, code: ModelFailureCode, aborted = false): AssistantMessage {
  return { role: 'assistant', api: model.api, provider: model.provider, model: model.id, timestamp: Date.now(),
    content: [], stopReason: aborted ? 'aborted' : 'error', errorMessage: code,
    usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
}

export function guardModelStream(original: AgentSession['agent']['streamFunction'], config: ModelConfiguration, options: {
  apiKey: string; beforeRequest: () => Promise<void>; onFailure: (error: unknown) => void;
  fetcher?: typeof fetch;
}): AgentSession['agent']['streamFunction'] {
  const endpoint = new URL(config.baseUrl + (config.api === 'openai-completions' ? '/chat/completions' : '/responses')).href;
  const fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis);
  return (model, context, sdkOptions) => {
    const stream = createAssistantMessageEventStream();
    const controller = new AbortController();
    const signal = sdkOptions?.signal ? AbortSignal.any([sdkOptions.signal, controller.signal]) : controller.signal;
    let failure: ModelFailureCode | undefined;
    let receivedResponse = false;
    const timer = setTimeout(() => { failure = 'MODEL_TIMEOUT'; controller.abort(); }, config.requestTimeoutMs);
    timer.unref();
    const guardedFetch: typeof fetch = async (input, init) => {
      const target = new URL(input instanceof Request ? input.url : String(input)).href;
      if (target !== endpoint) throw new ModelRequestError('MODEL_REQUEST_FAILED');
      try {
        const response = await fetcher(input, { ...init, redirect: 'error', credentials: 'omit', signal });
        receivedResponse = true;
        if (!response.ok) {
          failure = [401, 403].includes(response.status) ? 'MODEL_AUTH_FAILED' : response.status === 429 ? 'MODEL_RATE_LIMITED' : 'MODEL_REQUEST_FAILED';
          // Neither upstream response bodies nor headers may enter SDK errors or archives.
          await response.body?.cancel();
          return Response.json({ error: { message: failure, type: failure, code: failure } }, { status: response.status });
        }
        return response;
      } catch {
        failure ??= 'MODEL_REQUEST_FAILED';
        throw new ModelRequestError(failure);
      }
    };
    void (async () => {
      let terminal = false;
      try {
        signal.throwIfAborted();
        await options.beforeRequest();
        signal.throwIfAborted();
        const source = await original(model, context, { ...sdkOptions, signal, fetch: guardedFetch,
          apiKey: options.apiKey, transport: 'sse', cacheRetention: 'none', maxRetries: 0,
          timeoutMs: config.requestTimeoutMs, maxTokens: config.maxOutputTokens });
        for await (const event of source) {
          if (event.type === 'error') throw new ModelRequestError(failure ?? (receivedResponse ? 'MODEL_RESPONSE_INVALID' : 'MODEL_REQUEST_FAILED'));
          // A provider may mutate a prior partial when its error arrives. Copy before
          // forwarding so raw provider error metadata cannot leak into SDK history.
          const safe = structuredClone(event);
          if (JSON.stringify(safe).includes(options.apiKey)) throw new ModelRequestError('MODEL_RESPONSE_INVALID');
          if ('partial' in safe) delete safe.partial.errorMessage;
          if (safe.type === 'done') {
            if (!['stop', 'toolUse'].includes(safe.message.stopReason)) throw new ModelRequestError('MODEL_RESPONSE_INVALID');
            delete safe.message.errorMessage;
            terminal = true;
          }
          stream.push(safe);
        }
        if (!terminal) throw new ModelRequestError('MODEL_RESPONSE_INVALID');
        stream.end();
      } catch (error) {
        controller.abort();
        const safeError = error instanceof ModelRequestError ? error : new ModelRequestError(failure ?? 'MODEL_REQUEST_FAILED');
        options.onFailure(safeError);
        const message = blank(model, safeError.code, sdkOptions?.signal?.aborted === true);
        stream.push({ type: 'error', reason: message.stopReason === 'aborted' ? 'aborted' : 'error', error: message });
        stream.end(message);
      } finally { clearTimeout(timer); }
    })();
    return stream;
  };
}
