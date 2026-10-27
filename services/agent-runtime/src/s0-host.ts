import { appendFileSync, mkdirSync, readFileSync, existsSync, copyFileSync } from 'node:fs';
import { join } from 'node:path';
import { createAssistantMessageEventStream, InMemoryCredentialStore, type AssistantMessage, type TranscriptContext } from '@earendil-works/pi-ai';
import { createAgentSession, createExtensionRuntime, ModelRuntime, SessionManager, SettingsManager, type ResourceLoader } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';

export const PI_VERSION = '1.3.0';
export const FIXTURE_TOOL = 's0_fixture_read';
export const fixtureResult = {
  invocation_id: 's0-invocation-1', action_id: null, status: 'succeeded',
  scope_ref: { scope_kind: 'project', project_id: 's0-project', snapshot_ids: ['s0-snapshot'], material_revision_ids: [], alignment_overlay_revision: null },
  scope_effect: { kind: 'none' }, version_refs: [], result_ref: 's0-fixture-result-1',
  evidence_refs: ['s0-fixture-evidence-1'],
  method_summary: 'Deterministic SDK fixture; not research evidence.',
  result_view: { kind: 's0_fixture', resource_id: 's0-fixture-result-1' },
};

/** No filesystem discovery, extension loading, skills, prompts, or project instructions. */
export function explicitResources(): ResourceLoader {
  const runtime = createExtensionRuntime();
  return {
    getExtensions: () => ({ extensions: [], errors: [], runtime }),
    getSkills: () => ({ skills: [], diagnostics: [] }),
    getPrompts: () => ({ prompts: [], diagnostics: [] }),
    getThemes: () => ({ themes: [], diagnostics: [] }),
    getAgentsFiles: () => ({ agentsFiles: [] }),
    getSystemPrompt: () => 'Read the S0 fixture using s0_fixture_read. This is a host integration experiment.',
    getSystemPromptSource: () => undefined,
    getAppendSystemPrompt: () => [], getAppendSystemPromptSources: () => [],
    extendResources: () => {}, reload: async () => {},
  };
}

export interface HostOptions {
  directory: string;
  sessionFile?: string;
  retryOnce?: boolean;
  onModelRequest?: (context: TranscriptContext) => void;
  onTool?: () => void;
}

/** Real Pi loop with a registered deterministic provider; never sends a network model request. */
export async function createS0Host(options: HostOptions) {
  mkdirSync(options.directory, { recursive: true });
  const modelRuntime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(), modelsPath: null,
    allowModelNetwork: false, refreshOnCreate: false,
  });
  let requests = 0;
  modelRuntime.registerProvider('corpus-s0-fixture', {
    api: 'openai-completions', baseUrl: 'http://127.0.0.1:1/unused',
    apiKey: 's0-not-a-real-credential',
    models: [{ id: 'fixed-model-v1', name: 'S0 fixed model', input: ['text'], reasoning: false,
      contextWindow: 16000, maxTokens: 1024, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }],
    streamSimple: (model, context) => {
      options.onModelRequest?.(context);
      requests++;
      const stream = createAssistantMessageEventStream();
      const error = options.retryOnce && requests === 1;
      const hasResult = context.messages.some(message => message.role === 'toolResult');
      const message: AssistantMessage = {
        role: 'assistant', api: model.api, provider: model.provider, model: model.id,
        timestamp: Date.now(), usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
        stopReason: error ? 'error' : hasResult ? 'stop' : 'toolUse',
        content: error ? [] : hasResult
          ? [{ type: 'text', text: 'S0 fixture returned: s0-fixture-evidence-1.' }]
          : [{ type: 'toolCall', id: 's0-call-1', name: FIXTURE_TOOL, arguments: { fixture_id: 'sample' } }],
        ...(error ? { errorMessage: '503 service unavailable: deterministic S0 retry fixture' } : {}),
      };
      queueMicrotask(() => {
        stream.push({ type: 'start', partial: message });
        if (error) stream.push({ type: 'error', reason: 'error', error: message });
        else stream.push({ type: 'done', reason: message.stopReason as 'stop' | 'toolUse', message });
        stream.end(message);
      });
      return stream;
    },
  });
  const model = modelRuntime.getModel('corpus-s0-fixture', 'fixed-model-v1');
  if (!model) throw new Error('S0_MODEL_NOT_REGISTERED');
  // Archives are immutable. Open an attempt-local copy; Pi appends to its opened file.
  const localContext = join(options.directory, 'restored-context.jsonl');
  if (options.sessionFile && options.sessionFile !== localContext) copyFileSync(options.sessionFile, localContext);
  const sessionManager = options.sessionFile
    ? SessionManager.open(localContext, join(options.directory, 'sessions'), options.directory)
    : SessionManager.create(options.directory, join(options.directory, 'sessions'));
  const { session } = await createAgentSession({
    cwd: options.directory, agentDir: join(options.directory, 'agent'),
    modelRuntime, model, thinkingLevel: 'off', resourceLoader: explicitResources(),
    settingsManager: SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: true, maxRetries: 1, baseDelayMs: 1 } }),
    sessionManager, tools: [FIXTURE_TOOL],
    customTools: [{ name: FIXTURE_TOOL, label: 'S0 fixture', description: 'Read the fixed, non-research SDK fixture.',
      parameters: Type.Object({ fixture_id: Type.Literal('sample') }, { additionalProperties: false }),
      execute: async () => {
        options.onTool?.();
        return { content: [{ type: 'text' as const, text: JSON.stringify(fixtureResult) }], details: fixtureResult };
      },
    }],
  });
  const eventPath = join(options.directory, 'events.jsonl');
  const events: { sequence: number; kind: string; payload: unknown }[] = existsSync(eventPath)
    ? readFileSync(eventPath, 'utf8').trim().split('\n').filter(Boolean).map(line => JSON.parse(line))
    : [];
  session.subscribe(event => {
    const entry = { sequence: events.length + 1, kind: event.type, payload: event };
    events.push(entry);
    appendFileSync(eventPath, JSON.stringify(entry) + '\n', { encoding: 'utf8', flush: true });
  });
  return { session, sessionManager, events, eventPath, requests: () => requests };
}

/** Missing tool results must be reconciled by the business authority before continuation. */
export function recoveryReadiness(messages: readonly { role: string; content?: unknown; toolCallId?: string }[]): 'READY' | 'WAITING_REVIEW' {
  const completed = new Set(messages.filter(message => message.role === 'toolResult').map(message => message.toolCallId));
  for (const message of messages) {
    if (message.role !== 'assistant' || !Array.isArray(message.content)) continue;
    for (const item of message.content) if (item.type === 'toolCall' && !completed.has(item.id)) return 'WAITING_REVIEW';
  }
  return 'READY';
}
