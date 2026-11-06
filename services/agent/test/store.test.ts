/**
 * PgStore against a real PostgreSQL. Runs only with AGENT_TEST_DATABASE_URL; uses a
 * throwaway schema whose agent tables mirror migration 0002.
 */
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { test } from 'node:test';
import pg from 'pg';
import { PgStore } from '../src/store.ts';

const url = process.env.AGENT_TEST_DATABASE_URL?.replace(/^postgres(ql)?\+\w+:/, 'postgresql:');

test('PgStore session and message round trip, llm_usage rows and month total, deleted projects', { skip: !url && 'AGENT_TEST_DATABASE_URL not set' }, async () => {
  const schema = `agent_store_test_${randomUUID().slice(0, 8)}`;
  const admin = new pg.Client({ connectionString: url });
  await admin.connect();
  await admin.query(`CREATE SCHEMA ${schema}`);
  await admin.query(`SET search_path TO ${schema}`);
  await admin.query(`
    CREATE TABLE users (id uuid PRIMARY KEY);
    CREATE TABLE projects (id uuid PRIMARY KEY, deleted_at timestamptz);
    -- contracts/p9.md §一 (migration 0010)
    CREATE TABLE llm_usage (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(),
      user_id uuid REFERENCES users(id) ON DELETE SET NULL, project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
      source text NOT NULL, model text, prompt_tokens integer, completion_tokens integer, total_tokens integer,
      job_id uuid, session_id text);
    CREATE TABLE agent_sessions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      title text NOT NULL DEFAULT '', scope jsonb, state text NOT NULL DEFAULT 'idle'
        CONSTRAINT ck_agent_session_state CHECK (state IN ('idle', 'running')),
      pi_session_path text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE agent_messages (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      session_id uuid NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
      role text NOT NULL CONSTRAINT ck_agent_message_role CHECK (role IN ('user', 'assistant')),
      content text NOT NULL DEFAULT '', parts jsonb NOT NULL DEFAULT '[]', tool_calls jsonb NOT NULL DEFAULT '[]',
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(), duration_ms integer);`);
  const user = randomUUID();
  const project = randomUUID();
  await admin.query('INSERT INTO users VALUES ($1)', [user]);
  await admin.query('INSERT INTO projects VALUES ($1)', [project]);
  const separator = url!.includes('?') ? '&' : '?';
  const store = new PgStore(`${url}${separator}options=${encodeURIComponent(`-c search_path=${schema}`)}`);
  try {
    const id = randomUUID();
    const created = await store.createSession({ id, project_id: project, owner_id: user, title: '', scope: null, state: 'idle', pi_session_path: `/data/sessions/${id}` });
    assert.equal(created.scope, null);
    assert.equal(created.message_count, 0);
    assert.match(created.created_at, /^\d{4}-\d\d-\d\dT/);

    await store.updateSession(id, { title: '搭配', scope: { corpus_id: project }, state: 'running' });
    const now = Date.now();
    const context = { page: 'search' as const, label: 'UD 中文', query: '翻译/v', search_id: 's1', hit_ids: ['d:1-2'], scope: { corpus_id: project } };
    await store.insertMessage(id, { id: randomUUID(), role: 'user', content: '你好', parts: [{ type: 'text', text: '你好' }], tool_calls: [], created_at: new Date(now).toISOString(), context });
    const assistantId = randomUUID();
    await store.insertMessage(id, { id: assistantId, role: 'assistant', content: '', parts: [], tool_calls: [], created_at: new Date(now + 1).toISOString() });
    await store.updateMessage(assistantId, {
      content: '结果', parts: [{ type: 'text', text: '结果' }, { type: 'ui', lang: 'root = Callout("info", "x")' }],
      tool_calls: [{ id: 'c1', name: 'corpus.search', args: { query: 'x' }, state: 'succeeded', result_summary: '命中 1', duration_ms: 5 }],
      duration_ms: 42, stopped: true,
    });

    const [session] = await store.listSessions(project, user);
    assert.equal(session.title, '搭配');
    assert.deepEqual(session.scope, { corpus_id: project });
    assert.equal(session.state, 'running');
    assert.equal(session.message_count, 2);
    const messages = await store.listMessages(id);
    assert.deepEqual(messages.map(m => m.role), ['user', 'assistant']);
    assert.equal(messages[1].parts[1].type, 'ui');
    assert.equal(messages[1].tool_calls[0].name, 'corpus.search');
    assert.equal(messages[1].duration_ms, 42);
    // the stopped marker round-trips through parts and is not shown as a part
    assert.equal(messages[1].stopped, true);
    assert.equal(messages[1].parts.length, 2);
    assert.equal(messages[0].stopped, undefined);
    // the page context round-trips the same way, kept out of the displayed parts
    assert.deepEqual(messages[0].context, context);
    assert.deepEqual(messages[0].parts, [{ type: 'text', text: '你好' }]);
    assert.equal(messages[1].context, undefined);

    // llm_usage rows and the month total; last month's row does not count
    const monthStart = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
    const row = { user_id: user, project_id: project, session_id: id, model: 'fake-model' } as const;
    await store.recordUsage({ ...row, source: 'agent', prompt_tokens: 100, completion_tokens: 20, total_tokens: 120 });
    await store.recordUsage({ ...row, source: 'agent:estimated', prompt_tokens: 40, completion_tokens: 5, total_tokens: 45 });
    await admin.query(`INSERT INTO llm_usage (created_at, user_id, source, total_tokens) VALUES ($1, $2, 'agent', 1000)`,
      [new Date(monthStart.getTime() - 3600e3), user]);
    assert.equal(await store.monthlyTokens(user, monthStart), 165);
    assert.equal(await store.monthlyTokens(randomUUID(), monthStart), 0);
    const { rows: usage } = await admin.query(`SELECT source, session_id, project_id, model, prompt_tokens FROM llm_usage WHERE session_id = $1 ORDER BY id`, [id]);
    assert.deepEqual(usage, [
      { source: 'agent', session_id: id, project_id: project, model: 'fake-model', prompt_tokens: 100 },
      { source: 'agent:estimated', session_id: id, project_id: project, model: 'fake-model', prompt_tokens: 40 },
    ]);

    // a soft-deleted project lists no sessions
    await admin.query('UPDATE projects SET deleted_at = now() WHERE id = $1', [project]);
    assert.deepEqual(await store.listSessions(project, user), []);
    await admin.query('UPDATE projects SET deleted_at = NULL WHERE id = $1', [project]);

    await store.resetRunning();
    assert.equal((await store.getSession(id))!.state, 'idle');
    await store.deleteMessage(assistantId);
    assert.equal((await store.getSession(id))!.message_count, 1);
    await store.deleteSession(id);
    assert.equal(await store.getSession(id), null);
  } finally {
    await store.close();
    await admin.query(`DROP SCHEMA ${schema} CASCADE`);
    await admin.end();
  }
});
