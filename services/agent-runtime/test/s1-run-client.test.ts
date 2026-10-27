import assert from 'node:assert/strict';
import { test } from 'node:test';
import { randomUUID } from 'node:crypto';
import { S1RunClient, RunProtocolError } from '../src/s1-run-client.ts';
import { executionTools } from '../src/s1-run-host.ts';

const hostKey = 'host-secret-for-transport-test-only';
const token = 'execution-secret-for-transport-test-only';
function fixture(lostResponse = false) {
  const calls: { url: string; body?: Record<string, unknown>; auth: string }[] = [];
  let invoked = false;
  const fetcher = (async (url: string | URL | Request, init?: RequestInit) => {
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
    calls.push({ url: String(url), body, auth: String((init?.headers as Record<string, string>).Authorization) });
    if (String(url).endsWith('/claim')) return Response.json({ run_id: 'run', session_id: 'session', scope: { scope_kind: 'account' },
      scope_digest: 'digest', lease_epoch: 1, state: 'RUNNING', allowed_tools: ['account.get', 'projects.create'], execution_token: token });
    if (lostResponse && !invoked) { invoked = true; throw new TypeError('Connection closed after server commit'); }
    return Response.json({ result: { invocation_id: 'server-invocation', action_id: 'server-action', status: 'succeeded' }, data: { name: 'Result' } });
  }) as typeof fetch;
  return { client: new S1RunClient({ baseUrl: 'http://127.0.0.1:60636', hostKey, fetcher }), calls };
}

test('lost response retries one server registration, credentials stay outside model schema and result', async () => {
  const { client, calls } = fixture(true);
  const grant = await client.claim(randomUUID());
  assert.ok(!JSON.stringify(grant).includes(token));
  const tools = executionTools(client, grant);
  assert.deepEqual(tools.map(tool => tool.capability_id), ['account.get', 'projects.create']);
  assert.ok(!JSON.stringify(tools).includes(hostKey));
  assert.ok(!JSON.stringify(tools).includes(token));
  const result = await tools[1].execute('sdk-call-id', { name: 'One project' });
  assert.equal(calls.length, 3);
  assert.deepEqual(calls[1].body, calls[2].body);
  assert.notEqual(calls[1].body?.request_key, 'sdk-call-id');
  assert.equal(calls[0].auth, `Bearer ${hostKey}`);
  assert.equal(calls[1].auth, `Bearer ${token}`);
  assert.ok(!JSON.stringify(result).includes(token));
  await assert.rejects(tools[1].execute('sdk-call-id', { name: 'X', actor_id: 'admin' }), /INVALID_TOOL_INPUT/);
  await assert.rejects(client.invoke('bad', 'catalog.create', {}), /TOOL_NOT_GRANTED/);
  client.dispose();
});

test('401 execution fence is not retried, and base URL is trusted configuration only', async () => {
  assert.throws(() => new S1RunClient({ baseUrl: 'http://example.com', hostKey }), /TRUSTED_API_ORIGIN/);
  let calls = 0;
  const client = new S1RunClient({ baseUrl: 'https://corpus.example', hostKey,
    fetcher: (async (url: string | URL | Request) => {
      calls++;
      if (String(url).endsWith('/claim')) return Response.json({ run_id: 'run', allowed_tools: ['account.get'], execution_token: token });
      return Response.json({ code: 'EXECUTION_FENCED' }, { status: 401 });
    }) as typeof fetch });
  await client.claim('run');
  await assert.rejects(client.invoke('call', 'account.get', {}), (error: unknown) => error instanceof RunProtocolError && error.status === 401);
  assert.equal(calls, 2);
  client.dispose();
});
