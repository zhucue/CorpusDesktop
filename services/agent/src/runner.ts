/**
 * One assistant run per message: Pi session file under DATA_DIR/sessions/<id>/,
 * projected into agent_messages and streamed as SSE events (contracts/p2.md §五).
 * One run per session at a time; runs do not survive a process restart.
 */
import { randomUUID } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import {
  createAgentSession, createExtensionRuntime, SessionManager, SettingsManager,
  type AgentSession, type AgentSessionEvent, type ResourceLoader,
} from '@earendil-works/pi-coding-agent';
import { ApiClient } from './api.ts';
import type { Config } from './config.ts';
import { MODEL_ERROR_TEXT, trackModelRequests, type ModelHandle } from './model.ts';
import { describeScope, systemPrompt } from './prompt.ts';
import type { Store, SessionRecord } from './store.ts';
import { piName, piTools, toolSpecs, type ToolOutput } from './tools.ts';
import type { Message, Part, ToolCall } from './types.ts';
import { FenceSplitter } from './ui-stream.ts';

export type Emit = (event: string, data: unknown) => void;

interface ActiveRun {
  cancelled: boolean;
  session?: AgentSession;
}

export function sessionDir(dataDir: string, sessionId: string) {
  return join(dataDir, 'sessions', sessionId);
}

function explicitResources(prompt: string): ResourceLoader {
  const runtime = createExtensionRuntime();
  return {
    getExtensions: () => ({ extensions: [], errors: [], runtime }),
    getSkills: () => ({ skills: [], diagnostics: [] }),
    getPrompts: () => ({ prompts: [], diagnostics: [] }),
    getThemes: () => ({ themes: [], diagnostics: [] }),
    getAgentsFiles: () => ({ agentsFiles: [] }),
    getSystemPrompt: () => prompt,
    getSystemPromptSource: () => undefined,
    getAppendSystemPrompt: () => [],
    getAppendSystemPromptSources: () => [],
    extendResources: () => {},
    reload: async () => {},
  };
}

const CONTRACT_NAMES = new Map(
  toolSpecs({ api: null as unknown as ApiClient, projectId: '', scope: null, jobPollMs: 0, jobWaitMs: 0 })
    .map(tool => [piName(tool.name), tool.name]),
);

function errorText(result: any): string {
  const text = result?.content?.find?.((item: any) => item.type === 'text')?.text;
  return String(text ?? 'tool failed').slice(0, 300);
}

export class Runner {
  private readonly active = new Map<string, ActiveRun>();
  private readonly config: Config;
  private readonly store: Store;
  private readonly model: ModelHandle | null;

  constructor(config: Config, store: Store, model: ModelHandle | null) {
    this.config = config;
    this.store = store;
    this.model = model;
  }

  isRunning(sessionId: string) {
    return this.active.has(sessionId);
  }

  /** Reserve the session synchronously; false when a run is already active (SESSION_BUSY). */
  reserve(sessionId: string): boolean {
    if (this.active.has(sessionId)) return false;
    this.active.set(sessionId, { cancelled: false });
    return true;
  }

  release(sessionId: string) {
    this.active.delete(sessionId);
  }

  async cancel(sessionId: string) {
    const run = this.active.get(sessionId);
    if (!run) return;
    run.cancelled = true;
    await run.session?.abort();
  }

  /** Executes a reserved run to completion; always releases the reservation. */
  async run(session: SessionRecord, content: string, token: string, emit: Emit): Promise<void> {
    const run = this.active.get(session.id)!;
    const model = this.model!;
    const started = Date.now();
    const userMessage: Message = {
      id: randomUUID(), role: 'user', content, parts: [{ type: 'text', text: content }], tool_calls: [],
      created_at: new Date(started).toISOString(),
    };
    const assistant: Message = {
      id: randomUUID(), role: 'assistant', content: '', parts: [], tool_calls: [],
      created_at: new Date(started + 1).toISOString(), duration_ms: null,
    };
    const parts = assistant.parts;
    const calls = assistant.tool_calls;
    let piSession: AgentSession | undefined;
    let saving: Promise<void> = Promise.resolve();
    const save = () => {
      const snapshot = { content: textOf(parts), parts: structuredClone(parts), tool_calls: structuredClone(calls) };
      saving = saving.then(() => this.store.updateMessage(assistant.id, snapshot)).catch(error => console.error('save message', error));
    };

    try {
      await this.store.insertMessage(session.id, userMessage);
      await this.store.insertMessage(session.id, assistant);
      await this.store.updateSession(session.id, {
        state: 'running', ...(session.title ? {} : { title: content.replace(/\s+/g, ' ').trim().slice(0, 40) }),
      });
      emit('start', { message_id: assistant.id });

      // Part assembly: consecutive deltas of the same type extend the current part;
      // a new assistant turn or a new ```openui-lang fence starts a new part.
      let boundary = true;
      const append = (type: Part['type'], delta: string, newBlock = false) => {
        if (!delta) return;
        const last = parts.at(-1);
        if (last && !boundary && last.type === type && !(type === 'ui' && newBlock)) {
          if (last.type === 'ui') last.lang += delta; else last.text += delta;
        } else {
          parts.push(type === 'ui' ? { type, lang: delta } : { type, text: delta });
        }
        boundary = false;
        emit(type, { delta, part: parts.length - 1 });
      };
      const splitter = new FenceSplitter(chunk => append(chunk.kind, chunk.text, chunk.newBlock));

      const api = new ApiClient(this.config.apiBaseUrl, { bearer: token });
      const toolContext = {
        api, projectId: session.project_id, scope: session.scope,
        jobPollMs: this.config.jobPollMs, jobWaitMs: this.config.jobWaitMs,
      };
      const scopeName = await this.scopeName(api, session).catch(() => null);
      const dir = sessionDir(this.config.dataDir, session.id);
      mkdirSync(dir, { recursive: true });
      const tools = piTools(toolContext);
      ({ session: piSession } = await createAgentSession({
        cwd: dir,
        agentDir: join(this.config.dataDir, 'pi-agent'),
        modelRuntime: model.runtime,
        model: model.model,
        thinkingLevel: model.config.reasoning ? 'medium' : 'off',
        resourceLoader: explicitResources(systemPrompt(describeScope(session.scope, scopeName))),
        settingsManager: SettingsManager.inMemory({ compaction: { enabled: true }, retry: { enabled: false } }),
        sessionManager: SessionManager.continueRecent(dir, dir),
        tools: tools.map(tool => tool.name),
        customTools: tools,
      }));
      run.session = piSession;
      const classify = trackModelRequests(piSession, model.config);
      const startedAt = new Map<string, number>();

      piSession.subscribe((event: AgentSessionEvent) => {
        if (event.type === 'message_start' && event.message.role === 'assistant') boundary = true;
        if (event.type === 'message_update') {
          const update = event.assistantMessageEvent;
          if (update.type === 'text_delta') splitter.push(update.delta);
          else if (update.type === 'text_end') splitter.end();
          else if (update.type === 'thinking_delta') append('thinking', update.delta);
        }
        if (event.type === 'message_end' && event.message.role === 'assistant') splitter.end();
        if (event.type === 'tool_execution_start') {
          startedAt.set(event.toolCallId, Date.now());
          const call: ToolCall = {
            id: event.toolCallId, name: CONTRACT_NAMES.get(event.toolName) ?? event.toolName, args: event.args,
            state: 'running', result_summary: '', duration_ms: 0,
          };
          calls.push(call);
          emit('tool_call', call);
          save();
        }
        if (event.type === 'tool_execution_end') {
          const call = calls.find(item => item.id === event.toolCallId);
          if (!call) return;
          const output = event.result?.details as ToolOutput | undefined;
          call.state = event.isError ? (run.cancelled ? 'cancelled' : 'failed') : 'succeeded';
          call.result_summary = event.isError ? errorText(event.result) : output?.summary ?? '';
          if (!event.isError && output?.ref) call.result_ref = output.ref;
          call.duration_ms = event.durationMs ?? Date.now() - (startedAt.get(event.toolCallId) ?? Date.now());
          emit('tool_result', call);
          save();
        }
      });

      if (!run.cancelled) await piSession.prompt(content);
      splitter.end();

      const last = [...piSession.messages].reverse().find(message => message.role === 'assistant') as
        { stopReason?: string; errorMessage?: string } | undefined;
      const cancelled = run.cancelled || last?.stopReason === 'aborted';
      const failed = !cancelled && last?.stopReason === 'error';
      for (const call of calls) if (call.state === 'running') call.state = cancelled ? 'cancelled' : 'failed';
      assistant.content = textOf(parts);
      assistant.duration_ms = Date.now() - started;
      await saving;
      if (failed && !parts.length && !calls.length) await this.store.deleteMessage(assistant.id);
      else await this.store.updateMessage(assistant.id, assistant);
      if (failed) {
        const code = classify(last?.errorMessage);
        console.error(`run ${session.id} failed: ${code} ${last?.errorMessage ?? ''}`);
        emit('error', { code, message: MODEL_ERROR_TEXT[code] });
      } else {
        emit('done', { message: assistant });
      }
    } catch (error) {
      console.error(`run ${session.id} crashed`, error);
      for (const call of calls) if (call.state === 'running') call.state = 'failed';
      assistant.content = textOf(parts);
      assistant.duration_ms = Date.now() - started;
      await saving;
      await this.store.updateMessage(assistant.id, assistant).catch(() => {});
      emit('error', { code: 'INTERNAL', message: (error as Error).message });
    } finally {
      piSession?.dispose();
      await this.store.updateSession(session.id, { state: 'idle' }).catch(error => console.error('session idle', error));
      this.release(session.id);
    }
  }

  private async scopeName(api: ApiClient, session: SessionRecord): Promise<string | null> {
    const scope = session.scope;
    if (!scope) return null;
    const path = 'subcorpus_id' in scope ? `/subcorpora/${scope.subcorpus_id}` : `/corpora/${scope.corpus_id}`;
    return (await api.get<{ name: string }>(path)).name;
  }
}

function textOf(parts: Part[]): string {
  return parts.filter(part => part.type === 'text').map(part => (part as { text: string }).text).join('').trim();
}
