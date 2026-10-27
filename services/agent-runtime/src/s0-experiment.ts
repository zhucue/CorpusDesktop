import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { createS0Host, PI_VERSION } from './s0-host.ts';

const root = fileURLToPath(new URL('../../../tmp/pi-s0/', import.meta.url));
mkdirSync(root, { recursive: true });
const directory = mkdtempSync(join(root, 'experiment-'));
const host = await createS0Host({ directory, retryOnce: true });
try {
  await host.session.prompt('Read the S0 fixture');
  const result = {
    experiment: 'K03 Pi SDK with deterministic provider', pi_version: PI_VERSION,
    node_version: process.version, platform: process.platform, executed_at: new Date().toISOString(),
    tools: host.session.getActiveToolNames(), model_requests: host.requests(),
    event_kinds: host.events.map(event => event.kind), event_file: host.eventPath,
    session_file: host.sessionManager.getSessionFile(),
    limitations: ['No real model or research tool', 'SQLite lease experiment is not production PostgreSQL/API acceptance', 'Business tool reconciliation and production checkpoint publication remain S1/S7 work'],
  };
  writeFileSync(join(directory, 'result.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
} finally { host.session.dispose(); }
