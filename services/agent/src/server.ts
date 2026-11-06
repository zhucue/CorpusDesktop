/** HTTP surface under /agent (contracts/p2.md §五 会话接口). */
import { randomUUID } from 'node:crypto';
import { rm } from 'node:fs/promises';
import { Hono, type Context } from 'hono';
import { streamSSE } from 'hono/streaming';
import { ApiClient, ApiError, type User } from './api.ts';
import type { Config } from './config.ts';
import { Runner, sessionDir, type RunOptions } from './runner.ts';
import type { SessionRecord, Store } from './store.ts';
import type { PageContext, Scope, Session, ToolCall } from './types.ts';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_CONTENT = 20000;

class HttpError extends Error {
  readonly status: number;
  readonly code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function parseScope(value: unknown): Scope {
  if (value === null || value === undefined) return null;
  if (typeof value === 'object') {
    const keys = Object.keys(value);
    const v = value as Record<string, unknown>;
    if (keys.length === 1 && typeof v.corpus_id === 'string' && UUID.test(v.corpus_id)) return { corpus_id: v.corpus_id };
    if (keys.length === 1 && typeof v.subcorpus_id === 'string' && UUID.test(v.subcorpus_id)) return { subcorpus_id: v.subcorpus_id };
  }
  throw new HttpError(422, 'INVALID_SCOPE', 'scope 应为 {corpus_id}、{subcorpus_id} 或 null');
}

const PAGES = new Set<PageContext['page']>(['search', 'stats', 'annotate', 'knowledge', 'corpora']);
const MAX_HITS = 20;

/** Optional `context` of POST /messages (contracts/p7.md §三); undefined when absent. */
function parseContext(value: unknown): PageContext | undefined {
  if (value === null || value === undefined) return undefined;
  const bad = (message: string) => new HttpError(422, 'INVALID_CONTEXT', message);
  if (typeof value !== 'object' || Array.isArray(value)) throw bad('context 应为对象');
  const v = value as Record<string, unknown>;
  if (!PAGES.has(v.page as PageContext['page'])) throw bad('context.page 应为 search、stats、annotate、knowledge 或 corpora');
  const text = (key: string, max: number, required = false) => {
    const item = v[key];
    if (item === undefined || item === null || (item === '' && !required)) {
      if (required) throw bad(`context.${key} 必填`);
      return undefined;
    }
    if (typeof item !== 'string' || item.length > max) throw bad(`context.${key} 应为不超过 ${max} 字的字符串`);
    return item;
  };
  const context: PageContext = { page: v.page as PageContext['page'], label: text('label', 200, true)!, scope: parseScope(v.scope) };
  const query = text('query', 1000);
  const searchId = text('search_id', 200);
  if (query !== undefined) context.query = query;
  if (searchId !== undefined) context.search_id = searchId;
  if (v.hit_ids !== undefined && v.hit_ids !== null) {
    const ids = v.hit_ids;
    if (!Array.isArray(ids) || ids.length > MAX_HITS || ids.some(id => typeof id !== 'string' || !id || id.length > 200)) {
      throw bad(`context.hit_ids 应为不超过 ${MAX_HITS} 个 hit_id`);
    }
    if (ids.length) context.hit_ids = ids;
  }
  return context;
}

export function createApp(config: Config, store: Store, runner: Runner) {
  const app = new Hono();
  const origins = new Set((config.publicOrigin ?? '').split(',').map(o => o.trim()).filter(Boolean));

  const browserApi = (c: Context) =>
    new ApiClient(config.apiBaseUrl, { cookie: c.req.header('cookie'), origin: c.req.header('origin') });

  const view = (session: SessionRecord): Session => {
    const { pi_session_path: _path, ...rest } = session;
    return { ...rest, state: runner.isRunning(session.id) ? 'running' : 'idle' };
  };

  async function currentUser(c: Context): Promise<User> {
    if (!c.req.header('cookie')) throw new HttpError(401, 'AUTH_REQUIRED', '请先登录');
    const user = await browserApi(c).get<User>('/auth/me');
    // Same rule as the api: until the password is changed, everything but /auth/me, /auth/password, /auth/logout is 403.
    if (user.must_change_password) throw new HttpError(403, 'PASSWORD_CHANGE_REQUIRED', '请先修改密码');
    return user;
  }

  /** The user must be a member of a live project: the api answers 404 for a deleted one (contracts/p9.md §五). */
  async function checkProject(c: Context, projectId: string) {
    try {
      await browserApi(c).get(`/projects/${projectId}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) throw new HttpError(404, 'NOT_FOUND', '项目不存在或已删除');
      throw error;
    }
  }

  async function ownSession(c: Context, user: User): Promise<SessionRecord> {
    const id = c.req.param('id') ?? '';
    const session = UUID.test(id) ? await store.getSession(id) : null;
    if (!session || session.owner_id !== user.id) throw new HttpError(404, 'NOT_FOUND', '会话不存在');
    // The owner must still be a project member: removal revokes access to earlier sessions at once.
    await checkProject(c, session.project_id);
    return session;
  }

  /** Reserve a run of the session for its owner: SESSION_BUSY, then TOO_MANY_RUNS (contracts/p9.md §二). */
  function reserve(session: SessionRecord) {
    const result = runner.reserve(session.id, session.owner_id, config.maxRunsPerUser);
    if (result === 'busy') throw new HttpError(409, 'SESSION_BUSY', '会话正在运行');
    if (result === 'too_many') {
      throw new HttpError(429, 'TOO_MANY_RUNS', `已有 ${config.maxRunsPerUser} 个对话在运行，请等待完成或停止后再试`);
    }
  }

  /** LLM_QUOTA_EXCEEDED once the owner's total_tokens this calendar month (server local time) reach the limit. */
  async function checkQuota(userId: string) {
    const limit = config.monthlyTokensPerUser;
    if (!limit || !store.monthlyTokens) return;
    const now = new Date();
    const used = await store.monthlyTokens(userId, new Date(now.getFullYear(), now.getMonth(), 1));
    if (used >= limit) throw new HttpError(429, 'LLM_QUOTA_EXCEEDED', `本月模型用量已达上限（${limit} token），请联系管理员`);
  }

  async function body(c: Context): Promise<Record<string, unknown>> {
    try {
      const value = await c.req.json();
      if (value && typeof value === 'object' && !Array.isArray(value)) return value;
    } catch { /* fall through */ }
    throw new HttpError(422, 'INVALID_BODY', '请求体应为 JSON 对象');
  }

  app.onError((error, c) => {
    if (error instanceof HttpError || error instanceof ApiError) {
      return c.json({ error: { code: error.code, message: error.message } }, error.status as 400);
    }
    console.error(error);
    return c.json({ error: { code: 'INTERNAL', message: '服务内部错误' } }, 500);
  });

  // Same CSRF rule as the api: cookie requests that change state need a known Origin.
  app.use('/agent/*', async (c, next) => {
    if (origins.size && !['GET', 'HEAD', 'OPTIONS'].includes(c.req.method) && !origins.has(c.req.header('origin') ?? '')) {
      throw new HttpError(403, 'ORIGIN_REJECTED', '请求来源不被允许');
    }
    await next();
  });

  app.get('/agent/health', c =>
    c.json(config.model ? { ok: true, model_id: config.model.id } : { ok: false, reason: 'MODEL_NOT_CONFIGURED' }));

  app.get('/agent/sessions', async c => {
    const user = await currentUser(c);
    const projectId = c.req.query('project_id') ?? '';
    if (!UUID.test(projectId)) throw new HttpError(422, 'INVALID_PROJECT', '需要 project_id');
    await checkProject(c, projectId);
    const items = (await store.listSessions(projectId, user.id)).map(view);
    return c.json({ items, total: items.length });
  });

  app.post('/agent/sessions', async c => {
    const user = await currentUser(c);
    const input = await body(c);
    const projectId = String(input.project_id ?? '');
    if (!UUID.test(projectId)) throw new HttpError(422, 'INVALID_PROJECT', '需要 project_id');
    const scope = parseScope(input.scope);
    const title = typeof input.title === 'string' ? input.title.trim().slice(0, 200) : '';
    await checkProject(c, projectId);
    const id = randomUUID();
    const session = await store.createSession({
      id, project_id: projectId, owner_id: user.id, title, scope, state: 'idle',
      pi_session_path: sessionDir(config.dataDir, id),
    });
    return c.json(view(session), 201);
  });

  app.get('/agent/sessions/:id', async c => {
    const session = await ownSession(c, await currentUser(c));
    const running = runner.isRunning(session.id);
    const messages = (await store.listMessages(session.id)).map(message => running ? message : {
      // A run interrupted by a restart leaves running tool calls behind.
      ...message, tool_calls: message.tool_calls.map(call => call.state === 'running' ? { ...call, state: 'cancelled' as const } : call),
    });
    return c.json({ ...view(session), messages });
  });

  app.patch('/agent/sessions/:id', async c => {
    const session = await ownSession(c, await currentUser(c));
    const input = await body(c);
    const fields: { title?: string; scope?: Scope } = {};
    if ('title' in input) {
      if (typeof input.title !== 'string') throw new HttpError(422, 'INVALID_TITLE', 'title 应为字符串');
      fields.title = input.title.trim().slice(0, 200);
    }
    if ('scope' in input) fields.scope = parseScope(input.scope);
    await store.updateSession(session.id, fields);
    return c.json(view((await store.getSession(session.id))!));
  });

  app.delete('/agent/sessions/:id', async c => {
    const session = await ownSession(c, await currentUser(c));
    if (runner.isRunning(session.id)) throw new HttpError(409, 'SESSION_BUSY', '会话正在运行，请先停止');
    await store.deleteSession(session.id);
    await rm(sessionDir(config.dataDir, session.id), { recursive: true, force: true });
    return c.body(null, 204);
  });

  app.post('/agent/sessions/:id/cancel', async c => {
    const session = await ownSession(c, await currentUser(c));
    await runner.cancel(session.id);
    return c.body(null, 204);
  });

  /** Agent token, then the run as an SSE stream; the reservation is released by the run (or here on failure). */
  async function stream(c: Context, session: SessionRecord, content: string, options: RunOptions) {
    let token: string;
    try {
      ({ token } = await browserApi(c).post<{ token: string }>('/auth/agent-token', { project_id: session.project_id }));
    } catch (error) {
      runner.release(session.id);
      throw error;
    }

    c.header('X-Accel-Buffering', 'no');
    c.header('Cache-Control', 'no-cache');
    return streamSSE(c, async stream => {
      let open = true;
      stream.onAbort(() => { open = false; });
      const emit = (event: string, data: unknown) =>
        open ? stream.writeSSE({ event, data: JSON.stringify(data) }).catch(() => { open = false; }) : undefined;
      // Keep proxies from closing the stream while a tool waits on a background job.
      const ping = setInterval(() => { if (open) stream.write(': ping\n\n').catch(() => { open = false; }); }, 15000);
      try {
        // The run continues if the client disconnects; GET /agent/sessions/{id} shows its state.
        await runner.run(session, content, token, emit, options);
      } finally {
        clearInterval(ping);
      }
    });
  }

  app.post('/agent/sessions/:id/messages', async c => {
    const session = await ownSession(c, await currentUser(c));
    const input = await body(c);
    const regenerate = input.regenerate === true;
    let content = typeof input.content === 'string' ? input.content.trim() : '';
    let context = parseContext(input.context);
    if (regenerate) {
      // Regenerate re-asks the last question with its page context; the old question and answer are replaced.
      const last = (await store.listMessages(session.id)).findLast(message => message.role === 'user');
      if (!last) throw new HttpError(409, 'NOTHING_TO_REGENERATE', '没有可以重新生成的回答');
      content = last.content;
      context = last.context;
    }
    if (!content) throw new HttpError(422, 'EMPTY_CONTENT', '消息不能为空');
    if (content.length > MAX_CONTENT) throw new HttpError(422, 'CONTENT_TOO_LONG', `消息不能超过 ${MAX_CONTENT} 字`);
    if (!config.model) throw new HttpError(503, 'MODEL_NOT_CONFIGURED', '未配置模型服务');
    await checkQuota(session.owner_id);
    reserve(session);
    return stream(c, session, content, { regenerate, ...(context ? { context } : {}) });
  });

  /**
   * Answer the confirm card of the latest assistant message. decline → JSON {message};
   * execute → SSE run: the server runs the proposed calls as given, then the model reports.
   */
  app.post('/agent/sessions/:id/confirm', async c => {
    const session = await ownSession(c, await currentUser(c));
    const input = await body(c);
    const ids = Array.isArray(input.tool_call_ids) ? input.tool_call_ids.filter((id): id is string => typeof id === 'string') : [];
    const action = input.action;
    if (!ids.length || (action !== 'execute' && action !== 'decline')) {
      throw new HttpError(422, 'INVALID_CONFIRMATION', '需要 tool_call_ids 和 action（execute 或 decline）');
    }
    if (action === 'execute' && !config.model) throw new HttpError(503, 'MODEL_NOT_CONFIGURED', '未配置模型服务');
    // Execute starts a model run: quota and the owner's run limit apply; decline only answers the card.
    if (action === 'execute') await checkQuota(session.owner_id);
    if (action === 'execute') reserve(session);
    else if (runner.reserve(session.id, session.owner_id) === 'busy') throw new HttpError(409, 'SESSION_BUSY', '会话正在运行');
    let calls: ToolCall[];
    try {
      const message = (await store.listMessages(session.id)).findLast(item => item.role === 'assistant');
      const found = ids.map(id => message?.tool_calls.find(call => call.id === id));
      if (!message || found.some(call => call?.state !== 'needs_confirmation')) {
        throw new HttpError(409, 'CONFIRMATION_EXPIRED', '这个操作已处理或已失效');
      }
      calls = found as ToolCall[];
      for (const call of calls) {
        call.state = action === 'execute' ? 'confirmed' : 'declined';
        call.result_summary = action === 'execute' ? '已确认执行' : '已取消';
      }
      await store.updateMessage(message.id, message);
      if (action === 'decline') {
        runner.release(session.id);
        return c.json({ message });
      }
    } catch (error) {
      runner.release(session.id);
      throw error;
    }
    return stream(c, session, '', { confirmed: calls.map(call => structuredClone(call)) });
  });

  return app;
}
