/** Real Pi SDK + durable API, deterministic provider only. No model network. */
import { mkdtempSync, mkdirSync, readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { createAssistantMessageEventStream, InMemoryCredentialStore, type AssistantMessage, type TranscriptContext } from '@earendil-works/pi-ai';
import { createAgentSession, ModelRuntime, SettingsManager } from '@earendil-works/pi-coding-agent';
import { Check } from 'typebox/value';
import { CorpusApiClient } from '../../../contracts/types/s1.ts';
import { explicitResources } from './s0-host.ts';
import { createS1ContractTools } from './s1-tools.ts';
import { RUNTIME_MANIFEST, S1RunClient, type Grant, type InvocationOutput } from './s1-run-client.ts';
import { assertRuntime, openCheckpoint, sessionArchive, verifyArchive } from './s1-run-checkpoint.ts';

export function executionTools(client: S1RunClient, grant: Grant) {
  const scope = grant.scope.scope_kind === 'project'
    ? { kind: 'project' as const, projectId: grant.scope.project_id }
    : { kind: grant.scope.scope_kind };
  // Reuse reviewed typed schemas. The contract adapter's cookie transport is
  // deliberately unreachable; every execute is replaced by the fixed API grant.
  const forbiddenClient = new CorpusApiClient({ base: 'http://127.0.0.1:1', csrf: () => undefined,
    transport: (async () => { throw new Error('CONTRACT_TRANSPORT_MUST_NOT_EXECUTE'); }) as typeof fetch });
  return createS1ContractTools(forbiddenClient, { scope, idempotencyKey: () => { throw new Error('SERVER_ASSIGNS_ACTION'); } })
    .filter(tool => grant.allowed_tools.includes(tool.capability_id))
    .map(tool => ({ ...tool, description: `Execute authorized ${tool.capability_id} through the business API.`,
      async execute(toolCallId: string, input: unknown) {
        if (!Check(tool.parameters, input)) throw new Error('INVALID_TOOL_INPUT');
        const result = await client.invoke(toolCallId, tool.capability_id, input);
        return { content: [{ type: 'text' as const, text: JSON.stringify(result) }], details: result };
      },
    }));
}

export async function runFixedModelHost(options: {
  baseUrl: string; hostKey: string; runId: string; directory: string;
  onModelRequest?: (context: TranscriptContext) => void;
  fetcher?: typeof fetch;
}) {
  mkdirSync(options.directory, { recursive: true });
  const client = new S1RunClient({ baseUrl: options.baseUrl, hostKey: options.hostKey, fetcher: options.fetcher });
  const grant = await client.claim(options.runId);
  let restored;
  const directory = mkdtempSync(join(options.directory, `run-${grant.run_id}-epoch-${grant.lease_epoch}-`));
  try {
    assertRuntime(grant);
    restored = openCheckpoint(grant, await client.downloadCheckpoint(), directory);
  } catch (error) {
    await client.review('CHECKPOINT_RESTORE_FAILED').catch(() => {});
    client.dispose();
    throw error;
  }
  const tools = executionTools(client, grant);
  if (!tools.some(tool => tool.name === 'projects_create')) throw new Error('PROJECT_CREATE_NOT_GRANTED');
  const runtime = await ModelRuntime.create({ credentials: new InMemoryCredentialStore(), modelsPath: null,
    allowModelNetwork: false, refreshOnCreate: false });
  let requests = 0;
  let modelFailure: unknown;
  runtime.registerProvider(RUNTIME_MANIFEST.provider, {
    api: 'openai-completions', baseUrl: 'http://127.0.0.1:1/unused', apiKey: 'not-a-model-secret',
    models: [{ id: RUNTIME_MANIFEST.model, name: 'S1 deterministic model', input: ['text'], reasoning: false,
      contextWindow: 16000, maxTokens: 1024, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }],
    streamSimple: (model, context) => {
      const stream = createAssistantMessageEventStream();
      // Validate the active grant and inherited read dependencies before each
      // model request; no transcript is sent to an external provider here.
      void (async () => {
        try {
          await client.heartbeat();
          options.onModelRequest?.(context);
          requests++;
          const projectResult = context.messages.find(message => message.role === 'toolResult' && message.toolName === 'projects_create');
          const hasResult = !!projectResult;
          const projectText = projectResult && Array.isArray(projectResult.content)
            ? projectResult.content.find(item => item.type === 'text') : undefined;
          const prior = projectText?.type === 'text' ? JSON.parse(projectText.text) as InvocationOutput : undefined;
          const projectId = prior?.data && typeof prior.data === 'object' && 'id' in prior.data ? prior.data.id : undefined;
          if (hasResult && (prior?.result.status !== 'succeeded' || typeof projectId !== 'string')) throw new Error('PROJECT_RESULT_INVALID');
          const message: AssistantMessage = { role: 'assistant', api: model.api, provider: model.provider, model: model.id,
            timestamp: Date.now(), usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2,
              cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
            stopReason: hasResult ? 'stop' : 'toolUse', content: hasResult
              ? [{ type: 'text', text: `Existing project ${projectId} is retained in this session; no duplicate project is requested.` }]
              : [{ type: 'toolCall', id: 'fixed-project-create', name: 'projects_create', arguments: { name: 'Pi checkpoint verification' } }],
          };
          stream.push({ type: 'start', partial: message });
          stream.push({ type: 'done', reason: hasResult ? 'stop' : 'toolUse', message }); stream.end(message);
        } catch (error) {
          const failed: AssistantMessage = { role: 'assistant', api: model.api, provider: model.provider, model: model.id,
            timestamp: Date.now(), content: [], stopReason: 'error', errorMessage: 'CONTEXT_AUTHORIZATION_FAILED',
            usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
              cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
          modelFailure = error;
          stream.push({ type: 'error', reason: 'error', error: failed }); stream.end(failed);
        }
      })();
      return stream;
    },
  });
  const model = runtime.getModel(RUNTIME_MANIFEST.provider, RUNTIME_MANIFEST.model);
  if (!model) throw new Error('FIXED_MODEL_MISSING');
  const resourceLoader = explicitResources();
  resourceLoader.getSystemPrompt = () => 'Use the existing project result if present; otherwise call projects_create once. This is a fixed provider checkpoint check, not research.';
  const { session } = await createAgentSession({ cwd: directory, agentDir: join(directory, 'agent'),
    modelRuntime: runtime, model, thinkingLevel: 'off', resourceLoader,
    settingsManager: SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } }),
    sessionManager: restored.manager,
    tools: tools.map(tool => tool.name), customTools: tools,
  });
  const events: string[] = [];
  let aborted = false;
  let pending = Promise.resolve();
  let eventFailure: unknown;
  session.subscribe(event => {
    events.push(event.type);
    if (event.type === 'agent_settled' && event.aborted) aborted = true;
    if (event.type === 'agent_end' || event.type === 'agent_settled') {
      const kind = event.type === 'agent_end' ? 'sdk.agent_end' : 'sdk.agent_settled';
      pending = pending.then(async () => { await client.event(kind); }).catch(error => { eventFailure = error; });
    }
  });
  let heartbeatFailure: unknown;
  let heartbeatPending = Promise.resolve();
  const heartbeat = setInterval(() => {
    heartbeatPending = heartbeatPending.then(async () => { await client.heartbeat(); })
      .catch(error => { heartbeatFailure = error; void session.abort(); });
  }, 15000);
  heartbeat.unref();
  try {
    const inheritedMessages = session.messages.length;
    const inheritedToolResults = session.messages.filter(message => message.role === 'toolResult').length;
    await session.prompt(grant.continuation_message ?? grant.user_message ?? (restored.restored ? 'Continue using the previously created project; do not create another.' : 'Create one project for the checkpoint verification.'));
    clearInterval(heartbeat);
    await heartbeatPending;
    await pending;
    if (modelFailure) throw modelFailure;
    if (eventFailure) throw eventFailure;
    if (heartbeatFailure) throw heartbeatFailure;
    if (aborted || events.at(-1) !== 'agent_settled') throw new Error('SDK_NOT_SETTLED');
    const newToolMessages = session.messages.slice(inheritedMessages).filter(message => message.role === 'toolResult');
    for (const message of newToolMessages) {
      const output = 'details' in message ? message.details as unknown as InvocationOutput : undefined;
      if (!output?.result.invocation_id) throw new Error('INVOCATION_RESULT_MISSING');
      const reconciled = await client.reconcile(output.result.invocation_id);
      if (!isDeepStrictEqual(reconciled, output)) throw new Error('RECONCILIATION_MISMATCH');
    }
    const archive = sessionArchive(restored.manager);
    const checkpoint = await client.uploadCheckpoint(archive);
    verifyArchive(checkpoint, archive);
    if (restored.immutablePath && createHash('sha256').update(readFileSync(restored.immutablePath)).digest('hex') !== grant.base_checkpoint?.sha256) {
      throw new Error('BASE_CHECKPOINT_MODIFIED');
    }
    const final = await client.settle(checkpoint.checkpoint_id);
    const projectMessage = session.messages.find(message => message.role === 'toolResult' && message.toolName === 'projects_create');
    const projectOutput = projectMessage && 'details' in projectMessage ? projectMessage.details as unknown as InvocationOutput : undefined;
    const lastMessage = session.messages.at(-1);
    return { run_id: grant.run_id, session_id: grant.session_id, model_requests: requests,
      invocation_id: projectOutput?.result.invocation_id, project: projectOutput?.data,
      final_model_content: lastMessage?.role === 'assistant' ? lastMessage.content : undefined,
      events, final, restored: restored.restored, inherited_messages: inheritedMessages,
      inherited_tool_results: inheritedToolResults, new_tool_executions: newToolMessages.length,
      base_checkpoint: grant.base_checkpoint, checkpoint,
      model_network_mode: 'disabled_fixed_provider', production_available: false };
  } catch (error) {
    await client.review('SDK_CONTEXT_UNCERTAIN').catch(() => {});
    throw error;
  } finally {
    clearInterval(heartbeat);
    await heartbeatPending;
    session.dispose();
    client.dispose();
  }
}
