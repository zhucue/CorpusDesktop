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

test('evidence registration resolves fixed hit and strips material from model response', async () => {
  const { calls, tools } = fixture({ action_id: id, existing: false, evidence: { id, project_id: 'bound', query_run_id: id, result_set_id: id, snapshot_id: id, hit_ref: { result_set_id: id, ordinal: 0 }, context: { text: 'PRIVATE' }, method: { query: 'PRIVATE', counts: 100 } } });
  const tool = tools.find(t => t.capability_id === 'evidence.create')!;
  const value = await tool.execute('i', { result_set_id: id, ordinal: 0 });
  assert.equal(calls[0].path, '/api/v1/projects/bound/evidence');
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), { result_set_id: id, ordinal: 0 });
  assert.equal(JSON.stringify(value).includes('PRIVATE'), false);
  assert.deepEqual(value.details, { action_id: id, existing: false, evidence_id: id, project_id: 'bound', query_run_id: id, result_set_id: id, snapshot_id: id, hit_ref: { result_set_id: id, ordinal: 0 }, next_action: 'manual_evidence_view' });
  await assert.rejects(tool.execute('i', { result_set_id: id, ordinal: 0, quote: 'forged' }), /INVALID_TOOL_INPUT/);
});

test('notes and evidence material tools reject before transport; accept cannot self-confirm', async () => {
  const { calls, tools } = fixture({});
  for (const [name, args] of [
    ['evidence.get', { evidence_id: id }], ['notes.get', { note_id: id }],
    ['notes.create', { title: 'x', body: 'text' }],
    ['notes.update', { note_id: id, expected_revision: 1, title: 'x', body: 'text' }],
  ] as const) await assert.rejects(tools.find(t => t.capability_id === name)!.execute('i', args), /MODEL_EGRESS_DENIED/);
  const accept = tools.find(t => t.capability_id === 'notes.accept')!;
  await assert.rejects(accept.execute('i', { note_id: id, expected_revision: 1 }), /HUMAN_AUTHORIZATION_REQUIRED/);
  await assert.rejects(accept.execute('i', { note_id: id, expected_revision: 1, confirmed: true }), /INVALID_TOOL_INPUT/);
  assert.equal(calls.length, 0);
});

test('note and export lists exclude text filenames and computed artifact counts', async () => {
  const note = fixture({ items: [{ id, project_id: 'bound', revision: 2, status: 'draft', evidence_ids: [id], query_run_ids: [], authorization_evidence_ids: [id], authorization_query_run_ids: [], title: 'PRIVATE', body: 'PRIVATE' }], next_cursor: null, total: 1 });
  const a = await note.tools.find(t => t.capability_id === 'notes.list')!.execute('i', {});
  assert.equal(JSON.stringify(a).includes('PRIVATE'), false);
  assert.deepEqual(a.details, { project_id: 'bound', items: [{ note_id: id, project_id: 'bound', revision: 2, status: 'draft', evidence_ids: [id], query_run_ids: [], authorization_evidence_ids: [id], authorization_query_run_ids: [], next_action: 'manual_note_view' }], next_cursor: null, total: 1 });
  const exp = fixture({ items: [{ id, job_id: id, project_id: 'bound', state: 'SUCCEEDED', format: 'csv', result: { filename: 'PRIVATE.zip', row_count: 500 } }], next_cursor: null, total: 1 });
  const b = await exp.tools.find(t => t.capability_id === 'exports.list')!.execute('i', {});
  assert.equal(JSON.stringify(b).includes('PRIVATE'), false);
  assert.equal(JSON.stringify(b).includes('row_count'), false);
  assert.deepEqual(b.details, { project_id: 'bound', items: [{ export_id: id, job_id: id, project_id: 'bound', state: 'SUCCEEDED', next_action: 'manual_download' }], next_cursor: null, total: 1 });
});

test('exports bind query sequence and shared trusted invocation key without returning URL', async () => {
  const { calls, tools } = fixture({ action_id: id, run: { id, job_id: id, project_id: 'bound', state: 'QUEUED', format: 'json', filename: 'PRIVATE' } });
  const tool = tools.find(t => t.capability_id === 'exports.create')!;
  const input = { target: { kind: 'query_runs', query_run_ids: [id] }, format: 'json' };
  const value = await tool.execute('same', input); await tool.execute('same', input);
  assert.equal(calls[0].path, '/api/v1/projects/bound/exports');
  assert.deepEqual(calls[0].init.headers, calls[1].init.headers);
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), input);
  assert.equal(JSON.stringify(value).includes('PRIVATE'), false);
  await assert.rejects(tool.execute('i', { ...input, target: { kind: 'query_runs', query_run_ids: [id, id] } }), /INVALID_TOOL_INPUT/);
  await assert.rejects(tool.execute('i', { ...input, cursor: 'page' }), /INVALID_TOOL_INPUT/);
});

test('generic EXPORT jobs cannot leak artifact details through model projection', async () => {
  const { tools } = fixture({ job_id: id, project_id: 'bound', kind: 'EXPORT', state: 'SUCCEEDED', filename: 'PRIVATE', progress: { processed_records: 999 }, result: { export_id: id, state: 'READY', text: 'PRIVATE' } });
  const value = await tools.find(t => t.capability_id === 'jobs.get')!.execute('i', { job_id: id });
  assert.deepEqual(value.details, { job_id: id, export_id: id, project_id: 'bound', kind: 'EXPORT', state: 'SUCCEEDED', next_action: 'exports.get' });
  assert.equal(JSON.stringify(value).includes('PRIVATE'), false);
});


test('legacy manual-HTTP policy adapter cannot simulate trusted export approval preservation', async () => {
  const { calls, client } = fixture({});
  const tools = createS1ContractTools(client, { scope: { kind: 'platform' }, idempotencyKey: () => 'trusted' });
  const tool = tools.find(t => t.capability_id === 'policies.update')!;
  const input = { policy_kind: 'source', source_id: 'fixture', acquisition_id: id, expected_revision: 1, decision: 'allow', review_note: 'review', evidence_urls: ['https://example.org/license'] };
  await assert.rejects(tool.execute('i', input), /HUMAN_AUTHORIZATION_REQUIRED/);
  await assert.rejects(tool.execute('i', { ...input, export_decision: 'allow' }), /INVALID_TOOL_INPUT/);
  assert.equal(calls.length, 0);
});
