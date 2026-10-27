/** Read trusted configuration from stdin; never persist or print credentials. */
import { resolve, relative, isAbsolute } from 'node:path';
import { runFixedModelHost } from './s1-run-host.ts';

let input = '';
for await (const chunk of process.stdin) {
  input += String(chunk);
  if (input.length > 8192) throw new Error('CONFIG_TOO_LARGE');
}
const config = JSON.parse(input) as { baseUrl: string; hostKey: string; runId: string; directory: string };
const outputRoot = resolve('tmp');
const directory = resolve(config.directory);
const subpath = relative(outputRoot, directory);
if (subpath.startsWith('..') || isAbsolute(subpath)) throw new Error('OUTPUT_MUST_BE_IN_REPOSITORY_TMP');
try {
  const result = await runFixedModelHost({ ...config, directory });
  process.stdout.write(JSON.stringify(result) + '\n');
} catch (error) {
  // Error messages from network libraries can contain destinations. Keep output bounded.
  const code = error instanceof Error && /^[A-Z][A-Z0-9_]{2,80}$/.test(error.message) ? error.message : 'HOST_FAILED';
  process.stderr.write(JSON.stringify({ status: 'failed', code }) + '\n');
  process.exitCode = 1;
}
