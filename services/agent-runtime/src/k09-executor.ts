/** One leased SDK segment. Only explicit test configuration enables this provider. */
import { createHash, randomUUID } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { createAssistantMessageEventStream, InMemoryCredentialStore, type AssistantMessage, type ToolCall } from '@earendil-works/pi-ai';
import { createAgentSession, ModelRuntime, SettingsManager } from '@earendil-works/pi-coding-agent';
import { explicitResources } from './s0-host.ts';
import { executionTools } from './s1-run-host.ts';
import { RUNTIME_MANIFEST, RunProtocolError, type Grant, type InvocationOutput, type S1RunClient } from './s1-run-client.ts';
import { assertRuntime, openCheckpoint, sessionArchive, verifyArchive } from './s1-run-checkpoint.ts';
import type { ModelConfiguration } from './model-config.ts';
import { guardModelStream, ModelRequestError } from './model-transport.ts';

export type FixtureScenario = { kind: 'complete-upload'; uploadId: string };
const READ_REPORTS = new Set(['jobs.get', 'imports.get', 'snapshots.get', 'corpus.describe', 'sync.report', 'indexes.report', 'exports.get']);

export function fixtureCalls(grant: Grant, scenario?: FixtureScenario) {
  if (typeof grant.user_message !== 'string' || !grant.user_message || grant.user_message.length > 8000 ||
      grant.config_id !== 'local-fixture-v1') throw new Error('FIXTURE_GRANT_INVALID');
  if (scenario && (scenario.kind !== 'complete-upload' ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(scenario.uploadId) ||
      grant.user_message !== `fixture:complete-upload:${scenario.uploadId}` || grant.scope.scope_kind !== 'project')) {
    throw new Error('FIXTURE_INTENT_MISMATCH');
  }
  if (grant.resume_checkpoint) {
    if (!grant.continuation_message || !grant.waiting_jobs?.length) throw new Error('RESUME_GRANT_INVALID');
    return grant.waiting_jobs.map(job => {
      if (!['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(job.state)) throw new Error('WAITING_JOB_NOT_TERMINAL');
      if (!READ_REPORTS.has(job.report_tool) || !grant.allowed_tools.includes(job.report_tool)) throw new Error('WAITING_REPORT_NOT_ALLOWED');
      return { tool: job.report_tool, args: job.report_arguments };
    });
  }
  if (grant.continuation_message) throw new Error('RESUME_GRANT_INVALID');
  // The daemon has no scenario: every ordinary message is a non-writing fixture
  // acknowledgement. Writes are possible only via the trusted smoke stdin option.
  return scenario ? [{ tool: 'uploads.complete', args: { upload_id: scenario.uploadId } }] : [];
}

export interface SegmentOptions {
  client: S1RunClient; grant: Grant; directory: string; scenario?: FixtureScenario;
  signal?: AbortSignal;
  onActivity?: () => void;
  provider?: { config: ModelConfiguration; apiKey: string };
}

/** Fixture and configured models share the exact same leased business lifecycle. */
export async function executeSegment(options: SegmentOptions) {
  const { client, grant } = options;
  // The dedicated host never enables provider diagnostics that may include bodies.
  if (options.provider) process.env.OPENAI_LOG = 'off';
  const manifest = options.provider?.config.manifest ?? RUNTIME_MANIFEST;
  if (options.provider && (!options.provider.apiKey || options.scenario || grant.config_id !== options.provider.config.configId)) {
    throw new Error('MODEL_CONFIGURATION_INVALID');
  }
  mkdirSync(options.directory, { recursive: true });
  const directory = mkdtempSync(join(options.directory, `run-${grant.run_id}-epoch-${grant.lease_epoch}-`));
  let restored;
  let calls;
  try {
    assertRuntime(grant, manifest);
    restored = openCheckpoint(grant, await client.downloadCheckpoint(), directory, manifest);
  } catch (error) {
    await client.review('CHECKPOINT_RESTORE_FAILED').catch(() => {});
    throw error;
  }
  try {
    if (!grant.user_message || grant.user_message.length > 8000 ||
        Boolean(grant.resume_checkpoint) !== Boolean(grant.continuation_message)) throw new Error('RESUME_GRANT_INVALID');
    calls = options.provider ? [] : fixtureCalls(grant, options.scenario);
    if (calls.length > 32) throw new Error('FIXTURE_TOO_MANY_REPORTS');
  } catch (error) {
    await client.review('SDK_CONTEXT_UNCERTAIN').catch(() => {});
    throw error;
  }
  const tools = executionTools(client, grant);
  if (calls.some(call => !tools.some(tool => tool.capability_id === call.tool))) {
    await client.review('SDK_CONTEXT_UNCERTAIN').catch(() => {});
    throw new Error('TOOL_NOT_GRANTED');
  }
  const planned = calls.map(call => ({ ...call, id: `k09-${grant.lease_epoch}-${randomUUID()}` }));
  const runtime = await ModelRuntime.create({ credentials: new InMemoryCredentialStore(), modelsPath: null,
    allowModelNetwork: false, refreshOnCreate: false });
  let requests = 0;
  let providerFailure: unknown;
  if (options.provider) {
    const config = options.provider.config;
    runtime.registerProvider(manifest.provider, { api: config.api, baseUrl: config.baseUrl,
      models: [{ id: config.model, name: config.model, input: ['text'], reasoning: false,
        contextWindow: config.contextWindow, maxTokens: config.maxOutputTokens,
        ...(config.api === 'openai-completions' ? { compat: { maxTokensField: 'max_tokens' as const } } : {}),
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] });
    await runtime.setRuntimeApiKey(manifest.provider, options.provider.apiKey);
  } else runtime.registerProvider(RUNTIME_MANIFEST.provider, {
    api: 'openai-completions', baseUrl: 'http://127.0.0.1:1/unused', apiKey: 'fixture-no-secret',
    models: [{ id: RUNTIME_MANIFEST.model, name: 'Local lifecycle fixture', input: ['text'], reasoning: false,
      contextWindow: 16000, maxTokens: 1024, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }],
    streamSimple: (model, context) => {
      const stream = createAssistantMessageEventStream();
      void (async () => {
        const blank = (): AssistantMessage => ({ role: 'assistant', api: model.api, provider: model.provider, model: model.id,
          timestamp: Date.now(), content: [], stopReason: 'stop',
          usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } });
        try {
          options.signal?.throwIfAborted();
          await client.heartbeat();
          options.onActivity?.();
          requests++;
          const next = planned.find(call => !context.messages.some(message => message.role === 'toolResult' && message.toolCallId === call.id));
          const message = blank();
          message.stopReason = next ? 'toolUse' : 'stop';
          message.content = next
            ? [{ type: 'toolCall', id: next.id, name: next.tool.replaceAll('.', '_'), arguments: next.args as ToolCall['arguments'] }]
            : [{ type: 'text', text: planned.length ? 'Local fixture segment finished; business completion is determined by the server.' : 'Local fixture received the message. No model is configured and no business action was performed.' }];
          stream.push({ type: 'start', partial: message });
          stream.push({ type: 'done', reason: next ? 'toolUse' : 'stop', message }); stream.end(message);
        } catch (error) {
          providerFailure = error;
          const failed = { ...blank(), stopReason: 'error' as const, errorMessage: 'FIXTURE_EXECUTION_STOPPED' };
          stream.push({ type: 'error', reason: 'error', error: failed }); stream.end(failed);
        }
      })();
      return stream;
    },
  });
  const model = runtime.getModel(manifest.provider, manifest.model);
  if (!model) throw new Error('FIXTURE_MODEL_MISSING');
  const resourceLoader = explicitResources();
  resourceLoader.getSystemPrompt = () => options.provider
    ? 'You are a research workspace assistant. Use only the granted business tools. Empty material scope: do not claim access to corpus text. A tool result with status accepted starts a persistent business job: explain that it is waiting and end this segment; do not poll or resubmit it. When the server resumes a waiting job, call its specified report tool to observe the actual result before continuing. Never infer success from a job identifier. Do not repeat an existing write.'
    : 'Local fixed-provider lifecycle test. No external model, research interpretation, or inferred business action.';
  const { session } = await createAgentSession({ cwd: directory, agentDir: join(directory, 'agent'),
    modelRuntime: runtime, model, thinkingLevel: 'off', resourceLoader,
    settingsManager: SettingsManager.inMemory({ compaction: { enabled: false }, cacheWarming: 'off',
      retry: { enabled: false, provider: { maxRetries: 0, timeoutMs: options.provider?.config.requestTimeoutMs ?? 60000 } } }),
    sessionManager: restored.manager, tools: tools.map(tool => tool.name), customTools: tools });
  if (options.provider) {
    session.agent.streamFunction = guardModelStream(session.agent.streamFunction, options.provider.config, {
      apiKey: options.provider.apiKey,
      beforeRequest: async () => {
        if (requests >= 16) throw new ModelRequestError('MODEL_REQUEST_FAILED');
        options.signal?.throwIfAborted();
        await client.heartbeat();
        options.onActivity?.();
        requests++;
      },
      onFailure: error => { providerFailure = error; },
    });
  }
  const events: string[] = [];
  let aborted = false;
  let failed: unknown;
  let eventsPending = Promise.resolve();
  session.subscribe(event => {
    events.push(event.type);
    if (event.type === 'agent_settled') aborted ||= event.aborted;
    if (event.type === 'agent_end' || event.type === 'agent_settled') {
      const kind = event.type === 'agent_end' ? 'sdk.agent_end' : 'sdk.agent_settled';
      eventsPending = eventsPending.then(async () => { await client.event(kind); }).catch(error => { failed = error; });
    }
  });
  const abort = () => { aborted = true; void session.abort(); };
  options.signal?.addEventListener('abort', abort, { once: true });
  const deadline = setTimeout(abort, 900000); deadline.unref();
  let heartbeatPending = Promise.resolve();
  let renewedAt = Date.now();
  const timer = setInterval(() => {
    heartbeatPending = heartbeatPending.then(async () => {
      await client.heartbeat();
      options.onActivity?.();
      if (Date.now() - renewedAt >= 120000) { await client.renew(); renewedAt = Date.now(); }
    }).catch(error => { failed = error; abort(); });
  }, 15000); timer.unref();
  try {
    const inherited = session.messages.length;
    options.signal?.throwIfAborted();
    await session.prompt(grant.continuation_message ?? grant.user_message!);
    await session.waitForIdle();
    await heartbeatPending;
    await eventsPending;
    if (providerFailure) throw providerFailure;
    if (failed) throw failed;
    if (aborted || options.signal?.aborted || events.at(-1) !== 'agent_settled') throw new Error('SDK_NOT_SETTLED');
    const messages = session.messages.slice(inherited).filter(message => message.role === 'toolResult');
    for (const message of messages) {
      options.signal?.throwIfAborted();
      if (aborted) throw new Error('SDK_NOT_SETTLED');
      const output = 'details' in message ? message.details as unknown as InvocationOutput : undefined;
      if (!output?.result.invocation_id) throw new Error('INVOCATION_RESULT_MISSING');
      if (!isDeepStrictEqual(await client.reconcile(output.result.invocation_id), output)) throw new Error('RECONCILIATION_MISMATCH');
    }
    const archive = sessionArchive(restored.manager);
    options.signal?.throwIfAborted();
    const checkpoint = await client.uploadCheckpoint(archive);
    verifyArchive(checkpoint, archive, manifest);
    const effective = grant.resume_checkpoint ?? grant.base_checkpoint;
    if (restored.immutablePath && createHash('sha256').update(readFileSync(restored.immutablePath)).digest('hex') !== effective?.sha256) throw new Error('BASE_CHECKPOINT_MODIFIED');
    const accepted = messages.some(message => 'details' in message &&
      (message.details as unknown as InvocationOutput)?.result.status === 'accepted');
    clearInterval(timer);
    await heartbeatPending;
    if (failed) throw failed;
    options.signal?.throwIfAborted();
    if (aborted) throw new Error('SDK_NOT_SETTLED');
    await client.heartbeat();
    options.signal?.throwIfAborted();
    if (aborted) throw new Error('SDK_NOT_SETTLED');
    let final;
    try { final = accepted ? await client.suspend(checkpoint.checkpoint_id) : await client.settle(checkpoint.checkpoint_id); }
    catch (error) {
      if (error instanceof RunProtocolError && error.message === 'JOBS_PENDING') final = await client.suspend(checkpoint.checkpoint_id);
      else throw error;
    }
    if (!['SUCCEEDED', 'WAITING_JOB'].includes(final.state)) throw new Error('UNEXPECTED_RUN_STATE');
    return { run_id: grant.run_id, session_id: grant.session_id, lease_epoch: grant.lease_epoch,
      final, checkpoint, base_checkpoint: grant.base_checkpoint, resume_checkpoint: grant.resume_checkpoint ?? null,
      restored: restored.restored, inherited_messages: inherited, new_tool_executions: messages.length,
      tool_names: messages.map(message => message.toolName), model_requests: requests, events,
      model_network_mode: options.provider ? 'configured_builtin_adapter' : 'disabled_fixed_provider', production_available: false };
  } catch (error) {
    await client.review(error instanceof ModelRequestError ? error.code :
      error instanceof RunProtocolError && error.message === 'JOB_NOT_SUCCEEDED' ? 'JOB_NOT_SUCCEEDED' : 'SDK_CONTEXT_UNCERTAIN').catch(() => {});
    throw error;
  } finally {
    clearInterval(timer); clearTimeout(deadline);
    options.signal?.removeEventListener('abort', abort);
    await heartbeatPending; await eventsPending;
    session.dispose();
  }
}

/** Kept for the original explicitly enabled fixture smoke. */
export function executeFixtureSegment(options: Omit<SegmentOptions, 'provider'>) {
  return executeSegment(options);
}
