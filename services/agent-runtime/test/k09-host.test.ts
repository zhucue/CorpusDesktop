import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHash, randomUUID } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { S1RunClient, RUNTIME_MANIFEST, type Checkpoint, type Grant } from '../src/s1-run-client.ts';
import { executeFixtureSegment, fixtureCalls } from '../src/k09-executor.ts';
import { runDaemon, runtimeConfiguration, safeCode } from '../src/k09-daemon.ts';

const root = resolve('../../tmp/k09-host-tests'); mkdirSync(root, { recursive: true });
const folder = () => mkdtempSync(resolve(root, 'case-'));
function ledger() {
  const runId = randomUUID(), sessionId = randomUUID(), uploadId = randomUUID(), jobId = randomUUID();
  let cp: Checkpoint | null = null, archive: string | null = null, state = 'QUEUED', epoch = 0, writes = 0, jobState = 'QUEUED';
  const events: string[] = [], outputs = new Map<string, unknown>(), requests: { path: string; body: any }[] = [];
  const fetcher = (async (url, init) => {
    const path = new URL(String(url)).pathname; const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    requests.push({ path, body });
    if (path.endsWith('/claim') || path.endsWith('/claim-next')) {
      epoch++;
      const grant = { run_id: runId, session_id: sessionId, lease_epoch: epoch, state: 'RUNNING',
        scope: { scope_kind: 'project', project_id: randomUUID(), snapshot_ids: [], material_revision_ids: [], alignment_overlay_revision: null },
        scope_digest: 'a'.repeat(64), allowed_tools: ['uploads.complete', 'jobs.get'], runtime_manifest: RUNTIME_MANIFEST,
        base_checkpoint: null, resume_checkpoint: cp, config_id: 'local-fixture-v1',
        user_message: `fixture:complete-upload:${uploadId}`,
        continuation_message: cp ? `Resume waiting jobs for run ${runId}, epoch ${epoch}.` : null,
        waiting_jobs: cp ? [{ invocation_id: [...outputs.keys()][0], job_id: jobId, kind: 'UPLOAD_VALIDATE', state: jobState,
          report_tool: 'jobs.get', report_arguments: { job_id: jobId } }] : [], execution_token: 'execution-test-token' };
      return Response.json(path.endsWith('/claim-next') ? { grant } : grant);
    }
    if (path.endsWith('/heartbeat')) return Response.json({ state: 'RUNNING' });
    if (path.endsWith('/checkpoint') && !body) return Response.json({ checkpoint: cp, session_jsonl: archive });
    if (path.endsWith('/checkpoint')) {
      assert.equal(body.base_checkpoint_id, null);
      if (archive) assert.ok(body.session_jsonl.startsWith(archive));
      archive = body.session_jsonl;
      const rows = archive!.trimEnd().split('\n').map(line => JSON.parse(line));
      cp = { checkpoint_id: randomUUID(), sha256: createHash('sha256').update(archive!).digest('hex'),
        byte_size: Buffer.byteLength(archive!), sdk_session_id: sessionId, leaf_id: rows.at(-1).id, runtime_manifest: RUNTIME_MANIFEST };
      return Response.json(cp);
    }
    if (path.endsWith('/invocations')) {
      const id = randomUUID();
      const data = body.tool_name === 'uploads.complete' ? { job_id: jobId, state: 'QUEUED' } : { job_id: jobId, state: jobState, result: { sha256: 'b'.repeat(64) } };
      if (body.tool_name === 'uploads.complete') { writes++; assert.equal(writes, 1); assert.deepEqual(body.arguments, { upload_id: uploadId }); }
      else assert.equal(body.tool_name, 'jobs.get');
      const output = { result: { invocation_id: id, action_id: null, status: body.tool_name === 'uploads.complete' ? 'accepted' : 'succeeded', job_id: jobId }, data };
      outputs.set(id, output); return Response.json(output);
    }
    if (path.includes('/invocations/')) return Response.json(outputs.get(path.split('/').at(-1)!));
    if (path.endsWith('/events')) { events.push(body.kind); return Response.json({ sequence: events.length }); }
    if (path.endsWith('/suspend')) { state = 'WAITING_JOB'; assert.equal(body.checkpoint_id, cp!.checkpoint_id); return Response.json({ state, reason: null }); }
    if (path.endsWith('/settle')) {
      if (jobState !== 'SUCCEEDED') return Response.json({ code: 'JOB_NOT_SUCCEEDED' }, { status: 409 });
      state = 'SUCCEEDED'; return Response.json({ state, reason: null });
    }
    if (path.endsWith('/review')) { state = 'WAITING_REVIEW'; return Response.json({ state }); }
    throw new Error('UNEXPECTED_REQUEST');
  }) as typeof fetch;
  return { runId, uploadId, fetcher, requests, finishJob: () => { jobState = 'SUCCEEDED'; }, failJob: () => { jobState = 'FAILED'; },
    get cp() { return cp; }, get archive() { return archive; }, get state() { return state; }, get writes() { return writes; } };
}

test('real SDK pauses accepted job and reopens fixed archive under new epoch without repeating the write', async () => {
  const db = ledger();
  const firstClient = new S1RunClient({ baseUrl: 'http://127.0.0.1', hostKey: 'test-host', fetcher: db.fetcher });
  const firstGrant = await firstClient.claimNext(randomUUID()); assert.ok(firstGrant);
  const first = await executeFixtureSegment({ client: firstClient, grant: firstGrant, directory: folder(),
    scenario: { kind: 'complete-upload', uploadId: db.uploadId } });
  assert.equal(first.final.state, 'WAITING_JOB'); assert.equal(first.new_tool_executions, 1);
  const oldArchive = db.archive, oldCp = db.cp;
  const entries = oldArchive!.trimEnd().split('\n').map(line => JSON.parse(line));
  const users = entries.filter(e => e.type === 'message' && e.message.role === 'user');
  assert.equal(users.length, 1); assert.equal(users[0].message.content[0].text, firstGrant.user_message);
  firstClient.dispose(); db.finishJob();
  const secondClient = new S1RunClient({ baseUrl: 'http://127.0.0.1', hostKey: 'test-host', fetcher: db.fetcher });
  const grant = await secondClient.claimNext(randomUUID()); assert.ok(grant);
  const dir = folder();
  const second = await executeFixtureSegment({ client: secondClient, grant, directory: dir });
  assert.equal(second.final.state, 'SUCCEEDED'); assert.ok(second.lease_epoch > first.lease_epoch);
  assert.equal(second.restored, true); assert.deepEqual(second.tool_names, ['jobs_get']); assert.equal(db.writes, 1);
  assert.deepEqual(second.resume_checkpoint, oldCp);
  assert.equal(readFileSync(resolve(dir, readdirSync(dir)[0], 'base-checkpoint.jsonl'), 'utf8'), oldArchive);
  const allUsers = db.archive!.trimEnd().split('\n').map(line => JSON.parse(line)).filter(e => e.type === 'message' && e.message.role === 'user');
  assert.equal(allUsers.length, 2); assert.equal(allUsers[1].message.content[0].text, grant.continuation_message);
  secondClient.dispose();
});

test('ordinary fixture input never chooses a write; trusted scenario requires exact persisted intent and scope', () => {
  const uploadId = randomUUID();
  const grant = { config_id: 'local-fixture-v1', user_message: `fixture:complete-upload:${uploadId}`, scope: { scope_kind: 'project' } } as Grant;
  assert.deepEqual(fixtureCalls(grant), []);
  assert.deepEqual(fixtureCalls(grant, { kind: 'complete-upload', uploadId }), [{ tool: 'uploads.complete', args: { upload_id: uploadId } }]);
  assert.throws(() => fixtureCalls({ ...grant, user_message: 'please create a project' }, { kind: 'complete-upload', uploadId }), /INTENT_MISMATCH/);
  assert.throws(() => fixtureCalls({ ...grant, scope: { scope_kind: 'account' } }, { kind: 'complete-upload', uploadId }), /INTENT_MISMATCH/);
});

test('failed background job is observed by report tool then reviewed explicitly, never replayed', async () => {
  const db = ledger();
  const firstClient = new S1RunClient({ baseUrl: 'http://127.0.0.1', hostKey: 'test-host', fetcher: db.fetcher });
  const grant = await firstClient.claim(db.runId);
  await executeFixtureSegment({ client: firstClient, grant, directory: folder(), scenario: { kind: 'complete-upload', uploadId: db.uploadId } });
  firstClient.dispose(); db.failJob();
  const client = new S1RunClient({ baseUrl: 'http://127.0.0.1', hostKey: 'test-host', fetcher: db.fetcher });
  await assert.rejects(executeFixtureSegment({ client, grant: await client.claim(db.runId), directory: folder() }), /JOB_NOT_SUCCEEDED/);
  assert.equal(db.state, 'WAITING_REVIEW'); assert.equal(db.writes, 1);
  assert.equal(db.requests.filter(r => r.path.endsWith('/invocations') && r.body.tool_name === 'jobs.get').length, 1);
  assert.equal(db.requests.at(-1)!.body.reason, 'JOB_NOT_SUCCEEDED'); client.dispose();
});

test('aborted SDK segment cannot publish, and unknown credentials never appear in safe diagnostic', async () => {
  const db = ledger(); const client = new S1RunClient({ baseUrl: 'http://127.0.0.1', hostKey: 'test-host', fetcher: db.fetcher });
  const grant = await client.claim(db.runId); const stop = new AbortController(); stop.abort();
  await assert.rejects(executeFixtureSegment({ client, grant, directory: folder(), signal: stop.signal }));
  assert.equal(db.state, 'WAITING_REVIEW'); assert.equal(db.cp, null); assert.equal(db.writes, 0);
  assert.equal(safeCode(new Error('secret/url/token')), 'HOST_EXECUTION_FAILED'); client.dispose();
});

test('unconfigured daemon is not a consumer; explicit fixture polls sequentially and shutdown stops polling', async () => {
  let count = 0, active = 0, peak = 0;
  const stop = new AbortController();
  const config = runtimeConfiguration({ AGENT_WORK_DIR: 'tmp/k09-disabled' });
  setTimeout(() => stop.abort(), 30);
  await runDaemon(config, { signal: stop.signal, pollMs: 5, fetcher: (async () => { count++; throw new Error(); }) as typeof fetch });
  assert.equal(count, 0);
  const enabled = runtimeConfiguration({ AGENT_RUNTIME_MODE: 'fixture', AGENT_ENABLE_LOCAL_FIXTURE: 'true', AGENT_HOST_KEY: 'x'.repeat(32), AGENT_WORK_DIR: 'tmp/k09-poll' });
  const done = new AbortController();
  await runDaemon(enabled, { signal: done.signal, pollMs: 1, fetcher: (async () => {
    count++; active++; peak = Math.max(peak, active);
    await new Promise(r => setTimeout(r, 5)); active--; if (count === 3) done.abort();
    return Response.json({ grant: null });
  }) as typeof fetch });
  assert.equal(count, 3); assert.equal(peak, 1);
});

test('only explicit api internal origin is allowed; event ACK loss retries the same event ID once', async () => {
  assert.throws(() => new S1RunClient({ baseUrl: 'http://api:8000', hostKey: 'test' }), /TRUSTED_API/);
  assert.throws(() => new S1RunClient({ baseUrl: 'http://other:8000', hostKey: 'test', allowInternalApi: true }), /TRUSTED_API/);
  const bodies: unknown[] = [];
  const client = new S1RunClient({ baseUrl: 'http://api:8000', allowInternalApi: true, hostKey: 'test', fetcher: (async (url, init) => {
    if (String(url).endsWith('/claim')) return Response.json({ run_id: 'run', execution_token: 'token', allowed_tools: [] });
    bodies.push(JSON.parse(String(init?.body))); if (bodies.length === 1) throw new TypeError('lost ACK');
    return Response.json({ sequence: 1 });
  }) as typeof fetch });
  await client.claim('run'); await client.event('sdk.agent_settled');
  assert.equal(bodies.length, 2); assert.deepEqual(bodies[0], bodies[1]); client.dispose();
});

test('default fixture daemon executes a no-write SDK acknowledgement and removes its local private copy', async () => {
  const db = ledger(); db.finishJob();
  const directory = folder(); const completed: any[] = [];
  const config = runtimeConfiguration({ AGENT_RUNTIME_MODE: 'fixture', AGENT_ENABLE_LOCAL_FIXTURE: 'true',
    AGENT_HOST_KEY: 'x'.repeat(32), AGENT_WORK_DIR: directory });
  await runDaemon(config, { signal: new AbortController().signal, maxClaims: 1, fetcher: db.fetcher,
    onResult: result => completed.push(result) });
  assert.equal(completed.length, 1); assert.equal(completed[0].final.state, 'SUCCEEDED');
  assert.equal(completed[0].new_tool_executions, 0); assert.equal(db.writes, 0);
  assert.deepEqual(readdirSync(directory), []);
});
