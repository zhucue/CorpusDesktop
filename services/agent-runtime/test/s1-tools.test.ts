import assert from 'node:assert/strict';
import test from 'node:test';
import { CorpusApiClient } from '../../../contracts/types/s1.ts';
import { createS1ContractTools } from '../src/s1-tools.ts';

test('default browser transport retains the global receiver', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async function (this: unknown) {
    assert.equal(this, globalThis);
    return new Response(JSON.stringify({ items: [] }));
  };
  try {
    const client = new CorpusApiClient({ csrf: () => undefined });
    assert.deepEqual(await client.projects(), { items: [] });
  } finally { globalThis.fetch = original; }
});

function fixture(responses: Record<string, unknown>) {
  const calls: { url: string; options: RequestInit }[] = [];
  const transport: typeof fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    const value = responses[String(url)];
    return new Response(JSON.stringify(value ?? {}), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  const client = new CorpusApiClient({ base: 'https://trusted.example', transport, csrf: () => 'host-csrf-secret' });
  const context = { scope: { kind: 'project' as const, projectId: 'project-1' }, idempotencyKey: (id: string, name: string) => `${id}:${name}` };
  return { client, calls, tools: createS1ContractTools(client, context) };
}

test('only fixed actions are exposed; authority arguments are rejected', async () => {
  const { tools, calls } = fixture({});
  assert.equal(tools.length, 41);
  assert.ok(tools.every(tool => tool.production_available === false));
  assert.ok(!tools.some(tool => /shell|fetch|login|content|sql/.test(tool.name)));
  const get = tools.find(tool => tool.name === 'projects_get')!;
  await assert.rejects(get.execute('i', { project_id: 'other', actor_id: 'admin', url: 'https://evil' }), /INVALID_TOOL_INPUT/);
  assert.equal(calls.length, 0);
});

test('account result strips CSRF and does not expose login as a tool', async () => {
  const { client } = fixture({ 'https://trusted.example/api/v1/auth/session': { actor: { id: 'u', email: 'u@example.test', is_platform_admin: false }, csrf_token: 'never-model-visible' } });
  const tools = createS1ContractTools(client, { scope: { kind: 'account' }, idempotencyKey: () => 'host-key' });
  const result = await tools.find(tool => tool.name === 'account_get')!.execute('i', {});
  assert.ok(!JSON.stringify(result).includes('csrf'));
  assert.equal(tools.length, 7);
});

test('upload tool strips transfer URL and uses host-owned idempotency and CSRF', async () => {
  const { tools, calls } = fixture({ 'https://trusted.example/api/v1/projects/project-1/uploads': { upload_id: 'upload-1', action_id: 'action-1', project_id: 'project-1', state: 'CREATED', upload_url: 'secret-url', method: 'PUT' } });
  const args = { filename: 'sample.txt', size: 3, media_type: 'text/plain', sha256: 'a'.repeat(64) };
  const tool = tools.find(item => item.name === 'uploads_create')!;
  const result = await tool.execute('invocation-1', args);
  await tool.execute('invocation-1', args);
  assert.ok(!JSON.stringify(result).includes('secret-url'));
  assert.deepEqual(JSON.parse(String(calls[0].options.body)), args);
  assert.equal((calls[0].options.headers as Record<string, string>)['X-CSRF-Token'], 'host-csrf-secret');
  assert.equal((calls[0].options.headers as Record<string, string>)['Idempotency-Key'], (calls[1].options.headers as Record<string, string>)['Idempotency-Key']);
});

test('cross-scope job mutation is rejected before POST', async () => {
  const { tools, calls } = fixture({ 'https://trusted.example/api/v1/jobs/other-job': { job_id: 'other-job', project_id: 'other-project' } });
  await assert.rejects(tools.find(tool => tool.name === 'jobs_cancel')!.execute('i', { job_id: 'other-job' }), /JOB_OUT_OF_SCOPE/);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.method, 'GET');
});

test('manual client and adapter send identical upload business arguments', async () => {
  const { client, tools, calls } = fixture({});
  const args = { filename: 'x.txt', size: 12, media_type: 'text/plain', sha256: 'b'.repeat(64) };
  await client.createUpload('project-1', args, 'manual-key');
  await tools.find(tool => tool.name === 'uploads_create')!.execute('i', args);
  assert.equal(calls[0].url, calls[1].url);
  assert.equal(calls[0].options.body, calls[1].options.body);
});

test('source discovery is available without a project and preserves pagination', async () => {
  const { client, calls } = fixture({});
  const tools = createS1ContractTools(client, { scope: { kind: 'account' }, idempotencyKey: () => 'key' });
  assert.ok(!tools.some(tool => tool.name.startsWith('catalog_')));
  await tools.find(tool => tool.name === 'sources_list')!.execute('i', { q: 'D12 & Tatoeba', language: 'zh', category: 'parallel' });
  const url = new URL(calls[0].url);
  assert.equal(url.pathname, '/api/v1/sources');
  assert.equal(url.searchParams.get('q'), 'D12 & Tatoeba');
  assert.equal(url.searchParams.get('category'), 'parallel');
  await tools.find(tool => tool.name === 'sources_versions')!.execute('i2', { source_id: 'D12', cursor: 'next+cursor', page_size: 20 });
  assert.equal(new URL(calls[1].url).searchParams.get('cursor'), 'next+cursor');
  assert.equal(new URL(calls[1].url).searchParams.get('page_size'), '20');
});

test('catalog writes use fixed routes, host idempotency and optimistic revision', async () => {
  const { client, calls } = fixture({});
  const tools = createS1ContractTools(client, { scope: { kind: 'platform' }, idempotencyKey: (id, action) => `${id}:${action}` });
  const args = { source_id: 'D99', name: 'Example', publisher: 'Publisher', entry_kind: 'dataset', categories: ['parallel'], languages: ['zh', 'en'], official_url: 'https://example.org/reference', materials: 'sentences', access_route: 'catalog', boundary: 'pending review', expected_revision: 2 };
  const update = tools.find(tool => tool.name === 'catalog_update')!;
  await update.execute('i', args);
  await update.execute('i', args);
  assert.equal(calls[0].url, 'https://trusted.example/api/v1/admin/catalog/D99');
  assert.equal(calls[0].options.method, 'PATCH');
  const body = JSON.parse(String(calls[0].options.body));
  assert.equal(body.expected_revision, 2);
  assert.equal(body.source_id, undefined);
  assert.equal(body.official_url, 'https://example.org/reference');
  assert.equal((calls[0].options.headers as Record<string, string>)['Idempotency-Key'], (calls[1].options.headers as Record<string, string>)['Idempotency-Key']);
  await assert.rejects(update.execute('i', { ...args, capabilities: { fulltext_analysis: true } }), /INVALID_TOOL_INPUT/);
  await assert.rejects(update.execute('i', { ...args, actor_id: 'admin' }), /INVALID_TOOL_INPUT/);
  assert.equal(calls.length, 2);
});

test('all three trusted scopes expose the same source reads but only platform exposes metadata writes', () => {
  const { client } = fixture({});
  for (const scope of [{ kind: 'account' } as const, { kind: 'platform' } as const, { kind: 'project', projectId: 'p' } as const]) {
    const tools = createS1ContractTools(client, { scope, idempotencyKey: () => 'key' });
    for (const name of ['account_get', 'sources_list', 'sources_get', 'sources_versions']) assert.ok(tools.some(tool => tool.name === name));
    assert.equal(tools.some(tool => tool.name === 'catalog_create'), scope.kind === 'platform');
    assert.ok(tools.every(tool => tool.production_available === false));
  }
});
