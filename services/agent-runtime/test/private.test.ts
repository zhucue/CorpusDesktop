import assert from 'node:assert/strict';
import test from 'node:test';
import { CorpusApiClient } from '../../../contracts/types/s1.ts';
import { createS1ContractTools } from '../src/s1-tools.ts';
const id = 'ba89a93f-58e3-4f1c-a745-d10caf2f0b11';
function fixture(response: unknown) {
  const calls: { path: string; init: RequestInit }[] = [];
  const client = new CorpusApiClient({ csrf: () => 'trusted-csrf', transport: async (path, init = {}) => { calls.push({ path: String(path), init }); return Response.json(response); } });
  return { calls, client, tools: createS1ContractTools(client, { scope: { kind: 'project', projectId: 'bound' }, idempotencyKey: (invocation, action) => `${invocation}:${action}` }) };
}
const revision = { id, revision: 2, language: 'eng', counts: { documents: 1, segments: 3, characters: 50 }, quality: { text: 'PRIVATE' } };
const run = { id, job_id: id, project_id: 'bound', material_id: id, state: 'SUCCEEDED', result: revision, filename: 'PRIVATE.txt', progress: { processed_records: 500 }, error: { message: 'PRIVATE' } };

test('TXT import binds project and language, strips filename, text and derived counts', async () => {
  const { calls, tools } = fixture({ action_id: id, run });
  const tool = tools.find(item => item.capability_id === 'imports.start')!;
  const value = await tool.execute('same', { upload_id: id, language: 'eng' });
  await tool.execute('same', { upload_id: id, language: 'eng' });
  assert.equal(calls[0].path, '/api/v1/projects/bound/imports');
  assert.deepEqual(calls[0].init.headers, calls[1].init.headers);
  assert.equal(calls[0].init.credentials, 'include');
  assert.deepEqual(value.details, { action_id: id, import_id: id, job_id: id, project_id: 'bound', material_id: id, state: 'SUCCEEDED', material_revision_id: id, next_action: 'materials.get' });
  for (const field of ['PRIVATE', 'processed_records', 'counts']) assert.equal(JSON.stringify(value).includes(field), false);
  for (const extra of [{ language: 'auto' }, { project_id: 'other' }, { url: 'https://example.org' }, { recipe: 'custom' }]) await assert.rejects(tool.execute('i', { upload_id: id, language: 'eng', ...extra }), /INVALID_TOOL_INPUT/);
});

test('material metadata preserves fixed revisions without user filenames or quality', async () => {
  const material = { id, project_id: 'bound', state: 'READY', import_id: id, latest_revision: revision, revisions: [revision], name: 'PRIVATE' };
  for (const list of [false, true]) {
    const { tools } = fixture(list ? { items: [material], next_cursor: 'opaque' } : material);
    const result = await tools.find(item => item.capability_id === (list ? 'materials.list' : 'materials.get'))!.execute('i', list ? {} : { material_id: id });
    const encoded = JSON.stringify(result);
    for (const forbidden of ['PRIVATE', 'counts', 'characters', 'quality', 'filename']) assert.equal(encoded.includes(forbidden), false);
    assert.equal(encoded.includes('"revision":2'), true);
  }
});

test('mixed snapshot includes fixed selected revisions but does not change material scope', async () => {
  const snapshot = { id, project_id: 'bound', job_id: id, state: 'PREPARING', available: false };
  const { calls, tools } = fixture({ action_id: id, snapshot });
  const tool = tools.find(item => item.capability_id === 'snapshots.create')!;
  await tool.execute('i', { material_revision_ids: [id] });
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), { mount_ids: [], material_revision_ids: [id] });
  await assert.rejects(tool.execute('i', { material_revision_ids: [id, id] }), /INVALID_TOOL_INPUT/);
  assert.ok(tools.every(item => item.production_available === false));
});

test('TXT generic job metadata cannot bypass import projection', async () => {
  const job = { job_id: id, project_id: 'bound', kind: 'TXT_IMPORT', state: 'SUCCEEDED', filename: 'PRIVATE', result: { state: 'READY', material_revision_id: id, material_id: id }, progress: { processed_records: 90 }, error: { message: 'PRIVATE' } };
  const { tools } = fixture(job);
  const value = await tools.find(item => item.capability_id === 'jobs.get')!.execute('i', { job_id: id });
  assert.deepEqual(value.details, { job_id: id, import_id: id, project_id: 'bound', kind: 'TXT_IMPORT', state: 'SUCCEEDED', material_revision_id: id, next_action: 'imports.get' });
  assert.equal(JSON.stringify(value).includes('PRIVATE'), false);
});
