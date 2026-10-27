/** One real built-in protocol segment; credentials are only process memory/stdin. */
import { S1RunClient } from './s1-run-client.ts';
import { executeSegment } from './k09-executor.ts';
import { modelConfiguration } from './model-config.ts';
import { safeCode, workDirectory } from './k09-daemon.ts';

async function main() {
  let input = '';
  for await (const chunk of process.stdin) { input += String(chunk); if (Buffer.byteLength(input) > 8192) throw new Error('CONFIG_TOO_LARGE'); }
  const config = JSON.parse(input) as { baseUrl: string; hostKey: string; runId: string; directory: string };
  const model = modelConfiguration(process.env);
  const apiKey = process.env.AGENT_MODEL_API_KEY;
  if (!apiKey) throw new Error('MODEL_KEY_MISSING');
  const client = new S1RunClient(config);
  try {
    const result = await executeSegment({ client, grant: await client.claim(config.runId),
      directory: workDirectory(config.directory), provider: { config: model, apiKey } });
    process.stdout.write(JSON.stringify(result) + '\n');
  } finally { client.dispose(); }
}
main().catch(error => { process.stderr.write(JSON.stringify({ status: 'failed', code: safeCode(error) }) + '\n'); process.exitCode = 1; });
