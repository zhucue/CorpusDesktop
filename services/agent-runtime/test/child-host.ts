import { createS0Host } from '../src/s0-host.ts';
import { ExperimentalLeaseStore } from '../src/s0-lease.ts';
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';

const [mode, directory, owner] = process.argv.slice(2);
if (mode === 'lease') {
  const store = new ExperimentalLeaseStore(join(directory, 'leases.sqlite'));
  process.send?.({ ready: true });
  process.once('message', () => {
    const epoch = store.acquire('same-session', owner, 1000, 1000);
    process.send?.({ epoch, owner });
    store.close();
    process.disconnect();
  });
} else if (mode === 'crash' || mode === 'crash-before-persist') {
  const host = await createS0Host({ directory });
  // Abrupt termination immediately after the actual SDK persisted tool-result event.
  host.session.subscribe(event => {
    if ((mode === 'crash-before-persist' && event.type === 'message_end' && event.message.role === 'toolResult') || (mode === 'crash' && event.type === 'turn_end')) {
      writeFileSync(join(directory, 'checkpoint.json'), JSON.stringify({ sessionFile: host.sessionManager.getSessionFile() }), { flush: true });
      process.exit(73);
    }
  });
  await host.session.prompt('Read the fixture');
  throw new Error('Expected crash was not reached');
} else throw new Error('Unknown child mode');
