import assert from 'node:assert/strict';
import test from 'node:test';
import { CorpusApiClient } from '../../../contracts/types/s1.ts';
import { createS1ContractTools } from '../src/s1-tools.ts';

const syncId = 'dc397741-49cc-439f-af26-bd150a163acd';
function fixture(kind: 'platform' | 'account' | 'project' = 'platform') {
  const calls: { url: string; options: RequestInit }[] = [];
  const client = new CorpusApiClient({ csrf: () => 'host-csrf', transport: async (url, options = {}) => {
    calls.push({ url: String(url), options }); return Response.json({ items: [], source_id: 'D12' });
  } });
  const scope = kind === 'project' ? { kind, projectId: 'project-a' } as const : { kind };
  return { client, calls, tools: createS1ContractTools(client, { scope, idempotencyKey: (id, action) => `${id}:${action}` }) };
}

test('sync uses fixed D12 route, empty HTTP body, host CSRF and stable idempotency', async () => {
  const { client, tools, calls } = fixture();
  const start = tools.find(tool => tool.name === 'sync_start')!;
  await client.startSync('D12', 'manual');
  await start.execute('invocation', { source_id: 'D12' });
  await start.execute('invocation', { source_id: 'D12' });
  assert.equal(calls[0].url, '/api/v1/admin/sources/D12/sync-runs');
  assert.equal(calls[0].url, calls[1].url);
  assert.equal(calls[0].options.body, '{}'); assert.equal(calls[1].options.body, '{}');
  assert.equal((calls[1].options.headers as Record<string, string>)['X-CSRF-Token'], 'host-csrf');
  assert.equal((calls[1].options.headers as Record<string, string>)['Idempotency-Key'], (calls[2].options.headers as Record<string, string>)['Idempotency-Key']);
  for (const args of [{ source_id: 'D01' }, { source_id: 'D12', url: 'https://other.test' }, { source_id: 'D12', actor_id: 'admin' }]) {
    await assert.rejects(start.execute('i', args), /INVALID_TOOL_INPUT/);
  }
  assert.equal(calls.length, 3);
});

test('platform job branches reject project references and account has no sync tools', async () => {
  const platform = fixture(); const project = fixture('project'); const account = fixture('account');
  for (const name of ['jobs_get', 'jobs_cancel', 'jobs_retry']) {
    await assert.rejects(platform.tools.find(tool => tool.name === name)!.execute('i', { job_id: syncId }), /INVALID_TOOL_INPUT/);
    await assert.rejects(platform.tools.find(tool => tool.name === name)!.execute('i', { job_id: syncId, sync_run_id: syncId }), /INVALID_TOOL_INPUT/);
    await assert.rejects(project.tools.find(tool => tool.name === name)!.execute('i', { sync_run_id: syncId }), /INVALID_TOOL_INPUT/);
  }
  assert.equal(platform.calls.length + project.calls.length, 0);
  assert.ok(!account.tools.some(tool => tool.name.startsWith('sync_') || tool.name.startsWith('jobs_')));
  assert.ok(!project.tools.some(tool => tool.name.startsWith('sync_')));
  assert.ok(platform.tools.every(tool => !tool.production_available));
  assert.ok(!platform.tools.some(tool => tool.name === 'sync_check'));
});

test('sync report and platform jobs target the same protected source routes with real pagination', async () => {
  const { tools, calls } = fixture();
  await tools.find(tool => tool.name === 'jobs_list')!.execute('i', { source_id: 'D12', cursor: 'next+page', page_size: 10 });
  const url = new URL(calls[0].url, 'https://local.test');
  assert.equal(url.pathname, '/api/v1/admin/sources/D12/sync-runs');
  assert.equal(url.searchParams.get('cursor'), 'next+page'); assert.equal(url.searchParams.get('page_size'), '10');
  for (const name of ['sync_report', 'jobs_get', 'jobs_cancel', 'jobs_retry']) await tools.find(tool => tool.name === name)!.execute('i', { sync_run_id: syncId });
  assert.equal(calls[1].url, `/api/v1/admin/sync-runs/${syncId}`); assert.equal(calls[1].url, calls[2].url);
  assert.equal(calls[3].url, `/api/v1/admin/sync-runs/${syncId}/cancel`); assert.equal(calls[4].url, `/api/v1/admin/sync-runs/${syncId}/retry`);
  assert.equal(calls[3].options.method, 'POST'); assert.equal(calls[3].options.body, '{}');
});
