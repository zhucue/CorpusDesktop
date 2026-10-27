import assert from 'node:assert/strict';
import test from 'node:test';
import { CorpusApiClient } from '../../../contracts/types/s1.ts';
import { createS1ContractTools } from '../src/s1-tools.ts';
import { RUNTIME_MANIFEST } from '../src/s1-run-client.ts';

const id = 'dc397741-49cc-439f-af26-bd150a163acd';
function fixture(kind: 'platform' | 'project' | 'account') {
  const calls: { url: string; options: RequestInit }[] = [];
  const client = new CorpusApiClient({ csrf: () => 'trusted', transport: async (url, options = {}) => { calls.push({ url: String(url), options }); return Response.json({}); } });
  const scope = kind === 'project' ? { kind, projectId: 'bound-project' } as const : { kind };
  return { client, calls, tools: createS1ContractTools(client, { scope, idempotencyKey: (invocation, capability) => `${invocation}:${capability}` }) };
}
test('manual policy client and publish adapter use fixed routes and explicit decisions', async () => {
  const { client, tools, calls } = fixture('platform');
  const update = tools.find(item => item.name === 'policies_update')!;
  const args = { policy_kind: 'source', source_id: 'fixture', acquisition_id: id, expected_revision: 0, decision: 'allow', review_note: 'Synthetic fixture only', evidence_urls: ['https://example.test/license'] };
  const input = { expected_revision: 0, decision: 'allow' as const, export_decision: 'deny' as const, review_note: args.review_note, evidence_urls: args.evidence_urls };
  await client.updateSourcePolicy('fixture', id, input, 'trusted-manual-key');
  await client.updateSourcePolicy('fixture', id, input, 'trusted-manual-key');
  assert.equal(calls[0].url, `/api/v1/admin/sources/fixture/policies/${id}`);
  assert.equal(JSON.parse(String(calls[0].options.body)).policy_kind, undefined);
  assert.equal(JSON.parse(String(calls[0].options.body)).export_decision, 'deny');
  assert.deepEqual(calls[0].options.headers, calls[1].options.headers);
  assert.equal(calls[0].options.body, calls[1].options.body);
  for (const extra of [{ model_egress: true }, { actor_id: id }, { policy_kind: 'model' }, { evidence_urls: [] }]) await assert.rejects(update.execute('i', { ...args, ...extra }), /INVALID_TOOL_INPUT/);
  await tools.find(item => item.name === 'releases_publish')!.execute('i', { source_id: 'fixture', index_id: id, expected_policy_revision: 1 });
  assert.equal(calls[2].url, '/api/v1/admin/sources/fixture/releases');
});
test('mount tools bind project on trusted host and expose manifest read explicitly', async () => {
  const { tools, calls } = fixture('project');
  const create = tools.find(item => item.name === 'mounts_create')!;
  await create.execute('i', { source_snapshot_id: id });
  assert.equal(calls[0].url, '/api/v1/projects/bound-project/mounts');
  for (const extra of [{ project_id: 'other' }, { filters: {} }, { source_snapshot_id: 'latest' }]) await assert.rejects(create.execute('i', { source_snapshot_id: id, ...extra }), /INVALID_TOOL_INPUT/);
  await tools.find(item => item.name === 'mounts_manifest')!.execute('i', { mount_id: id });
  assert.equal(calls[1].url, `/api/v1/projects/bound-project/mounts/${id}/manifest`);
  await tools.find(item => item.name === 'mounts_remove')!.execute('i', { mount_id: id });
  assert.equal(calls[2].options.body, '{}');
});
test('release metadata reads cover each scope, authority tools do not, old checkpoint schema differs', () => {
  for (const kind of ['account', 'project', 'platform'] as const) {
    const tools = fixture(kind).tools;
    assert.ok(tools.some(item => item.name === 'releases_get'));
    assert.equal(tools.some(item => item.name === 'policies_update'), kind === 'platform');
    assert.equal(tools.some(item => item.name === 'mounts_create'), kind === 'project');
    assert.ok(tools.every(item => !item.production_available));
  }
  assert.equal(RUNTIME_MANIFEST.tool_schema, 's3-outcomes-tools-v1');
  assert.notEqual(RUNTIME_MANIFEST.tool_schema, 's3-tools-v1');
});
