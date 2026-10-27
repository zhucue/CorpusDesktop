import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHash, randomUUID } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { RUNTIME_MANIFEST, S1RunClient, type Checkpoint, type Grant } from '../src/s1-run-client.ts';
import { openCheckpoint, verifyArchive } from '../src/s1-run-checkpoint.ts';
import { runFixedModelHost } from '../src/s1-run-host.ts';

const testRoot = resolve('../../tmp/pi-checkpoint-tests');
mkdirSync(testRoot, { recursive: true });
function directory() { return mkdtempSync(resolve(testRoot, 'case-')); }
function metadata(archive: string): Checkpoint {
  const entries = archive.trimEnd().split('\n').map(line => JSON.parse(line));
  return { checkpoint_id: randomUUID(), sha256: createHash('sha256').update(archive).digest('hex'),
    byte_size: Buffer.byteLength(archive), sdk_session_id: entries[0].id, leaf_id: entries.at(-1).id,
    runtime_manifest: RUNTIME_MANIFEST };
}

test('real Pi reopens full JSONL, inherits project toolResult and does not repeat write', async () => {
  const sessionId = randomUUID(); let base: Checkpoint | null = null; let archive: string | null = null;
  const responses = new Map<string, unknown>(); let invocations = 0; let checks = 0;
  const fetcher = (async (url: string | URL | Request, init?: RequestInit) => {
    const path = new URL(String(url)).pathname;
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
    if (path.endsWith('/claim')) return Response.json({ run_id: path.split('/')[4], session_id: sessionId,
      scope: { scope_kind: 'account' }, scope_digest: 'fixed-scope', lease_epoch: base ? 2 : 1,
      state: 'RUNNING', allowed_tools: ['projects.create'], runtime_manifest: RUNTIME_MANIFEST,
      base_checkpoint: base, execution_token: 'test-execution-token' });
    if (path.endsWith('/heartbeat')) { checks++; return Response.json({ state: 'RUNNING' }); }
    if (path.endsWith('/checkpoint') && !body) return Response.json({ checkpoint: base, session_jsonl: archive });
    if (path.endsWith('/checkpoint')) {
      assert.equal(body.base_checkpoint_id, base?.checkpoint_id ?? null);
      assert.deepEqual(body.runtime_manifest, RUNTIME_MANIFEST);
      if (archive) assert.ok(body.session_jsonl.startsWith(archive));
      archive = body.session_jsonl; base = metadata(archive!); return Response.json(base);
    }
    if (path.endsWith('/invocations')) {
      invocations++;
      assert.equal(body.tool_name, 'projects.create');
      const id = randomUUID();
      const output = { result: { invocation_id: id, action_id: randomUUID(), status: 'succeeded' },
        data: { id: randomUUID(), name: body.arguments.name } };
      responses.set(id, output); return Response.json(output);
    }
    if (path.includes('/invocations/')) return Response.json(responses.get(path.split('/').at(-1)!));
    if (path.endsWith('/settle')) { assert.equal(body.checkpoint_id, base?.checkpoint_id); return Response.json({ state: 'SUCCEEDED', reason: null }); }
    if (path.endsWith('/events')) return Response.json({ sequence: 1 });
    throw new Error('UNEXPECTED_REQUEST');
  }) as typeof fetch;
  const initial = await runFixedModelHost({ baseUrl: 'http://127.0.0.1', hostKey: 'test-host', runId: randomUUID(), directory: directory(), fetcher });
  assert.equal(initial.new_tool_executions, 1); assert.equal(initial.restored, false); assert.equal(initial.model_requests, 2);
  const oldArchive = archive!; const oldMetadata = base!; const secondDir = directory();
  let sawHistory = false;
  const resumed = await runFixedModelHost({ baseUrl: 'http://127.0.0.1', hostKey: 'test-host', runId: randomUUID(), directory: secondDir, fetcher,
    onModelRequest: context => { sawHistory = context.messages.some(message => message.role === 'toolResult' && message.toolName === 'projects_create'); } });
  assert.equal(sawHistory, true); assert.equal(resumed.restored, true); assert.equal(resumed.inherited_tool_results, 1);
  assert.equal(resumed.new_tool_executions, 0); assert.equal(resumed.model_requests, 1); assert.equal(invocations, 1); assert.equal(checks, 3);
  assert.deepEqual(resumed.project, initial.project); assert.notEqual(resumed.checkpoint.checkpoint_id, initial.checkpoint.checkpoint_id);
  assert.ok(JSON.stringify(resumed.final_model_content).includes((initial.project as { id: string }).id));
  // The working file grew; the downloaded base remains byte-for-byte immutable.
  const { readdirSync } = await import('node:fs');
  const runDirectory = resolve(secondDir, readdirSync(secondDir)[0]);
  assert.equal(readFileSync(resolve(runDirectory, 'base-checkpoint.jsonl'), 'utf8'), oldArchive);
  verifyArchive(oldMetadata, oldArchive);
});

test('archive tampering, runtime drift and missing base fail before Pi can open a working copy', () => {
  const sessionId = randomUUID();
  const archive = JSON.stringify({ type: 'session', id: sessionId, version: 3 }) + '\n' +
    JSON.stringify({ type: 'message', id: 'leaf', parentId: null, message: { role: 'assistant', stopReason: 'stop' } }) + '\n';
  const checkpoint = metadata(archive);
  assert.throws(() => verifyArchive(checkpoint, archive + 'x'), /DIGEST_MISMATCH/);
  assert.throws(() => verifyArchive({ ...checkpoint, runtime_manifest: { ...RUNTIME_MANIFEST, sdk_version: 'other' } as never }, archive), /RUNTIME_MISMATCH/);
  assert.throws(() => verifyArchive({ ...checkpoint, runtime_manifest: { ...RUNTIME_MANIFEST, tool_schema: 's3-tools-v1' } as never }, archive), /RUNTIME_MISMATCH/);
  const grant = { runtime_manifest: RUNTIME_MANIFEST, base_checkpoint: checkpoint } as Grant;
  assert.throws(() => openCheckpoint(grant, { checkpoint, session_jsonl: null }, directory()), /CHECKPOINT_MISSING/);
  assert.throws(() => openCheckpoint(grant, { checkpoint: null, session_jsonl: null }, directory()), /BASE_MISMATCH/);
});

test('checkpoint and terminal settle retry the identical request after response loss; old epoch rejection is not retried', async () => {
  const bodies: Record<string, unknown>[][] = [[], []]; let fencedCalls = 0;
  const client = new S1RunClient({ baseUrl: 'http://127.0.0.1', hostKey: 'test-host', fetcher: (async (url, init) => {
    const path = String(url); const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    if (path.endsWith('/claim')) return Response.json({ run_id: 'run', allowed_tools: [], runtime_manifest: RUNTIME_MANIFEST, base_checkpoint: null, execution_token: 'test-token' });
    if (path.endsWith('/heartbeat')) { fencedCalls++; return Response.json({ code: 'EXECUTION_FENCED' }, { status: 401 }); }
    const calls = bodies[path.endsWith('/checkpoint') ? 0 : 1]; calls.push(body);
    if (calls.length === 1) throw new TypeError('lost response after commit');
    return Response.json(path.endsWith('/checkpoint') ? { checkpoint_id: 'checkpoint' } : { state: 'SUCCEEDED', reason: null });
  }) as typeof fetch });
  await client.claim('run'); await client.uploadCheckpoint('archive'); await client.settle('checkpoint');
  for (const calls of bodies) { assert.equal(calls.length, 2); assert.deepEqual(calls[0], calls[1]); }
  await assert.rejects(client.heartbeat(), /EXECUTION_FENCED/); assert.equal(fencedCalls, 1);
  client.dispose();
});

test('unreliable checkpoint asks for review and never makes a model request', async () => {
  let modelRequests = 0; let reviewed = false;
  const fetcher = (async (url, init) => {
    if (String(url).endsWith('/claim')) return Response.json({ run_id: randomUUID(), session_id: randomUUID(), lease_epoch: 2,
      runtime_manifest: RUNTIME_MANIFEST, base_checkpoint: { checkpoint_id: 'missing' }, execution_token: 'test-token' });
    if (String(url).endsWith('/checkpoint')) return Response.json({ checkpoint: null, session_jsonl: null });
    if (String(url).endsWith('/review')) { reviewed = true; assert.equal(JSON.parse(String(init?.body)).reason, 'CHECKPOINT_RESTORE_FAILED'); return Response.json({ state: 'WAITING_REVIEW' }); }
    throw new Error('UNEXPECTED_REQUEST');
  }) as typeof fetch;
  await assert.rejects(runFixedModelHost({ baseUrl: 'http://127.0.0.1', hostKey: 'test-host', runId: randomUUID(), directory: directory(), fetcher,
    onModelRequest: () => { modelRequests++; } }), /CHECKPOINT_BASE_MISMATCH/);
  assert.equal(modelRequests, 0); assert.equal(reviewed, true);
});

test('permission failure before the next model request stops context reuse and checkpoint publication', async () => {
  let checks = 0; let requests = 0; let writes = 0; let reviewed = false;
  const fetcher = (async (url, init) => {
    const path = String(url);
    if (path.endsWith('/claim')) return Response.json({ run_id: randomUUID(), session_id: randomUUID(), lease_epoch: 1,
      scope: { scope_kind: 'account' }, allowed_tools: ['projects.create'], runtime_manifest: RUNTIME_MANIFEST,
      base_checkpoint: null, execution_token: 'test-token' });
    if (path.endsWith('/checkpoint') && !init?.body) return Response.json({ checkpoint: null, session_jsonl: null });
    if (path.endsWith('/heartbeat')) return ++checks === 1 ? Response.json({ state: 'RUNNING' }) : Response.json({ code: 'EXECUTION_FENCED' }, { status: 401 });
    if (path.endsWith('/invocations')) { writes++; return Response.json({ result: { invocation_id: randomUUID(), action_id: randomUUID(), status: 'succeeded' }, data: { id: randomUUID() } }); }
    if (path.endsWith('/review')) { reviewed = true; return Response.json({ state: 'WAITING_REVIEW' }); }
    if (path.endsWith('/events')) return Response.json({ sequence: 1 });
    throw new Error('UNEXPECTED_PUBLICATION_OR_REPLAY');
  }) as typeof fetch;
  await assert.rejects(runFixedModelHost({ baseUrl: 'http://127.0.0.1', hostKey: 'test-host', runId: randomUUID(), directory: directory(), fetcher,
    onModelRequest: () => { requests++; } }), /EXECUTION_FENCED/);
  assert.equal(checks, 2); assert.equal(requests, 1); assert.equal(writes, 1); assert.equal(reviewed, true);
});
