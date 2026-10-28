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
import { piName, piTools, runConfirmed, toolSpecs, type ToolOutput } from './tools.ts';
import type { Message, Part, ToolCall } from './types.ts';
import { FenceSplitter } from './ui-stream.ts';

/** Returns the write promise when the transport has one; the final event is awaited before the stream closes. */
export type Emit = (event: string, data: unknown) => unknown;

interface ActiveRun {
  cancelled: boolean;
  session?: AgentSession;
  /** Aborts confirmed tool calls the server runs itself. */
  abort: AbortController;
}

export interface RunOptions {
  /** Replace the last question and everything after it (store rows and the Pi branch). */
  regenerate?: boolean;
  /** Proposals the user confirmed: run them first (no user message), then let the model report. */
  confirmed?: ToolCall[];
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
    this.active.set(sessionId, { cancelled: false, abort: new AbortController() });
    return true;
  }

  release(sessionId: string) {
    this.active.delete(sessionId);
  }

  async cancel(sessionId: string) {
    const run = this.active.get(sessionId);
    if (!run) return;
    run.cancelled = true;
    run.abort.abort();
    await run.session?.abort();
  }

  /** Executes a reserved run to completion; always releases the reservation. */
  async run(session: SessionRecord, content: string, token: string, emit: Emit, options: RunOptions = {}): Promise<void> {
    const run = this.active.get(session.id)!;
    const model = this.model!;
    const started = Date.now();
    const confirmed = options.confirmed ?? [];
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
    let final: [string, unknown] | null = null;
    let saving: Promise<void> = Promise.resolve();
    const save = () => {
      const snapshot = { content: textOf(parts), parts: structuredClone(parts), tool_calls: structuredClone(calls) };
      saving = saving.then(() => this.store.updateMessage(assistant.id, snapshot)).catch(error => console.error('save message', error));
    };

    try {
      const history = await this.store.listMessages(session.id);
      let replaced: string | null = null;
      if (options.regenerate) {
        const at = history.findLastIndex(message => message.role === 'user');
        if (at >= 0) {
          replaced = history[at].content;
          for (const message of history.splice(at)) await this.store.deleteMessage(message.id);
        }
      }
      // A proposal the user declined is told to the model once, with the next message.
      const declined = history.findLast(message => message.role === 'assistant')?.tool_calls
        .filter(call => call.state === 'declined').map(call => call.confirm?.title ?? call.name) ?? [];
      if (!confirmed.length) await this.store.insertMessage(session.id, userMessage);
      await this.store.insertMessage(session.id, assistant);
      await this.store.updateSession(session.id, {
        state: 'running', ...(session.title || !content ? {} : { title: content.replace(/\s+/g, ' ').trim().slice(0, 40) }),
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

      let prompt = content;
      if (confirmed.length) {
        const reports: string[] = [];
        for (const proposed of confirmed) {
          if (run.cancelled) break;
          const call: ToolCall = { id: randomUUID(), name: proposed.name, args: proposed.args, state: 'running', result_summary: '', duration_ms: 0 };
          const callStarted = Date.now();
          calls.push(call);
          emit('tool_call', call);
          save();
          const title = proposed.confirm?.title ?? proposed.name;
          try {
            const output = await runConfirmed(toolContext, proposed.name, proposed.args, run.abort.signal);
            call.state = 'succeeded';
            call.result_summary = output.summary;
            if (output.ref) call.result_ref = output.ref;
            reports.push(`- ${title}（${piName(proposed.name)}）：已执行，结果 ${JSON.stringify(output.data)}`);
          } catch (error) {
            call.state = run.cancelled ? 'cancelled' : 'failed';
            call.result_summary = String((error as Error).message ?? error).slice(0, 300);
            reports.push(`- ${title}（${piName(proposed.name)}）：执行失败，${call.result_summary}`);
          }
          call.duration_ms = Date.now() - callStarted;
          emit('tool_result', call);
          save();
        }
        prompt = [
          '[平台消息] 用户点了“执行”，平台已执行你上次提出的操作：', ...reports,
          '请用中文简要告诉用户结果，需要时用组件呈现；不要再次调用这些工具。',
        ].join('\n');
      } else if (declined.length) {
        prompt = `[平台消息] 用户取消了你上次提出的操作：${declined.join('；')}。除非用户再次要求，不要再提出。\n\n${content}`;
      }

      const sessionManager = SessionManager.continueRecent(dir, dir);
      if (replaced !== null) branchBefore(sessionManager, replaced);
      const tools = piTools(toolContext);
      ({ session: piSession } = await createAgentSession({
        cwd: dir,
        agentDir: join(this.config.dataDir, 'pi-agent'),
        modelRuntime: model.runtime,
        model: model.model,
        thinkingLevel: model.config.reasoning ? 'medium' : 'off',
        resourceLoader: explicitResources(systemPrompt(describeScope(session.scope, scopeName))),
        settingsManager: SettingsManager.inMemory({ compaction: { enabled: true }, retry: { enabled: false } }),
        sessionManager,
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
          call.state = event.isError ? (run.cancelled ? 'cancelled' : 'failed') : output?.proposal ? 'needs_confirmation' : 'succeeded';
          call.result_summary = event.isError ? errorText(event.result) : output?.summary ?? '';
          if (!event.isError && output?.ref) call.result_ref = output.ref;
          if (!event.isError && output?.proposal) call.confirm = output.proposal;
          call.duration_ms = event.durationMs ?? Date.now() - (startedAt.get(event.toolCallId) ?? Date.now());
          emit('tool_result', call);
          save();
        }
      });

      if (!run.cancelled) await piSession.prompt(prompt);
      splitter.end();

      const last = [...piSession.messages].reverse().find(message => message.role === 'assistant') as
        { stopReason?: string; errorMessage?: string } | undefined;
      const cancelled = run.cancelled || last?.stopReason === 'aborted';
      const failed = !cancelled && last?.stopReason === 'error';
      for (const call of calls) if (call.state === 'running') call.state = cancelled ? 'cancelled' : 'failed';
      assistant.content = textOf(parts);
      assistant.duration_ms = Date.now() - started;
      if (cancelled) assistant.stopped = true;
      await saving;
      if (failed && !parts.length && !calls.length) await this.store.deleteMessage(assistant.id);
      else await this.store.updateMessage(assistant.id, assistant);
      if (failed) {
        const code = classify(last?.errorMessage);
        console.error(`run ${session.id} failed: ${code} ${last?.errorMessage ?? ''}`);
        final = ['error', { code, message: MODEL_ERROR_TEXT[code] }];
      } else {
        final = ['done', { message: assistant }];
      }
    } catch (error) {
      console.error(`run ${session.id} crashed`, error);
      for (const call of calls) if (call.state === 'running') call.state = 'failed';
      assistant.content = textOf(parts);
      assistant.duration_ms = Date.now() - started;
      await saving;
      await this.store.updateMessage(assistant.id, assistant).catch(() => {});
      final = ['error', { code: 'INTERNAL', message: (error as Error).message }];
    } finally {
      piSession?.dispose();
      await this.store.updateSession(session.id, { state: 'idle' }).catch(error => console.error('session idle', error));
      this.release(session.id);
      // The final event goes out after the session is idle, so a client refreshing on `done` never sees it running.
      if (final) await emit(...final);
    }
  }

  private async scopeName(api: ApiClient, session: SessionRecord): Promise<string | null> {
    const scope = session.scope;
    if (!scope) return null;
    const path = 'subcorpus_id' in scope ? `/subcorpora/${scope.subcorpus_id}` : `/corpora/${scope.corpus_id}`;
    return (await api.get<{ name: string }>(path)).name;
  }
}

/** Regenerate: move the Pi leaf to just before the latest user prompt that carried `content`, so the old turn leaves the context. */
function branchBefore(manager: SessionManager, content: string) {
  const entry = manager.getBranch().findLast(item => {
    if (item.type !== 'message' || (item as any).message?.role !== 'user') return false;
    const value = (item as any).message.content;
    const text = typeof value === 'string' ? value : Array.isArray(value) ? value.map((c: any) => c?.text ?? '').join('') : '';
    return text.includes(content);
  });
  if (!entry) return;
  if (entry.parentId) manager.branch(entry.parentId);
  else manager.resetLeaf();
}

function textOf(parts: Part[]): string {
  return parts.filter(part => part.type === 'text').map(part => (part as { text: string }).text).join('').trim();
}
