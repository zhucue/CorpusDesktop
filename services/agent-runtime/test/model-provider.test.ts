import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHash, randomUUID } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { modelConfiguration } from '../src/model-config.ts';
import { runtimeConfiguration, runDaemon } from '../src/k09-daemon.ts';
import { executeSegment } from '../src/k09-executor.ts';
import { S1RunClient, type Checkpoint, type RuntimeManifest } from '../src/s1-run-client.ts';
import { protocolServer, writeReply } from './provider-fixture.ts';

const root = fileURLToPath(new URL('../../../tmp/model-protocol-tests', import.meta.url)); mkdirSync(root, { recursive: true });
const folder = () => mkdtempSync(resolve(root, 'case-'));
const key = 'synthetic-provider-key-NOT-A-CREDENTIAL';
const env = (api: string, url: string) => ({ AGENT_MODEL_API: api, AGENT_MODEL_BASE_URL: url,
  AGENT_MODEL_ID: 'research-model-v1', AGENT_MODEL_ALLOW_LOOPBACK_HTTP: 'true' });

function ledger(manifest: RuntimeManifest, configId: string) {
  const runId = randomUUID(), sessionId = randomUUID(), uploadId = randomUUID(), jobId = randomUUID();
  let cp: Checkpoint | null = null, archive: string | null = null, epoch = 0, state = 'QUEUED', jobState = 'QUEUED';
  const requests: { path: string; body: any }[] = [], outputs = new Map<string, any>();
  const fetcher = (async (url, init) => {
    const path = new URL(String(url)).pathname, body = init?.body ? JSON.parse(String(init.body)) : undefined;
    requests.push({ path, body });
    if (path.endsWith('/claim')) {
      epoch++; state = 'RUNNING';
      return Response.json({ run_id: runId, session_id: sessionId, lease_epoch: epoch, state,
        scope: { scope_kind: 'project', project_id: randomUUID(), snapshot_ids: [], material_revision_ids: [], alignment_overlay_revision: null },
        scope_digest: 'a'.repeat(64), allowed_tools: ['uploads.complete', 'jobs.get'], runtime_manifest: manifest,
        base_checkpoint: null, resume_checkpoint: cp, config_id: configId,
        user_message: `protocol-test:complete-upload:${uploadId}`, continuation_message: cp ? `Resume waiting jobs ${jobId}.` : null,
        waiting_jobs: cp ? [{ invocation_id: [...outputs.keys()][0], job_id: jobId, kind: 'UPLOAD_VALIDATE', state: jobState,
          report_tool: 'jobs.get', report_arguments: { job_id: jobId } }] : [], execution_token: 'execution-token-NEVER-MODEL' });
    }
    if (path.endsWith('/heartbeat')) return Response.json({ state });
    if (path.endsWith('/checkpoint') && !body) return Response.json({ checkpoint: cp, session_jsonl: archive });
    if (path.endsWith('/checkpoint')) {
      assert.deepEqual(body.runtime_manifest, manifest);
      if (archive) assert.ok(body.session_jsonl.startsWith(archive));
      archive = body.session_jsonl;
      const rows = archive!.trimEnd().split('\n').map(line => JSON.parse(line));
      cp = { checkpoint_id: randomUUID(), sha256: createHash('sha256').update(archive!).digest('hex'),
        byte_size: Buffer.byteLength(archive!), sdk_session_id: sessionId, leaf_id: rows.at(-1).id, runtime_manifest: manifest };
      return Response.json(cp);
    }
    if (path.endsWith('/invocations')) {
      const id = randomUUID(), accepted = body.tool_name === 'uploads.complete';
      const result = { result: { invocation_id: id, action_id: null, status: accepted ? 'accepted' : 'succeeded', job_id: jobId },
        data: { job_id: jobId, state: accepted ? 'QUEUED' : jobState } };
      outputs.set(id, result); return Response.json(result);
    }
    if (path.includes('/invocations/')) return Response.json(outputs.get(path.split('/').at(-1)!));
    if (path.endsWith('/events')) return Response.json({ sequence: requests.length });
    if (path.endsWith('/suspend')) { state = 'WAITING_JOB'; return Response.json({ state }); }
    if (path.endsWith('/settle')) { state = 'SUCCEEDED'; return Response.json({ state }); }
    if (path.endsWith('/review')) { state = 'WAITING_REVIEW'; return Response.json({ state }); }
    throw new Error('UNEXPECTED_REQUEST');
  }) as typeof fetch;
  return { runId, uploadId, jobId, fetcher, requests, finish: () => { jobState = 'SUCCEEDED'; },
    get archive() { return archive; }, get cp() { return cp; }, get state() { return state; } };
}

test('model identity shared vector and safe unconfigured/missing-key host', async () => {
  const config = modelConfiguration({ AGENT_MODEL_API: 'openai-completions', AGENT_MODEL_BASE_URL: ' https://model.example.test/v1/// ', AGENT_MODEL_ID: 'research-model-v1' });
  assert.equal(config.sha256, '756090785086b08af0069d1cd1165498755ea3895d54c4a0ffb9c8e61fc61b3d');
  assert.throws(() => modelConfiguration({ ...env('\u00a0openai-completions', 'https://model.example.test/v1') }), /MODEL_CONFIGURATION_INVALID/);
  for (const bad of ['http://example.test/v1', 'https://user:pw@host/v1', 'https://host/v1?key=x', 'https://host\\x', 'https://@host', 'http:127.0.0.1', 'http://127.1/v1', 'http://2130706433/v1', 'http://127.0.0.2/v1', 'https://host/\u2003']) {
    assert.throws(() => modelConfiguration({ ...env('openai-completions', bad), AGENT_MODEL_ALLOW_LOOPBACK_HTTP: 'false' }), /MODEL_CONFIGURATION_INVALID/);
  }
  const host = runtimeConfiguration({ ...env('openai-responses', 'http://127.0.0.1:1234/v1'), AGENT_RUNTIME_MODE: 'openai-compatible' });
  assert.equal(host.canClaim, false); assert.equal(host.reason, 'MODEL_KEY_MISSING');
  let calls = 0; const stop = new AbortController(); setTimeout(() => stop.abort(), 20);
  await runDaemon(host, { signal: stop.signal, pollMs: 1, fetcher: (async () => { calls++; throw new Error(); }) as typeof fetch });
  assert.equal(calls, 0);
});

for (const api of ['openai-completions', 'openai-responses']) {
  test(`${api}: actual SSE text, fragmented tool args, WAITING_JOB archive and resume share lifecycle`, async () => {
    let db: ReturnType<typeof ledger>;
    const server = await protocolServer((_body, response, index) => writeReply(response, api,
      index === 0 ? { tool: 'uploads_complete', args: { upload_id: db.uploadId } }
        : index === 2 ? { tool: 'jobs_get', args: { job_id: db.jobId } } : { text: '已读取真实业务结果。' }));
    const config = modelConfiguration(env(api, server.url)); db = ledger(config.manifest, config.configId);
    try {
      for (let segment = 0; segment < 2; segment++) {
        const client = new S1RunClient({ baseUrl: 'http://127.0.0.1', hostKey: 'host-key-NEVER-MODEL', fetcher: db.fetcher });
        const result = await executeSegment({ client, grant: await client.claim(db.runId), directory: folder(), provider: { config, apiKey: key } });
        assert.equal(result.final.state, segment ? 'SUCCEEDED' : 'WAITING_JOB');
        assert.deepEqual(result.tool_names, [segment ? 'jobs_get' : 'uploads_complete']);
        assert.equal(result.model_requests, 2); client.dispose(); db.finish();
      }
      assert.equal(server.bodies.length, 4);
      for (const body of server.bodies) {
        assert.equal(body.model, config.model); assert.equal(body.stream, true); assert.equal(body.tools.length, 2);
        assert.equal(body[api === 'openai-completions' ? 'max_tokens' : 'max_output_tokens'], 1024);
        if (api === 'openai-responses') assert.equal(body.store, false);
        const text = JSON.stringify(body);
        assert.ok(!text.includes(key)); assert.ok(!text.includes('NEVER-MODEL'));
      }
      assert.ok(!db.archive!.includes(key)); assert.ok(db.archive!.includes('已读取真实业务结果'));
      assert.equal(db.requests.filter(r => r.path.endsWith('/invocations') && r.body.tool_name === 'uploads.complete').length, 1);
      assert.equal(db.requests.filter(r => r.path.endsWith('/heartbeat')).length >= 6, true);
    } finally { await server.close(); }
  });

  test(`${api}: model loop stops at sixteen requests while retaining tool ledger`, async () => {
    let db: ReturnType<typeof ledger>;
    const server = await protocolServer((_body, response) => writeReply(response, api, { tool: 'jobs_get', args: { job_id: db.jobId } }));
    const config = modelConfiguration(env(api, server.url)); db = ledger(config.manifest, config.configId);
    const client = new S1RunClient({ baseUrl: 'http://127.0.0.1', hostKey: 'host', fetcher: db.fetcher });
    try {
      await assert.rejects(executeSegment({ client, grant: await client.claim(db.runId), directory: folder(), provider: { config, apiKey: key } }), /MODEL_REQUEST_FAILED/);
      assert.equal(server.bodies.length, 16);
      assert.equal(db.requests.filter(r => r.path.endsWith('/invocations')).length, 16);
      assert.equal(db.cp, null); assert.equal(db.requests.at(-1)!.body.reason, 'MODEL_REQUEST_FAILED');
    } finally { client.dispose(); await server.close(); }
  });

  for (const fault of ['401', '429', 'redirect', 'broken', 'interrupted', 'echo-key', 'cancel', 'timeout']) {
    test(`${api}: ${fault} remains safe, no auto retry or successful archive`, async () => {
      const controller = new AbortController();
      const server = await protocolServer((_body, response) => {
        if (fault === '401' || fault === '429') { response.writeHead(Number(fault), { 'Content-Type': 'application/json' }); response.end(JSON.stringify({ error: { message: key, metadata: key } })); }
        else if (fault === 'redirect') response.writeHead(307, { Location: 'http://127.0.0.1:1/forbidden' }).end();
        else if (fault === 'broken') { response.writeHead(200, { 'Content-Type': 'text/event-stream' }); response.end('data: {"invalid":\n\n'); }
        else if (fault === 'interrupted') {
          response.writeHead(200, { 'Content-Type': 'text/event-stream' }); response.flushHeaders();
          response.write('data: ' + JSON.stringify(api === 'openai-completions'
            ? { id: 'partial', choices: [{ index: 0, delta: { role: 'assistant', content: 'unfinished' }, finish_reason: null }] }
            : { type: 'response.created', response: { id: 'partial', status: 'in_progress', output: [] } }) + '\n\n');
          setTimeout(() => response.destroy(), 30);
        }
        else if (fault === 'echo-key') writeReply(response, api, { text: key });
        else if (fault === 'cancel') setTimeout(() => controller.abort(), 30);
        // timeout intentionally never returns a response; total request deadline closes it.
      });
      const config = modelConfiguration({ ...env(api, server.url), AGENT_MODEL_REQUEST_TIMEOUT_MS: '1000' });
      const db = ledger(config.manifest, config.configId); const dir = folder();
      const client = new S1RunClient({ baseUrl: 'http://127.0.0.1', hostKey: 'host', fetcher: db.fetcher });
      try {
        await assert.rejects(executeSegment({ client, grant: await client.claim(db.runId), directory: dir,
          signal: controller.signal, provider: { config, apiKey: key } }), /^Error: MODEL_/);
        assert.equal(server.bodies.length, 1); assert.equal(db.cp, null);
        const expected = fault === '401' ? 'MODEL_AUTH_FAILED' : fault === '429' ? 'MODEL_RATE_LIMITED' :
          fault === 'timeout' ? 'MODEL_TIMEOUT' : ['broken', 'interrupted', 'echo-key'].includes(fault) ? 'MODEL_RESPONSE_INVALID' : 'MODEL_REQUEST_FAILED';
        assert.equal(db.requests.at(-1)!.body.reason, expected);
        for (const run of readdirSync(dir)) for (const file of readdirSync(resolve(dir, run, 'sessions'), { recursive: true }).filter(x => String(x).endsWith('.jsonl'))) {
          assert.ok(!readFileSync(resolve(dir, run, 'sessions', String(file)), 'utf8').includes(key));
        }
      } finally { client.dispose(); await server.close(); }
    });
  }
}
