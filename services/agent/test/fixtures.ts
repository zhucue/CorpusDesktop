/** Loopback fakes: an OpenAI-compatible SSE model server, the business api, and an in-memory store. */
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { randomUUID } from 'node:crypto';
import { mkdirSync, mkdtempSync } from 'node:fs';
import { join } from 'node:path';
import type { AddressInfo } from 'node:net';
import type { Config } from '../src/config.ts';
import type { SessionRecord, Store } from '../src/store.ts';
import type { Message, Part, Scope, Session, ToolCall } from '../src/types.ts';

export const PROJECT = '11111111-1111-4111-8111-111111111111';
export const CORPUS = '22222222-2222-4222-8222-222222222222';
export const USER = { id: '33333333-3333-4333-8333-333333333333', email: 'r@example.edu', display_name: '研究生', is_admin: false };
export const COOKIE = 'corpus_session=good';
export const ORIGIN = 'http://localhost:8080';
export const AGENT_TOKEN = 'agent-token-1';
export const MODEL_KEY = 'model-key-1';

async function readBody(request: IncomingMessage): Promise<string> {
  let text = '';
  for await (const chunk of request) text += String(chunk);
  return text;
}

async function listen(server: ReturnType<typeof createServer>) {
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = (server.address() as AddressInfo).port;
  return {
    url: `http://127.0.0.1:${port}`,
    close: async () => { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); },
  };
}

// ---------------------------------------------------------------- model server

export type Reply = { text: string; thinking?: string } | { tool: string; args: Record<string, unknown> } | { status: number } | { hang: true };

function writeReply(response: ServerResponse, api: string, reply: { text: string; thinking?: string } | { tool: string; args: Record<string, unknown> }) {
  response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
  const emit = (value: unknown) => response.write(`data: ${JSON.stringify(value)}\n\n`);
  const id = 'call_' + randomUUID().replaceAll('-', '');
  // Small uneven chunks exercise the fence splitter across delta boundaries.
  const pieces = (text: string) => text.match(/[\s\S]{1,7}/g) ?? [];
  if (api === 'openai-completions') {
    const chunk = (delta: unknown, finish_reason: string | null = null) => emit({
      id: 'chatcmpl_test', object: 'chat.completion.chunk', created: 1, model: 'fake-model',
      choices: [{ index: 0, delta, finish_reason }],
    });
    chunk({ role: 'assistant' });
    if ('text' in reply) {
      for (const piece of pieces(reply.thinking ?? '')) chunk({ reasoning_content: piece });
      for (const piece of pieces(reply.text)) chunk({ content: piece });
      chunk({}, 'stop');
    } else {
      const args = JSON.stringify(reply.args);
      const split = Math.floor(args.length / 2);
      chunk({ tool_calls: [{ index: 0, id, type: 'function', function: { name: reply.tool, arguments: args.slice(0, split) } }] });
      chunk({ tool_calls: [{ index: 0, function: { arguments: args.slice(split) } }] });
      chunk({}, 'tool_calls');
    }
    response.end('data: [DONE]\n\n');
    return;
  }
  emit({ type: 'response.created', response: { id: 'resp_' + id, status: 'in_progress', output: [] } });
  let item;
  if ('text' in reply) {
    item = { type: 'message', id: 'msg_' + id, role: 'assistant', status: 'completed', content: [{ type: 'output_text', text: reply.text, annotations: [] }] };
    emit({ type: 'response.output_item.added', output_index: 0, item: { ...item, content: [] } });
    emit({ type: 'response.content_part.added', item_id: item.id, output_index: 0, content_index: 0, part: { type: 'output_text', text: '', annotations: [] } });
    for (const piece of pieces(reply.text)) emit({ type: 'response.output_text.delta', item_id: item.id, output_index: 0, content_index: 0, delta: piece });
  } else {
    const args = JSON.stringify(reply.args);
    item = { type: 'function_call', id: 'fc_' + id, call_id: id, name: reply.tool, arguments: args, status: 'completed' };
    emit({ type: 'response.output_item.added', output_index: 0, item: { ...item, arguments: '', status: 'in_progress' } });
    emit({ type: 'response.function_call_arguments.delta', output_index: 0, item_id: item.id, delta: args });
    emit({ type: 'response.function_call_arguments.done', output_index: 0, item_id: item.id, arguments: args });
  }
  emit({ type: 'response.output_item.done', output_index: 0, item });
  emit({ type: 'response.completed', response: { id: 'resp_' + id, status: 'completed', output: [item], usage: { input_tokens: 8, output_tokens: 4, total_tokens: 12 } } });
  response.end();
}

/** Replies are consumed in order, one per model request. */
export async function fakeModel(api: string, replies: Reply[]) {
  const requests: any[] = [];
  const server = createServer(async (request, response) => {
    const body = JSON.parse(await readBody(request));
    requests.push({ body, authorization: request.headers.authorization });
    if (request.headers.authorization !== `Bearer ${MODEL_KEY}`) {
      response.writeHead(401, { 'Content-Type': 'application/json' }).end(JSON.stringify({ error: { message: 'bad key' } }));
      return;
    }
    const reply = replies[requests.length - 1] ?? { text: '（无更多脚本回复）' };
    if ('status' in reply) { response.writeHead(reply.status, { 'Content-Type': 'application/json' }).end('{"error":{"message":"x"}}'); return; }
    if ('hang' in reply) return; // never answers; the client aborts
    writeReply(response, api, reply);
  });
  const handle = await listen(server);
  return { ...handle, url: `${handle.url}/v1`, requests };
}

// ---------------------------------------------------------------- api server

export interface ApiRequest { method: string; path: string; headers: IncomingMessage['headers']; body: any }

export const HITS = [
  { hit_id: 'doc1:10-12', document_id: 'doc1', document_title: '新闻 01', sentence_index: 3, left: '他们决定', match: '翻译', right: '这本书。', start_cp: 10, end_cp: 12, metadata: {}, aligned: [] },
  { hit_id: 'doc2:4-6', document_id: 'doc2', document_title: '小说 07', sentence_index: 0, left: '请', match: '翻译', right: '成英文。', start_cp: 4, end_cp: 6, metadata: {}, aligned: [{ language: 'en', text: 'Please translate it.' }] },
];

export async function fakeApi(options: { statJobState?: 'succeeded' | 'running' } = {}) {
  const requests: ApiRequest[] = [];
  const jobPolls = new Map<string, number>();
  let jobPolled: () => void = () => {};
  const firstJobPoll = new Promise<void>(resolve => { jobPolled = resolve; });
  const json = (response: ServerResponse, status: number, value: unknown) =>
    response.writeHead(status, { 'Content-Type': 'application/json' }).end(JSON.stringify(value));
  const fail = (response: ServerResponse, status: number, code: string) => json(response, status, { error: { code, message: code } });

  const server = createServer(async (request, response) => {
    const url = new URL(request.url!, 'http://x');
    const text = await readBody(request);
    const body = text ? JSON.parse(text) : null;
    const path = url.pathname.replace(/^\/api/, '');
    requests.push({ method: request.method!, path: path + url.search, headers: request.headers, body });
    const cookieOk = request.headers.cookie === COOKIE;
    const bearerOk = request.headers.authorization === `Bearer ${AGENT_TOKEN}`;

    if (path === '/auth/me') return cookieOk ? json(response, 200, USER) : fail(response, 401, 'AUTH_REQUIRED');
    if (path === '/auth/agent-token' && request.method === 'POST') {
      if (!cookieOk) return fail(response, 401, 'AUTH_REQUIRED');
      if (request.headers.origin !== ORIGIN) return fail(response, 403, 'ORIGIN_REJECTED');
      if (body?.project_id !== PROJECT) return fail(response, 403, 'FORBIDDEN');
      return json(response, 200, { token: AGENT_TOKEN, expires_at: new Date(Date.now() + 1800e3).toISOString() });
    }
    if (path === `/projects/${PROJECT}` && cookieOk) return json(response, 200, { id: PROJECT, name: '毕业论文', role: 'owner' });
    if (path.startsWith('/projects/') && cookieOk) return fail(response, 404, 'NOT_FOUND');
    if (!bearerOk) return fail(response, 401, 'AUTH_REQUIRED');

    if (path === `/corpora/${CORPUS}`) return json(response, 200, { id: CORPUS, name: 'UD 中文', status: 'ready' });
    if (path === '/search' && request.method === 'POST') {
      return json(response, 200, {
        search_id: 'search-1', parse: { ok: true }, counts: { hits: 2, sentences: 2, documents: 2, complete: true },
        items: HITS, page: 1, page_size: 20,
      });
    }
    const statJob = /^\/stats\/(frequency|ngrams|collocations|keywords|distribution)$/.exec(path);
    if (statJob && request.method === 'POST') {
      return json(response, 200, { id: `job-${statJob[1]}`, project_id: PROJECT, kind: 'stats', state: 'queued', progress: { done: 0, total: null, message: '' }, result: null, error: null });
    }
    const job = /^\/jobs\/(job-\w+)$/.exec(path);
    if (job) {
      const polls = (jobPolls.get(job[1]) ?? 0) + 1;
      jobPolls.set(job[1], polls);
      jobPolled();
      const done = options.statJobState !== 'running' && polls >= 2;
      return json(response, 200, {
        id: job[1], project_id: PROJECT, kind: 'stats', state: done ? 'succeeded' : 'running',
        progress: { done: done ? 1 : 0, total: 1, message: '' }, result: done ? { stat_id: 'stat-1' } : null, error: null,
      });
    }
    if (path === '/stats/stat-1') {
      return json(response, 200, {
        id: 'stat-1', project_id: PROJECT, method: 'collocations', params: {}, scope: { corpus_id: CORPUS, subcorpus_id: null, name: 'UD 中文' },
        index_version: 'v1', totals: { tokens: 1000, sentences: 80, documents: 5 }, created_at: new Date().toISOString(),
        columns: [{ key: 'collocate', label: '搭配词', type: 'string' }, { key: 'cooc', label: '共现频次', type: 'number' }, { key: 'logdice', label: 'logDice', type: 'number' }],
        rows: Array.from({ length: 60 }, (_, i) => ({ key: `w${i}`, values: { collocate: `w${i}`, cooc: 60 - i, logdice: 10 - i / 10 }, search_query: null, search_scope: { corpus_id: CORPUS } })),
        row_count: 60,
      });
    }
    return fail(response, 404, 'NOT_FOUND');
  });
  return { ...(await listen(server)), requests, firstJobPoll };
}

// ---------------------------------------------------------------- store + config

export class MemoryStore implements Store {
  sessions = new Map<string, SessionRecord>();
  messages = new Map<string, Message & { session_id: string }>();
  async resetRunning() { for (const s of this.sessions.values()) s.state = 'idle'; }
  async createSession(session: Omit<SessionRecord, 'message_count' | 'created_at' | 'updated_at'>) {
    const now = new Date().toISOString();
    this.sessions.set(session.id, { ...session, created_at: now, updated_at: now, message_count: 0 });
    return (await this.getSession(session.id))!;
  }
  async getSession(id: string) {
    const s = this.sessions.get(id);
    if (!s) return null;
    return structuredClone({ ...s, message_count: [...this.messages.values()].filter(m => m.session_id === id).length });
  }
  async listSessions(projectId: string, ownerId: string) {
    const ids = [...this.sessions.values()].filter(s => s.project_id === projectId && s.owner_id === ownerId).map(s => s.id);
    return Promise.all(ids.map(async id => (await this.getSession(id))!));
  }
  async updateSession(id: string, fields: { title?: string; scope?: Scope; state?: Session['state'] }) {
    const s = this.sessions.get(id);
    if (s) Object.assign(s, structuredClone(fields), { updated_at: new Date().toISOString() });
  }
  async deleteSession(id: string) {
    this.sessions.delete(id);
    for (const [key, m] of this.messages) if (m.session_id === id) this.messages.delete(key);
  }
  async listMessages(sessionId: string) {
    return [...this.messages.values()].filter(m => m.session_id === sessionId)
      .sort((a, b) => a.created_at.localeCompare(b.created_at))
      .map(({ session_id: _s, ...m }) => structuredClone(m));
  }
  async insertMessage(sessionId: string, message: Message) { this.messages.set(message.id, structuredClone({ ...message, session_id: sessionId })); }
  async updateMessage(id: string, fields: { content: string; parts: Part[]; tool_calls: ToolCall[]; duration_ms?: number | null }) {
    const m = this.messages.get(id);
    if (m) Object.assign(m, structuredClone(fields));
  }
  async deleteMessage(id: string) { this.messages.delete(id); }
  async close() {}
}

export function testConfig(overrides: Partial<Config> & { apiUrl: string; modelUrl?: string; modelApi?: 'openai-completions' | 'openai-responses' }): Config {
  const root = join(import.meta.dirname, '..', '..', '..', 'tmp');
  mkdirSync(root, { recursive: true });
  const { apiUrl, modelUrl, modelApi, ...rest } = overrides;
  return {
    port: 0, apiBaseUrl: `${apiUrl}/api`, databaseUrl: '', dataDir: mkdtempSync(join(root, 'agent-test-')),
    publicOrigin: ORIGIN,
    model: modelUrl ? {
      baseUrl: modelUrl, apiKey: MODEL_KEY, id: 'fake-model', api: modelApi ?? 'openai-completions',
      contextWindow: 32000, maxTokens: 2048, timeoutMs: 10000, reasoning: false,
    } : null,
    jobPollMs: 10, jobWaitMs: 5000,
    ...rest,
  };
}

/** Parses a complete SSE body into [{event, data}] (comment lines ignored). */
export function parseSse(text: string): { event: string; data: any }[] {
  return text.split('\n\n').filter(block => block.trim() && !block.startsWith(':')).map(block => {
    const event = /^event: ?(.*)$/m.exec(block)?.[1] ?? 'message';
    const data = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.replace(/^data: ?/, '')).join('\n');
    return { event, data: JSON.parse(data) };
  });
}
