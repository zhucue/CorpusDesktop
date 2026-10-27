import assert from 'node:assert/strict';
import test from 'node:test';
import { CorpusApiClient } from '../../../contracts/types/s1.ts';
import { createS1ContractTools } from '../src/s1-tools.ts';
import { RUNTIME_MANIFEST } from '../src/s1-run-client.ts';

const id = 'dc397741-49cc-439f-af26-bd150a163acd';
function fixture(kind: 'platform' | 'account' | 'project' = 'platform') {
  const calls: { url: string; options: RequestInit }[] = [];
  const client = new CorpusApiClient({ csrf: () => 'trusted-csrf', transport: async (url, options = {}) => {
    calls.push({ url: String(url), options }); return Response.json({ items: [] });
  } });
  const scope = kind === 'project' ? { kind, projectId: 'project-a' } as const : { kind };
  return { client, calls, tools: createS1ContractTools(client, { scope, idempotencyKey: (invocation, action) => `${invocation}:${action}` }) };
}

test('index build captures fixed acquisition and shares the authenticated manual route', async () => {
  const { client, calls, tools } = fixture();
  const build = tools.find(tool => tool.name === 'indexes_build')!;
  await client.buildIndex('D12', id, 'manual-key');
  await build.execute('invocation', { source_id: 'D12', acquisition_id: id });
  await build.execute('invocation', { source_id: 'D12', acquisition_id: id });
  assert.equal(calls[0].url, '/api/v1/admin/sources/D12/index-builds');
  assert.equal(calls[0].url, calls[1].url);
  assert.equal(calls[1].options.body, JSON.stringify({ acquisition_id: id }));
  assert.equal((calls[1].options.headers as Record<string, string>)['X-CSRF-Token'], 'trusted-csrf');
  assert.equal((calls[1].options.headers as Record<string, string>)['Idempotency-Key'], (calls[2].options.headers as Record<string, string>)['Idempotency-Key']);
  for (const extra of [{ source_id: 'D01' }, { acquisition_id: 'latest' }, { recipe: 'custom' }, { url: 'https://other.test' }, { actor_id: id }]) {
    await assert.rejects(build.execute('i', { source_id: 'D12', acquisition_id: id, ...extra }), /INVALID_TOOL_INPUT/);
  }
  assert.equal(calls.length, 3);
});

test('index and sync jobs dispatch to disjoint fixed endpoints and reject mixed references', async () => {
  const { tools, calls } = fixture();
  const list = tools.find(tool => tool.name === 'jobs_list')!;
  await list.execute('i', { source_id: 'D12', task_kind: 'source_index', cursor: 'a+b', page_size: 10 });
  await list.execute('i', { source_id: 'D12' });
  assert.equal(new URL(calls[0].url, 'https://local.test').pathname, '/api/v1/admin/sources/D12/index-builds');
  assert.equal(new URL(calls[0].url, 'https://local.test').searchParams.get('cursor'), 'a+b');
  assert.equal(calls[1].url, '/api/v1/admin/sources/D12/sync-runs');
  for (const name of ['indexes_report', 'jobs_get', 'jobs_cancel', 'jobs_retry']) {
    await tools.find(tool => tool.name === name)!.execute('i', { index_run_id: id });
    await assert.rejects(tools.find(tool => tool.name === name)!.execute('i', { index_run_id: id, sync_run_id: id }), /INVALID_TOOL_INPUT/);
    await assert.rejects(tools.find(tool => tool.name === name)!.execute('i', { index_run_id: id, job_id: id }), /INVALID_TOOL_INPUT/);
  }
  assert.equal(calls[2].url, `/api/v1/admin/index-builds/${id}`);
  assert.equal(calls[3].url, calls[2].url);
  assert.equal(calls[4].url, `${calls[2].url}/cancel`);
  assert.equal(calls[5].url, `${calls[2].url}/retry`);
  assert.equal(calls[4].options.body, '{}');
});

test('index tools remain platform-only, production unavailable, and require a new archive schema', async () => {
  for (const kind of ['account', 'project'] as const) assert.ok(!fixture(kind).tools.some(tool => tool.name.startsWith('indexes_')));
  assert.ok(fixture().tools.every(tool => !tool.production_available));
  const project = fixture('project');
  await assert.rejects(project.tools.find(tool => tool.name === 'jobs_get')!.execute('i', { index_run_id: id }), /INVALID_TOOL_INPUT/);
  assert.equal(project.calls.length, 0);
  assert.equal(RUNTIME_MANIFEST.tool_schema, 's3-outcomes-tools-v1');
});
