/** Trusted stdin-only scenario runner. One OS process executes one leased segment. */
import { randomUUID } from 'node:crypto';
import { S1RunClient } from './s1-run-client.ts';
import { executeFixtureSegment, type FixtureScenario } from './k09-executor.ts';
import { safeCode, workDirectory } from './k09-daemon.ts';

async function main() {
  let input = '';
  for await (const chunk of process.stdin) { input += String(chunk); if (Buffer.byteLength(input) > 8192) throw new Error('CONFIG_TOO_LARGE'); }
  const config = JSON.parse(input) as { baseUrl: string; hostKey: string; runId?: string; directory: string;
    scenario?: FixtureScenario; fixtureEnabled: boolean; allowInternalApi?: boolean };
  if (config.fixtureEnabled !== true) throw new Error('FIXTURE_NOT_ENABLED');
  const client = new S1RunClient(config);
  const stop = new AbortController();
  const terminate = () => stop.abort();
  process.once('SIGINT', terminate); process.once('SIGTERM', terminate);
  try {
    const grant = config.runId ? await client.claim(config.runId) : await client.claimNext(randomUUID());
    if (!grant) { process.stdout.write(JSON.stringify({ claimed: false }) + '\n'); return; }
    const result = await executeFixtureSegment({ client, grant, scenario: config.scenario,
      directory: workDirectory(config.directory), signal: stop.signal });
    process.stdout.write(JSON.stringify({ claimed: true, ...result }) + '\n');
  } finally {
    client.dispose(); process.removeListener('SIGINT', terminate); process.removeListener('SIGTERM', terminate);
  }
}
main().catch(error => { process.stderr.write(JSON.stringify({ status: 'failed', code: safeCode(error) }) + '\n'); process.exitCode = 1; });
