/** Explicit synthetic HTTP peer. Never used by the production daemon. */
import { createInterface } from 'node:readline';
import { protocolServer, writeReply } from './provider-fixture.ts';

const input = createInterface({ input: process.stdin });
const iterator = input[Symbol.asyncIterator]();
const first = await iterator.next();
const config = JSON.parse(first.value ?? '{}') as { api: string; port: number; uploadId: string; model: string };
if (!['openai-completions', 'openai-responses'].includes(config.api) || !Number.isInteger(config.port) || config.port < 1024 ||
    !/^[a-f0-9-]{36}$/.test(config.uploadId)) throw new Error('SYNTHETIC_CONFIG_INVALID');
const server = await protocolServer((body, response, index) => {
  const raw = JSON.stringify(body);
  if (index === 0 && !raw.includes(`protocol-test:complete-upload:${config.uploadId}`)) throw new Error('SYNTHETIC_INTENT_MISMATCH');
  if (index === 0) writeReply(response, config.api, { tool: 'uploads_complete', args: { upload_id: config.uploadId } }, config.model);
  else if (index === 2) {
    // The only resumed target is supplied by the server-bound control message.
    const matches = [...raw.matchAll(/job_id\\?"\s*:\s*\\?"([a-f0-9-]{36})/g)];
    const jobId = matches.at(-1)?.[1];
    if (!jobId) throw new Error('SYNTHETIC_REPORT_MISSING');
    writeReply(response, config.api, { tool: 'jobs_get', args: { job_id: jobId } }, config.model);
  } else if (index === 1 || index === 3) writeReply(response, config.api, { text: '本机协议测试段结束，业务状态由平台账本确认。' }, config.model);
  else throw new Error('SYNTHETIC_REQUEST_LIMIT');
}, config.port);
process.stdout.write(JSON.stringify({ ready: true, url: server.url }) + '\n');
await iterator.next();
await server.close();
process.stdout.write(JSON.stringify({ requests: server.bodies }) + '\n');
input.close();
