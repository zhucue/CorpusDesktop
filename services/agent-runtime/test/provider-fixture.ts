/** Synthetic loopback server for testing Pi's actual built-in HTTP/SSE adapters. */
import { createServer, type ServerResponse } from 'node:http';
import { randomUUID } from 'node:crypto';
import type { AddressInfo } from 'node:net';

export type Reply = { text: string } | { tool: string; args: Record<string, unknown> };
export function writeReply(response: ServerResponse, api: string, reply: Reply, model = 'research-model-v1') {
  response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
  const emit = (value: unknown) => response.write(`data: ${JSON.stringify(value)}\n\n`);
  const id = 'call_' + randomUUID().replaceAll('-', '');
  if (api === 'openai-completions') {
    const chunk = (delta: unknown, finish_reason: string | null = null) => emit({
      id: 'chatcmpl_test', object: 'chat.completion.chunk', created: 1, model,
      choices: [{ index: 0, delta, finish_reason }],
    });
    chunk({ role: 'assistant' });
    if ('text' in reply) {
      chunk({ content: reply.text.slice(0, 2) }); chunk({ content: reply.text.slice(2) }); chunk({}, 'stop');
    } else {
      const args = JSON.stringify(reply.args); const split = Math.floor(args.length / 2);
      chunk({ tool_calls: [{ index: 0, id, type: 'function', function: { name: reply.tool, arguments: args.slice(0, split) } }] });
      chunk({ tool_calls: [{ index: 0, function: { arguments: args.slice(split) } }] }); chunk({}, 'tool_calls');
    }
    response.end('data: [DONE]\n\n');
  } else {
    emit({ type: 'response.created', response: { id: 'resp_' + id, status: 'in_progress', output: [] } });
    let item;
    if ('text' in reply) {
      item = { type: 'message', id: 'msg_' + id, role: 'assistant', status: 'completed',
        content: [{ type: 'output_text', text: reply.text, annotations: [] }] };
      emit({ type: 'response.output_item.added', output_index: 0, item: { ...item, content: [] } });
      emit({ type: 'response.content_part.added', item_id: item.id, output_index: 0, content_index: 0,
        part: { type: 'output_text', text: '', annotations: [] } });
      emit({ type: 'response.output_text.delta', item_id: item.id, output_index: 0, content_index: 0, delta: reply.text.slice(0, 2) });
      emit({ type: 'response.output_text.delta', item_id: item.id, output_index: 0, content_index: 0, delta: reply.text.slice(2) });
    } else {
      const args = JSON.stringify(reply.args); const split = Math.floor(args.length / 2);
      item = { type: 'function_call', id: 'fc_' + id, call_id: id, name: reply.tool, arguments: args, status: 'completed' };
      emit({ type: 'response.output_item.added', output_index: 0, item: { ...item, arguments: '', status: 'in_progress' } });
      emit({ type: 'response.function_call_arguments.delta', output_index: 0, item_id: item.id, delta: args.slice(0, split) });
      emit({ type: 'response.function_call_arguments.delta', output_index: 0, item_id: item.id, delta: args.slice(split) });
      emit({ type: 'response.function_call_arguments.done', output_index: 0, item_id: item.id, arguments: args });
    }
    emit({ type: 'response.output_item.done', output_index: 0, item });
    emit({ type: 'response.completed', response: { id: 'resp_' + id, status: 'completed', output: [item],
      usage: { input_tokens: 8, output_tokens: 4, total_tokens: 12 } } });
    response.end();
  }
}

export async function protocolServer(handler: (body: any, response: ServerResponse, index: number) => void | Promise<void>, port = 0) {
  const bodies: any[] = [];
  const server = createServer(async (request, response) => {
    try {
      if (request.method !== 'POST') { response.writeHead(405).end(); return; }
      let text = '';
      for await (const chunk of request) {
        text += String(chunk);
        if (Buffer.byteLength(text) > 2 * 1024 * 1024) throw new Error('REQUEST_TOO_LARGE');
      }
      const body = JSON.parse(text); bodies.push(body);
      await handler(body, response, bodies.length - 1);
    } catch { if (!response.headersSent) response.writeHead(400); response.end(); }
  });
  await new Promise<void>(resolve => server.listen(port, '127.0.0.1', resolve));
  return { url: `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`, bodies,
    close: async () => { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); } };
}
