import assert from 'node:assert/strict';
import test from 'node:test';
import { CorpusApiClient } from '../../../contracts/types/s1.ts';
import { createS1ContractTools } from '../src/s1-tools.ts';
import { RUNTIME_MANIFEST } from '../src/s1-run-client.ts';

const id = 'ba89a93f-58e3-4f1c-a745-d10caf2f0b11';
const query = { dsl_version: 'corpus-query/v1', unit: 'character', pattern: { type: 'literal', value: '😀汉' }, within: 'sentence', overlap: 'all' } as const;
function fixture(response: unknown = {}) {
  const calls: { path: string; init: RequestInit }[] = [];
  const client = new CorpusApiClient({ csrf: () => 'trusted-csrf', transport: async (url, init = {}) => { calls.push({ path: String(url), init }); return Response.json(response, { status: 202 }); } });
  const tools = createS1ContractTools(client, { scope: { kind: 'project', projectId: 'bound-project' }, idempotencyKey: (invocation, capability) => `${invocation}:${capability}` });
  return { calls, client, tools };
}

test('snapshot creation binds one mount and returns metadata without source text/counts', async () => {
  const snapshot = { id, project_id: 'bound-project', job_id: id, state: 'PREPARING', available: false, counts: { sentences: 999 }, name: 'PRIVATE', members: [{ source_text: 'PRIVATE' }], error: { message: 'PRIVATE' } };
  const { calls, tools } = fixture({ action_id: id, existing: false, snapshot });
  const tool = tools.find(item => item.capability_id === 'snapshots.create')!;
  const first = await tool.execute('invocation', { mount_ids: [id] });
  await tool.execute('invocation', { mount_ids: [id] });
  assert.equal(calls[0].path, '/api/v1/projects/bound-project/snapshots');
  assert.deepEqual(calls[0].init.headers, calls[1].init.headers);
  assert.equal(calls[0].init.credentials, 'include');
  assert.deepEqual(first.details, { action_id: id, snapshot_id: id, project_id: 'bound-project', job_id: id, state: 'PREPARING', next_action: 'snapshots.get' });
  assert.equal(JSON.stringify(first).includes('PRIVATE'), false);
  for (const args of [{ mount_ids: [] }, { mount_ids: [id, id] }, { mount_ids: [id], project_id: 'other' }, { mount_ids: [id], snapshot_ids: [id] }]) await assert.rejects(tool.execute('i', args), /INVALID_TOOL_INPUT/);
});

test('research read adapters explicitly project only empty-scope metadata', async () => {
  const full = { id, project_id: 'bound-project', job_id: id, snapshot_id: id, result_set_id: id, state: 'SUCCEEDED', available: true,
    first_page_state: 'ready', count_state: 'complete', query, name: 'PRIVATE', total_hits: 123, hits: ['PRIVATE'], progress: { processed_records: 123 }, error: { message: 'PRIVATE' } };
  const { calls, tools } = fixture(full);
  for (const capability of ['snapshots.get', 'corpus.describe', 'results.get']) {
    const result = await tools.find(item => item.capability_id === capability)!.execute('i', capability === 'results.get' ? { result_set_id: id } : { snapshot_id: id });
    const encoded = JSON.stringify(result);
    for (const forbidden of ['PRIVATE', 'total_hits', 'processed_records', '😀汉']) assert.equal(encoded.includes(forbidden), false);
    assert.equal(Object.hasOwn(result.details as object, 'query'), false);
    if (capability === 'results.get') assert.deepEqual(result.details, { id, project_id: 'bound-project', snapshot_id: id, result_set_id: id, state: 'SUCCEEDED', first_page_state: 'ready', count_state: 'complete', next_action: 'manual_result_view' });
    else assert.deepEqual(result.details, { snapshot_id: id, project_id: 'bound-project', job_id: id, state: 'SUCCEEDED', next_action: 'manual_query' });
  }
  assert.equal(calls[2].path, `/api/v1/projects/bound-project/result-sets/${id}`);
});

test('material search/context are denied before transport even for registered adapters', async () => {
  const { calls, tools } = fixture();
  await assert.rejects(tools.find(item => item.capability_id === 'corpus.search')!.execute('i', { snapshot_id: id, query }), /SNAPSHOT_SCOPE_UNAVAILABLE/);
  await assert.rejects(tools.find(item => item.capability_id === 'results.context')!.execute('i', { result_set_id: id, ordinal: 0 }), /MODEL_EGRESS_DENIED/);
  const search = tools.find(item => item.capability_id === 'corpus.search')!;
  for (const extra of [{ context_tokens: 40 }, { context_codepoints: 201 }, { actor_id: id }, { query: { ...query, unit: 'token' } }, { query: { ...query, within: 'paragraph' } }]) await assert.rejects(search.execute('i', { snapshot_id: id, query, ...extra }), /INVALID_TOOL_INPUT/);
  assert.equal(calls.length, 0);
  assert.ok(tools.every(item => !item.production_available));
  assert.equal(RUNTIME_MANIFEST.tool_schema, 's3-outcomes-tools-v1');
  assert.notEqual(RUNTIME_MANIFEST.tool_schema, 's3-release-tools-v1');
});

test('manual query client preserves fixed context and safely encodes cursors with real HTTP verbs', async () => {
  const { calls, client } = fixture();
  await client.createQuery('project', { snapshot_id: id, query, context_codepoints: 0, page_size: 50 }, 'same-key');
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(JSON.parse(String(calls[0].init.body)).context_codepoints, 0);
  await client.hits('project', id, 'a/b+c=');
  assert.equal(calls[1].path, `/api/v1/projects/project/result-sets/${id}/hits?cursor=a%2Fb%2Bc%3D`);
  assert.equal(calls[1].init.method, 'GET');
  await client.context('project', id, 51);
  assert.equal(calls[2].path, `/api/v1/projects/project/result-sets/${id}/hits/51/context`);
  await client.prepareResult('project', id, 'prepare');
  assert.equal(calls[3].init.method, 'POST');
  assert.equal(calls[3].init.body, '{}');
});
