/** HTTP surface under /agent (contracts/p2.md §五 会话接口). */
import { randomUUID } from 'node:crypto';
import { rm } from 'node:fs/promises';
import { Hono, type Context } from 'hono';
import { streamSSE } from 'hono/streaming';
import { ApiClient, ApiError, type User } from './api.ts';
import type { Config } from './config.ts';
import { Runner, sessionDir } from './runner.ts';
import type { SessionRecord, Store } from './store.ts';
import type { Scope, Session } from './types.ts';

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
    return browserApi(c).get<User>('/auth/me');
  }

  async function ownSession(c: Context, user: User): Promise<SessionRecord> {
    const id = c.req.param('id') ?? '';
    const session = UUID.test(id) ? await store.getSession(id) : null;
    if (!session || session.owner_id !== user.id) throw new HttpError(404, 'NOT_FOUND', '会话不存在');
    return session;
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
    await browserApi(c).get(`/projects/${projectId}`);
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
    await browserApi(c).get(`/projects/${projectId}`);
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

  app.post('/agent/sessions/:id/messages', async c => {
    const session = await ownSession(c, await currentUser(c));
    const input = await body(c);
    const content = typeof input.content === 'string' ? input.content.trim() : '';
    if (!content) throw new HttpError(422, 'EMPTY_CONTENT', '消息不能为空');
    if (content.length > MAX_CONTENT) throw new HttpError(422, 'CONTENT_TOO_LONG', `消息不能超过 ${MAX_CONTENT} 字`);
    if (!config.model) throw new HttpError(503, 'MODEL_NOT_CONFIGURED', '未配置模型服务');
    if (!runner.reserve(session.id)) throw new HttpError(409, 'SESSION_BUSY', '会话正在运行');
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
        await runner.run(session, content, token, emit);
      } finally {
        clearInterval(ping);
      }
    });
  });

  return app;
}
