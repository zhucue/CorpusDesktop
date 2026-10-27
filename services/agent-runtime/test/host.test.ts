import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, copyFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { fork, spawnSync } from 'node:child_process';
import { once } from 'node:events';
import { createHash } from 'node:crypto';
import { createS0Host, FIXTURE_TOOL, recoveryReadiness } from '../src/s0-host.ts';
import { ExperimentalLeaseStore } from '../src/s0-lease.ts';

const root = fileURLToPath(new URL('../../../tmp/pi-s0/', import.meta.url));
mkdirSync(root, { recursive: true });
const temporary = (name: string) => mkdtempSync(join(root, name));

test('real SDK loads only the fixture and persists final events and SessionManager context', async () => {
  const directory = temporary('explicit-');
  mkdirSync(join(directory, '.pi'), { recursive: true });
  writeFileSync(join(directory, 'AGENTS.md'), 'UNAPPROVED_CONTEXT_SENTINEL');
  writeFileSync(join(directory, '.pi', 'settings.json'), JSON.stringify({ defaultTools: ['bash', 'read', 'edit', 'write'] }));
  const host = await createS0Host({ directory, onModelRequest: context => {
    assert.ok(!JSON.stringify(context).includes('UNAPPROVED_CONTEXT_SENTINEL'));
  } });
  try {
    assert.deepEqual(host.session.getActiveToolNames(), [FIXTURE_TOOL]);
    await host.session.prompt('Read the fixture');
    assert.equal(host.requests(), 2);
    assert.equal(host.events.at(-1)?.kind, 'agent_settled');
    assert.ok(host.events.some(event => event.kind === 'tool_execution_end'));
    const persisted = readFileSync(host.eventPath, 'utf8').trim().split('\n').map(line => JSON.parse(line));
    assert.deepEqual(persisted.map(event => event.sequence), persisted.map((_, i) => i + 1));
    assert.deepEqual(persisted.map(event => event.kind), host.events.map(event => event.kind));
    const source = host.sessionManager.getSessionFile()!;
    const archive = join(directory, 'immutable-context.jsonl');
    copyFileSync(source, archive);
    const digest = createHash('sha256').update(readFileSync(archive)).digest('hex');
    host.session.dispose();
    const previousLength = host.events.length;
    const restored = await createS0Host({ directory, sessionFile: archive });
    try {
      assert.ok(restored.session.messages.some(message => message.role === 'toolResult'));
      assert.equal(restored.session.getLastAssistantText(), 'S0 fixture returned: s0-fixture-evidence-1.');
      await restored.session.prompt('Continue from the existing result');
      assert.ok(restored.events.length > previousLength);
      assert.equal(restored.events[previousLength].sequence, previousLength + 1);
      assert.equal(createHash('sha256').update(readFileSync(archive)).digest('hex'), digest);
    } finally { restored.session.dispose(); }
  } finally { host.session.dispose(); }
});

test('agent_end can precede automatic retry; settle occurs only after the retry completes', async () => {
  const host = await createS0Host({ directory: temporary('retry-'), retryOnce: true });
  try {
    await host.session.prompt('Read the fixture');
    const kinds = host.events.map(event => event.kind);
    assert.equal(host.requests(), 3);
    assert.equal(kinds.filter(kind => kind === 'agent_end').length, 2);
    assert.equal(kinds.filter(kind => kind === 'agent_settled').length, 1);
    assert.ok(kinds.indexOf('agent_end') < kinds.indexOf('auto_retry_start'));
    assert.equal(kinds.at(-1), 'agent_settled');
  } finally { host.session.dispose(); }
});

test('crash after persisted read tool result restores through SessionManager without replaying the tool', async () => {
  const directory = temporary('crash-');
  const child = spawnSync(process.execPath, [fileURLToPath(new URL('./child-host.ts', import.meta.url)), 'crash', directory], { encoding: 'utf8', timeout: 30000 });
  assert.equal(child.status, 73, child.stderr);
  const checkpoint = JSON.parse(readFileSync(join(directory, 'checkpoint.json'), 'utf8'));
  let executed = 0;
  const host = await createS0Host({ directory: temporary('recovered-'), sessionFile: resolve(checkpoint.sessionFile), onTool: () => executed++ });
  try {
    assert.ok(host.session.messages.some(message => message.role === 'toolResult'));
    assert.equal(recoveryReadiness(host.session.messages), 'READY');
    await host.session.prompt('Continue from the existing fixture result');
    assert.equal(executed, 0);
    assert.equal(host.requests(), 1);
    assert.equal(host.events.at(-1)?.kind, 'agent_settled');
  } finally { host.session.dispose(); }
});

test('crash in message_end before SDK persistence is identified as WAITING_REVIEW', async () => {
  const directory = temporary('missing-result-');
  const child = spawnSync(process.execPath, [fileURLToPath(new URL('./child-host.ts', import.meta.url)), 'crash-before-persist', directory], { encoding: 'utf8', timeout: 30000 });
  assert.equal(child.status, 73, child.stderr);
  const checkpoint = JSON.parse(readFileSync(join(directory, 'checkpoint.json'), 'utf8'));
  const host = await createS0Host({ directory: temporary('review-'), sessionFile: checkpoint.sessionFile });
  try {
    assert.equal(recoveryReadiness(host.session.messages), 'WAITING_REVIEW');
    assert.equal(host.requests(), 0);
  } finally { host.session.dispose(); }
});

test('two OS processes compete for one durable lease; expired owner cannot publish after takeover', async () => {
  const directory = temporary('lease-');
  const database = join(directory, 'leases.sqlite');
  new ExperimentalLeaseStore(database).close();
  const children = ['one', 'two'].map(owner => fork(fileURLToPath(new URL('./child-host.ts', import.meta.url)), ['lease', directory, owner], { stdio: ['ignore', 'pipe', 'pipe', 'ipc'] }));
  try {
    await Promise.all(children.map(child => once(child, 'message')));
    const responses = children.map(child => once(child, 'message'));
    children.forEach(child => child.send('compete'));
    const results = (await Promise.all(responses)).map(([message]) => message as { epoch: number | null; owner: string });
    assert.equal(results.filter(result => result.epoch === 1).length, 1);
    assert.equal(results.filter(result => result.epoch === null).length, 1);
    const winner = results.find(result => result.epoch === 1)!;
    const store = new ExperimentalLeaseStore(database);
    try {
      assert.equal(store.publish('same-session', winner.owner, 1, 1500, 'archive-first'), true);
      assert.equal(store.acquire('same-session', 'replacement', 2001, 1000), 2);
      assert.equal(store.publish('same-session', winner.owner, 1, 2002, 'stale-archive'), false);
      assert.equal(store.publish('same-session', 'replacement', 2, 2002, 'archive-second'), true);
      assert.equal(store.get('same-session')?.archive, 'archive-second');
    } finally { store.close(); }
  } finally { children.forEach(child => child.kill()); }
});
