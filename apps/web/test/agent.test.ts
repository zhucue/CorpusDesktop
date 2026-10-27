import assert from 'node:assert/strict';
import test from 'node:test';
import { AgentReads, agentBusy, agentConfigChanged, mergeTurns, runtimeLabel, transcriptChanged } from '../src/agent-state.ts';
import { CorpusApiClient } from '../../../contracts/types/s1.ts';
import type { AgentRun, AgentRuntime, AgentSession, AgentTurn } from '../../../contracts/types/agent.ts';

test('configured real provider never silently continues fixture or different model history', () => {
  const runtime = { production_ready: false, mode: 'openai-compatible', fixture_enabled: false, can_submit: true,
    config_id: `openai-${'a'.repeat(48)}`, reason: null, runtime_manifest: {
      sdk_package: '@earendil-works/pi-coding-agent', sdk_version: '1.3.0', session_version: 3,
      tool_schema: 's3-outcomes-tools-v1', provider: 'corpus-openai-compatible', model: 'configured-model',
      host_policy: 'corpus-k09-openai-v1', resource_config: 'corpus-explicit-resources-v1',
      model_api: 'openai-completions', model_config_sha256: 'a'.repeat(64),
    } } as AgentRuntime;
  assert.equal(agentConfigChanged(runtime, { config_id: 'local-fixture-v1' } as AgentSession), true);
  assert.equal(agentConfigChanged(runtime, { config_id: `openai-${'b'.repeat(48)}` } as AgentSession), true);
  assert.equal(agentConfigChanged(runtime, { config_id: runtime.config_id } as AgentSession), false);
  assert.equal(agentConfigChanged(runtime, undefined), false);
  assert.equal(runtimeLabel(runtime), '已配置模型 configured-model');
  assert.equal(runtimeLabel({ ...runtime, can_submit: false, config_id: null, runtime_manifest: null,
    reason: 'MODEL_CONFIGURATION_INVALID' }), '模型配置有误');
  assert.equal(runtimeLabel({ production_ready: false, mode: 'unconfigured', fixture_enabled: false,
    can_submit: false, config_id: null, runtime_manifest: null, reason: 'MODEL_NOT_CONFIGURED' }), '尚未配置模型');
});

test('revocation or scope selection invalidates every earlier channel and old same-channel responses', () => {
  const reads = new AgentReads();
  const old = reads.begin('transcript'); const latest = reads.begin('transcript');
  const list = reads.begin('sessions');
  assert.equal(old(), false); assert.equal(latest(), true); assert.equal(list(), true);
  reads.invalidate(); assert.equal(latest(), false); assert.equal(list(), false);
  assert.equal(reads.begin('transcript')(), true);
});

test('history merge replaces the same run rather than duplicating messages', () => {
  const turn: AgentTurn = { run_id: 'a', user_message: 'Hello', assistant_messages: [], tools: [], state: 'QUEUED', created_at: '2026-10-17T00:00:00Z' };
  const complete = { ...turn, state: 'SUCCEEDED' as const, assistant_messages: [{ id: 'answer', text: 'Complete' }] };
  assert.deepEqual(mergeTurns([turn], [complete]), [complete]);
  assert.equal(agentBusy({ state: 'WAITING_REVIEW' } as AgentRun), true);
  assert.equal(agentBusy({ state: 'WAITING_JOB' } as AgentRun), true);
  assert.equal(agentBusy({ state: 'SUCCEEDED' } as AgentRun), false);
});

test('browser run binds real message and scope digest; only cookie/CSRF transport', async () => {
  const calls: { url: string; init?: RequestInit }[] = [];
  const api = new CorpusApiClient({ csrf: () => 'csrf', transport: (async (url, init) => {
    calls.push({ url: String(url), init }); return new Response(JSON.stringify({}), { status: 200 });
  }) as typeof fetch });
  const input = { request_key: 'key', message: 'Hello 😀', scope_digest: 'a'.repeat(64) };
  await api.createAgentRun('session', input);
  assert.equal(calls[0].url, '/api/v1/agent/sessions/session/runs');
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), input);
  assert.equal(calls[0].init?.credentials, 'include');
  assert.equal(new Headers(calls[0].init?.headers).get('X-CSRF-Token'), 'csrf');
  assert.equal(new Headers(calls[0].init?.headers).has('Authorization'), false);
  await api.agentMessages('session', 'prior'); await api.cancelAgentRun('run');
  assert.equal(calls[1].url, '/api/v1/agent/sessions/session/messages?limit=20&before=prior');
  assert.equal(calls[2].url, '/api/v1/agent/runs/run/cancel');
  assert.equal(calls[2].init?.body, '{}');
});

test('unchanged terminal runs do not repeatedly read transcript archives', () => {
  const complete = { run_id: 'run', state: 'SUCCEEDED', event_sequence: 8 } as AgentRun;
  assert.equal(transcriptChanged(complete, { ...complete }), false);
  assert.equal(transcriptChanged(complete, { ...complete, event_sequence: 9 }), true);
  assert.equal(transcriptChanged({ ...complete, state: 'RUNNING' }, complete), true);
  assert.equal(transcriptChanged(undefined, complete), true);
});

test('rejected submission is not automatically retried or converted into acceptance', async () => {
  let calls = 0;
  const api = new CorpusApiClient({ csrf: () => 'csrf', transport: (async () => {
    calls++; return new Response(JSON.stringify({ code: 'SESSION_BUSY', message: 'Busy' }), { status: 409 });
  }) as typeof fetch });
  await assert.rejects(api.createAgentRun('session', { request_key: 'same', message: 'keep draft', scope_digest: 'a'.repeat(64) }), { code: 'SESSION_BUSY' });
  assert.equal(calls, 1);
});
