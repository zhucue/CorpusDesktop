/** A bounded single-consumer HTTP host; no direct DB, object-store or model keys. */
import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';
import { mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { resolve, relative, isAbsolute } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { S1RunClient } from './s1-run-client.ts';
import { executeSegment } from './k09-executor.ts';
import { modelConfiguration, type ModelConfiguration } from './model-config.ts';

export function safeCode(error: unknown) {
  return error instanceof Error && /^[A-Z][A-Z0-9_]{2,80}$/.test(error.message) ? error.message : 'HOST_EXECUTION_FAILED';
}

export function workDirectory(value: string) {
  const repository = fileURLToPath(new URL('../../../', import.meta.url));
  const root = resolve(repository, 'tmp'); const directory = resolve(repository, value); const subpath = relative(root, directory);
  if (!subpath || subpath.startsWith('..') || isAbsolute(subpath)) throw new Error('OUTPUT_MUST_BE_IN_REPOSITORY_TMP');
  return directory;
}

export function runtimeConfiguration(env: NodeJS.ProcessEnv) {
  const fixture = env.AGENT_RUNTIME_MODE === 'fixture' && env.AGENT_ENABLE_LOCAL_FIXTURE === 'true';
  const mode = fixture ? 'fixture' : env.AGENT_RUNTIME_MODE === 'openai-compatible' ? 'openai-compatible' : 'unconfigured';
  const baseUrl = env.AGENT_API_ORIGIN ?? 'http://api:8000';
  const hostKey = env.AGENT_HOST_KEY ?? '';
  if (fixture && hostKey.length < 32) throw new Error('HOST_CONFIGURATION_MISSING');
  let model: ModelConfiguration | undefined;
  let reason: string | null = fixture ? 'LOCAL_FIXTURE_ONLY' : 'MODEL_NOT_CONFIGURED';
  const apiKey = env.AGENT_MODEL_API_KEY ?? '';
  if (mode === 'openai-compatible') {
    try {
      model = modelConfiguration(env);
      reason = !apiKey.trim() ? 'MODEL_KEY_MISSING' : hostKey.length < 32 ? 'HOST_CONFIGURATION_MISSING' : null;
    } catch { reason = 'MODEL_CONFIGURATION_INVALID'; }
  }
  const canClaim = fixture || (mode === 'openai-compatible' && model !== undefined && reason === null);
  return { mode, baseUrl, hostKey, allowInternalApi: baseUrl === 'http://api:8000',
    reason, canClaim, configId: model?.configId ?? 'local-fixture-v1', provider: model ? { config: model, apiKey } : undefined,
    directory: workDirectory(env.AGENT_WORK_DIR ?? 'tmp/agent-host'),
    port: Number(env.AGENT_HEALTH_PORT ?? 8081) };
}

export async function runDaemon(config: ReturnType<typeof runtimeConfiguration>, options: {
  signal: AbortSignal; fetcher?: typeof fetch; pollMs?: number; maxClaims?: number;
  onResult?: (result: unknown) => void; onError?: (code: string) => void;
  onPoll?: () => void;
}) {
  const hostId = randomUUID(); let claimed = 0;
  const pollMs = options.pollMs ?? 2000;
  if (pollMs < 1 || pollMs > 10000) throw new Error('POLL_INTERVAL_INVALID');
  while (!options.signal.aborted) {
    if (config.canClaim) {
      const client = new S1RunClient({ ...config, fetcher: options.fetcher });
      let attemptDirectory: string | undefined;
      try {
        const grant = await client.claimNext(hostId, config.configId);
        options.onPoll?.();
        if (grant) {
          claimed++;
          mkdirSync(config.directory, { recursive: true });
          attemptDirectory = mkdtempSync(resolve(config.directory, 'attempt-'));
          const result = await executeSegment({ client, grant, provider: config.provider,
            directory: attemptDirectory, signal: options.signal, onActivity: options.onPoll });
          options.onResult?.(result);
        }
      } catch (error) { options.onError?.(safeCode(error)); }
      finally {
        client.dispose();
        if (attemptDirectory) {
          const within = relative(resolve(config.directory), resolve(attemptDirectory));
          if (!within || within.startsWith('..') || isAbsolute(within)) throw new Error('WORK_DIRECTORY_INVALID');
          // Durable checkpoints belong to the API. This attempt-local SDK copy
          // must not accumulate private transcripts across daemon runs.
          rmSync(attemptDirectory, { recursive: true, force: true });
        }
      }
      if (options.maxClaims !== undefined && claimed >= options.maxClaims) break;
    }
    await delay(pollMs, undefined, { signal: options.signal }).catch(() => {});
  }
  return { claimed };
}

export async function main() {
  const config = runtimeConfiguration(process.env);
  if (!Number.isInteger(config.port) || config.port < 1024 || config.port > 65535) throw new Error('HEALTH_PORT_INVALID');
  const stop = new AbortController();
  const terminate = () => stop.abort();
  process.once('SIGTERM', terminate); process.once('SIGINT', terminate);
  let lastPoll = 0;
  const server = createServer((request, response) => {
    const live = !stop.signal.aborted;
    const ready = live && config.canClaim && Date.now() - lastPoll < 45000;
    response.setHeader('Content-Type', 'application/json');
    if (request.url !== '/health/live' && request.url !== '/health/ready') { response.writeHead(404).end(); return; }
    response.statusCode = request.url === '/health/live' ? (live ? 200 : 503) : ready ? 200 : 503;
    response.end(JSON.stringify({ live, ready, mode: config.mode, production_ready: false,
      fixture_enabled: config.mode === 'fixture', reason: config.reason }));
  });
  await new Promise<void>(accept => server.listen(config.port, '0.0.0.0', accept));
  try {
    await runDaemon(config, { signal: stop.signal, onPoll: () => { lastPoll = Date.now(); },
      onResult: () => { process.stdout.write(JSON.stringify({ event: 'host.segment_finished' }) + '\n'); },
      onError: code => { process.stderr.write(JSON.stringify({ event: 'host.segment_error', code }) + '\n'); } });
  } finally {
    server.close(); process.removeListener('SIGTERM', terminate); process.removeListener('SIGINT', terminate);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error => { process.stderr.write(JSON.stringify({ code: safeCode(error) }) + '\n'); process.exitCode = 1; });
}
