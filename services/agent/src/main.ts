/** Agent service entry: node dist/main.js (or node src/main.ts in development). */
import { serve } from '@hono/node-server';
import { loadConfig } from './config.ts';
import { createModel } from './model.ts';
import { Runner } from './runner.ts';
import { createApp } from './server.ts';
import { PgStore } from './store.ts';

const config = loadConfig();
const store = new PgStore(config.databaseUrl);
await store.resetRunning();
const model = config.model ? await createModel(config.model) : null;
const app = createApp(config, store, new Runner(config, store, model));

const server = serve({ fetch: app.fetch, port: config.port, hostname: '0.0.0.0' }, info => {
  console.log(`agent listening on ${info.port}; model ${config.model ? `${config.model.api} ${config.model.id}` : 'MODEL_NOT_CONFIGURED'}`);
});

for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => {
    server.close();
    void store.close().finally(() => process.exit(0));
  });
}
