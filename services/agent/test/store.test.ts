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

test('PgStore session and message round trip', { skip: !url && 'AGENT_TEST_DATABASE_URL not set' }, async () => {
  const schema = `agent_store_test_${randomUUID().slice(0, 8)}`;
  const admin = new pg.Client({ connectionString: url });
  await admin.connect();
  await admin.query(`CREATE SCHEMA ${schema}`);
  await admin.query(`SET search_path TO ${schema}`);
  await admin.query(`
    CREATE TABLE users (id uuid PRIMARY KEY);
    CREATE TABLE projects (id uuid PRIMARY KEY);
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
    await store.insertMessage(id, { id: randomUUID(), role: 'user', content: '你好', parts: [{ type: 'text', text: '你好' }], tool_calls: [], created_at: new Date(now).toISOString() });
    const assistantId = randomUUID();
    await store.insertMessage(id, { id: assistantId, role: 'assistant', content: '', parts: [], tool_calls: [], created_at: new Date(now + 1).toISOString() });
    await store.updateMessage(assistantId, {
      content: '结果', parts: [{ type: 'text', text: '结果' }, { type: 'ui', lang: 'root = Callout("info", "x")' }],
      tool_calls: [{ id: 'c1', name: 'corpus.search', args: { query: 'x' }, state: 'succeeded', result_summary: '命中 1', duration_ms: 5 }],
      duration_ms: 42,
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
