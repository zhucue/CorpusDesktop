import assert from 'node:assert/strict';
import { rm } from 'node:fs/promises';
import { after, test } from 'node:test';
import { createParser } from '@openuidev/lang-core';
import { COMPONENTS, componentCatalog, library } from '../src/components.ts';
import type { Config } from '../src/config.ts';
import { createModel } from '../src/model.ts';
import { systemPrompt } from '../src/prompt.ts';
import { Runner } from '../src/runner.ts';
import { createApp } from '../src/server.ts';
import {
  AGENT_TOKEN, CORPUS, COOKIE, DEP_LAYER, KB_SEARCH, LONG_CHUNK, MemoryStore, ORIGIN, PROJECT, USER, fakeApi, fakeModel, parseSse, testConfig, type Reply,
} from './fixtures.ts';

const closers: (() => Promise<void>)[] = [];
after(async () => { for (const close of closers) await close(); });

async function setup(replies: Reply[], options: { api?: Parameters<typeof fakeApi>[0]; config?: Partial<Config>; modelApi?: 'openai-completions' | 'openai-responses'; noModel?: boolean; modelTimeoutMs?: number } = {}) {
  const api = await fakeApi(options.api);
  const model = await fakeModel(options.modelApi ?? 'openai-completions', replies);
  closers.push(api.close, model.close);
  const config = testConfig({ apiUrl: api.url, modelUrl: options.noModel ? undefined : model.url, modelApi: options.modelApi, ...options.config });
  closers.push(() => rm(config.dataDir, { recursive: true, force: true }));
  if (options.modelTimeoutMs && config.model) config.model.timeoutMs = options.modelTimeoutMs;
  const store = new MemoryStore();
  const runner = new Runner(config, store, config.model ? await createModel(config.model) : null);
  const app = createApp(config, store, runner);
  const call = (method: string, path: string, body?: unknown) => app.request(path, {
    method, headers: { cookie: COOKIE, origin: ORIGIN, 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const createSession = async () => {
    const response = await call('POST', '/agent/sessions', { project_id: PROJECT, scope: { corpus_id: CORPUS } });
    assert.equal(response.status, 201);
    return (await response.json()) as { id: string; state: string };
  };
  return { api, model, store, app, call, createSession };
}

const KWIC = [
  'root = KwicTable("search-1", "翻译", "UD 中文", counts, rows, 2)',
  'counts = {hits: 2, sentences: 2, documents: 2}',
  'rows = [{hit_id: "doc1:10-12", left: "他们决定", match: "翻译", right: "这本书。", source: "新闻 01"}, {hit_id: "doc2:4-6", left: "请", match: "翻译", right: "成英文。", source: "小说 07", aligned: "Please translate it."}]',
].join('\n');
const COLLOCATIONS = 'root = CollocationTable("stat-1", "翻译", 5, "logdice", [{collocate: "w0", freq: 60, score: 10}, {collocate: "w1", freq: 59, score: 9.9}])';
const ANSWER = `“翻译”在 UD 中文中有 2 条命中（hit_id doc1:10-12、doc2:4-6）。\n\n\`\`\`openui-lang\n${KWIC}\n\`\`\`\n\n搭配结果见 stat-1：\n\`\`\`openui-lang\n${COLLOCATIONS}\n\`\`\`\n`;

test('full run: search and collocation tools, prose and OpenUI streamed, message persisted', async () => {
  const { api, model, store, call, createSession } = await setup([
    { tool: 'corpus_search', args: { query: '翻译/v' } },
    { tool: 'stats_collocations', args: { node: '翻译/v', measures: ['logdice'] } },
    { text: ANSWER },
  ]);
  const session = await createSession();
  const response = await call('POST', `/agent/sessions/${session.id}/messages`, { content: '找 翻译 作动词的搭配' });
  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-type') ?? '', /text\/event-stream/);
  const events = parseSse(await response.text());
  const names = events.map(e => e.event);

  assert.equal(names[0], 'start');
  assert.equal(names.at(-1), 'done');
  assert.deepEqual(names.filter(n => n === 'tool_call' || n === 'tool_result'), ['tool_call', 'tool_result', 'tool_call', 'tool_result']);
  const results = events.filter(e => e.event === 'tool_result').map(e => e.data);
  assert.deepEqual(results.map(r => [r.name, r.state]), [['corpus.search', 'succeeded'], ['stats.collocations', 'succeeded']]);
  assert.deepEqual(results[0].result_ref, { kind: 'search', id: 'search-1' });
  assert.deepEqual(results[1].result_ref, { kind: 'stat', id: 'stat-1' });
  assert.equal(events.find(e => e.event === 'tool_call')!.data.state, 'running');

  // text deltas carry only prose; ui deltas carry only OpenUI Lang (no fences)
  const text = events.filter(e => e.event === 'text').map(e => e.data.delta).join('');
  const ui = events.filter(e => e.event === 'ui').map(e => e.data.delta).join('');
  assert.ok(!text.includes('```') && !text.includes('root ='));
  assert.ok(text.includes('hit_id doc1:10-12'));
  assert.ok(!ui.includes('```'));
  assert.ok(ui.startsWith('root = KwicTable('));

  const message = events.at(-1)!.data.message;
  assert.equal(message.id, events[0].data.message_id);
  assert.deepEqual(message.parts.map((p: any) => p.type), ['text', 'ui', 'text', 'ui']);
  assert.equal(message.parts[1].lang.trim(), KWIC);
  assert.equal(message.parts[3].lang.trim(), COLLOCATIONS);
  assert.equal(message.tool_calls.length, 2);
  assert.ok(message.duration_ms >= 0);
  // every ui part index in the stream points at the matching persisted part
  for (const e of events.filter(e => e.event === 'ui')) assert.equal(message.parts[e.data.part].type, 'ui');

  // the ui parts are valid OpenUI Lang for the registered library
  const parser = createParser(library.toJSONSchema());
  const kwic = parser.parse(message.parts[1].lang);
  assert.equal((kwic.root as any)?.typeName, 'KwicTable');
  assert.equal((kwic.root as any)?.props.rows.length, 2);
  assert.equal((parser.parse(message.parts[3].lang).root as any)?.typeName, 'CollocationTable');

  // tools used the agent token, with the session scope; browser cookie only for identity
  const search = api.requests.find(r => r.path === '/search')!;
  assert.equal(search.headers.authorization, `Bearer ${AGENT_TOKEN}`);
  assert.equal(search.headers.cookie, undefined);
  assert.deepEqual(search.body.scope, { corpus_id: CORPUS });
  const collocations = api.requests.find(r => r.path === '/stats/collocations')!;
  assert.deepEqual(collocations.body.measures, ['logdice']);
  assert.ok(api.requests.filter(r => r.path.startsWith('/jobs/')).length >= 2);
  const tokenRequest = api.requests.find(r => r.path === '/auth/agent-token')!;
  assert.equal(tokenRequest.headers.cookie, COOKIE);
  assert.deepEqual(tokenRequest.body, { project_id: PROJECT });

  // compact tool results reach the model; system prompt carries the catalog and scope
  const toolResult = JSON.parse(model.requests[2].body.messages.filter((m: any) => m.role === 'tool').at(-1).content);
  assert.equal(toolResult.rows.length, 50);
  assert.equal(toolResult.row_count, 60);
  const system = model.requests[0].body.messages[0].content;
  assert.match(system, /KwicTable\(search_id: string/);
  assert.match(system, /UD 中文/);
  const toolNames = model.requests[0].body.tools.map((t: any) => t.function.name);
  assert.equal(toolNames.length, 32);
  assert.ok(!toolNames.some((n: string) => ['read', 'bash', 'edit', 'write'].includes(n)));
  assert.ok(toolNames.includes('stats_collocations') && toolNames.includes('jobs_cancel') && toolNames.includes('kb_search'));

  // persisted: user + assistant, session idle, title from first message, Pi session file present
  const detail = await (await call('GET', `/agent/sessions/${session.id}`)).json() as any;
  assert.equal(detail.state, 'idle');
  assert.equal(detail.message_count, 2);
  assert.equal(detail.title, '找 翻译 作动词的搭配');
  assert.deepEqual(detail.messages.map((m: any) => m.role), ['user', 'assistant']);
  assert.deepEqual(detail.messages[1].parts, message.parts);
  const stored = [...store.sessions.values()][0];
  assert.ok(stored.pi_session_path.endsWith(session.id));
});

test('second message in a session reuses the Pi session history', async () => {
  const { model, call, createSession } = await setup([{ text: '第一次回答。' }, { text: '第二次回答。' }]);
  const session = await createSession();
  parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '你好' })).text());
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '继续' })).text());
  assert.equal(events.at(-1)!.event, 'done');
  const contents = model.requests[1].body.messages.map((m: any) => typeof m.content === 'string' ? m.content : JSON.stringify(m.content));
  assert.ok(contents.some((c: string) => c.includes('第一次回答')));
});

test('reasoning deltas become thinking events and a thinking part', async () => {
  const { call, createSession } = await setup([{ thinking: '先确认范围。', text: '范围是 UD 中文。' }]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '范围？' })).text());
  const thinking = events.filter(e => e.event === 'thinking');
  assert.equal(thinking.map(e => e.data.delta).join(''), '先确认范围。');
  assert.ok(thinking.every(e => e.data.part === 0));
  const message = events.at(-1)!.data.message;
  assert.deepEqual(message.parts, [{ type: 'thinking', text: '先确认范围。' }, { type: 'text', text: '范围是 UD 中文。' }]);
  assert.equal(message.content, '范围是 UD 中文。');
});

test('openai-responses provider streams text', async () => {
  const { call, createSession } = await setup([{ text: '结果如下。\n```openui-lang\nroot = Callout("info", "范围内没有命中")\n```' }], { modelApi: 'openai-responses' });
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '查一下' })).text());
  const message = events.at(-1)!.data.message;
  assert.deepEqual(message.parts.map((p: any) => p.type), ['text', 'ui']);
  assert.equal(message.parts[1].lang.trim(), 'root = Callout("info", "范围内没有命中")');
});

test('SESSION_BUSY while running; cancel aborts the run and the waiting tool', async () => {
  const { api, call, createSession } = await setup(
    [{ tool: 'stats_frequency', args: {} }],
    { api: { statJobState: 'running' }, config: { jobWaitMs: 60000 } },
  );
  const session = await createSession();
  const first = await call('POST', `/agent/sessions/${session.id}/messages`, { content: '统计词频' });
  const body = first.text();
  await api.firstJobPoll;

  const busy = await call('POST', `/agent/sessions/${session.id}/messages`, { content: '再来' });
  assert.equal(busy.status, 409);
  assert.equal(((await busy.json()) as any).error.code, 'SESSION_BUSY');
  const running = await (await call('GET', `/agent/sessions/${session.id}`)).json() as any;
  assert.equal(running.state, 'running');
  assert.equal(running.messages[1].tool_calls[0].state, 'running');

  const cancel = await call('POST', `/agent/sessions/${session.id}/cancel`);
  assert.equal(cancel.status, 204);
  const events = parseSse(await body);
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.equal(result.name, 'stats.frequency');
  assert.equal(result.state, 'cancelled');
  assert.equal(events.at(-1)!.event, 'done');
  assert.equal(events.at(-1)!.data.message.tool_calls[0].state, 'cancelled');

  const idle = await (await call('GET', `/agent/sessions/${session.id}`)).json() as any;
  assert.equal(idle.state, 'idle');
});

test('stats tool returns job_id when the job outlives the wait', async () => {
  const { model, call, createSession } = await setup(
    [{ tool: 'stats_frequency', args: { unit: 'lemma' } }, { text: '任务仍在运行。' }],
    { api: { statJobState: 'running' }, config: { jobWaitMs: 50 } },
  );
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '统计' })).text());
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.equal(result.state, 'succeeded');
  assert.deepEqual(result.result_ref, { kind: 'job', id: 'job-frequency' });
  const toolMessage = JSON.parse(model.requests[1].body.messages.find((m: any) => m.role === 'tool').content);
  assert.equal(toolMessage.job_id, 'job-frequency');
  assert.equal(toolMessage.state, 'running');
});

test('api errors become failed tool calls with the api code', async () => {
  const { call, createSession } = await setup([{ tool: 'corpora_get', args: { corpus_id: 'missing' } }, { text: '没有找到该语料库。' }]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '看看语料' })).text());
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.equal(result.name, 'corpora.get');
  assert.equal(result.state, 'failed');
  assert.match(result.result_summary, /NOT_FOUND/);
  assert.equal(events.at(-1)!.event, 'done');
});

test('MODEL_NOT_CONFIGURED: health reports it and messages return 503', async () => {
  const { app, call, createSession } = await setup([], { noModel: true });
  assert.deepEqual(await (await app.request('/agent/health')).json(), { ok: false, reason: 'MODEL_NOT_CONFIGURED' });
  const session = await createSession();
  const response = await call('POST', `/agent/sessions/${session.id}/messages`, { content: '你好' });
  assert.equal(response.status, 503);
  assert.equal(((await response.json()) as any).error.code, 'MODEL_NOT_CONFIGURED');
});

test('provider errors map to MODEL_* codes', async () => {
  const cases: [Reply, string][] = [[{ status: 401 }, 'MODEL_AUTH_FAILED'], [{ status: 429 }, 'MODEL_RATE_LIMITED'], [{ status: 500 }, 'MODEL_REQUEST_FAILED']];
  for (const [reply, code] of cases) {
    const { app, call, createSession } = await setup([reply]);
    assert.equal(((await (await app.request('/agent/health')).json()) as any).ok, true);
    const session = await createSession();
    const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '你好' })).text());
    assert.deepEqual(events.map(e => e.event), ['start', 'error']);
    assert.equal(events[1].data.code, code);
  }
});

test('model timeout maps to MODEL_TIMEOUT', async () => {
  const { call, createSession } = await setup([{ hang: true }], { modelTimeoutMs: 300 });
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '你好' })).text());
  assert.equal(events.at(-1)!.event, 'error');
  assert.equal(events.at(-1)!.data.code, 'MODEL_TIMEOUT');
});

test('identity, ownership and origin checks', async () => {
  const { app, call, createSession } = await setup([]);
  const anonymous = await app.request('/agent/sessions?project_id=' + PROJECT);
  assert.equal(anonymous.status, 401);
  const foreign = await app.request('/agent/sessions', {
    method: 'POST', headers: { cookie: COOKIE, origin: 'http://evil.example', 'content-type': 'application/json' },
    body: JSON.stringify({ project_id: PROJECT, scope: null }),
  });
  assert.equal(foreign.status, 403);
  const otherProject = await call('POST', '/agent/sessions', { project_id: '99999999-9999-4999-8999-999999999999', scope: null });
  assert.equal(otherProject.status, 404);
  const badScope = await call('POST', '/agent/sessions', { project_id: PROJECT, scope: { corpus_id: 'x' } });
  assert.equal(badScope.status, 422);

  const session = await createSession();
  const list = await (await call('GET', `/agent/sessions?project_id=${PROJECT}`)).json() as any;
  assert.equal(list.total, 1);
  const patched = await (await call('PATCH', `/agent/sessions/${session.id}`, { title: '搭配研究', scope: null })).json() as any;
  assert.equal(patched.title, '搭配研究');
  assert.equal(patched.scope, null);
  assert.equal((await call('DELETE', `/agent/sessions/${session.id}`)).status, 204);
  assert.equal((await call('GET', `/agent/sessions/${session.id}`)).status, 404);
});

// ---------------------------------------------------------------- P3 annotation

const TREE = [
  'root = DependencyTree("doc1", 3, tokens, arcs, [3])',
  'tokens = [{index: 1, form: "他们", pos: "r"}, {index: 2, form: "翻译", pos: "v"}, {index: 3, form: "这本书", pos: "n"}, {index: 4, form: "。", pos: "x"}]',
  'arcs = [{head: 2, dep: 1, label: "nsubj"}, {head: 0, dep: 2, label: "root"}, {head: 2, dep: 3, label: "obj"}, {head: 2, dep: 4, label: "punct"}]',
].join('\n');

test('annot.sentence then a DependencyTree block', async () => {
  const { api, model, call, createSession } = await setup([
    { tool: 'annot_sentence', args: { layer_id: DEP_LAYER, document_id: 'doc1', sentence_index: 3 } },
    { text: `doc1 第 4 句的依存结构：\n\`\`\`openui-lang\n${TREE}\n\`\`\`\n` },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '看第 4 句的依存树' })).text());
  assert.equal(events.at(-1)!.event, 'done');
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([result.name, result.state], ['annot.sentence', 'succeeded']);
  assert.deepEqual(result.result_ref, { kind: 'layer', id: DEP_LAYER });
  const sentence = api.requests.find(r => r.path === `/layers/${DEP_LAYER}/sentences/doc1/3`)!;
  assert.equal(sentence.headers.authorization, `Bearer ${AGENT_TOKEN}`);

  // compact tool result: system values, the layer's annotation, and effective values (modified wins, suggested does not)
  const toolResult = JSON.parse(model.requests[1].body.messages.find((m: any) => m.role === 'tool').content);
  assert.equal(toolResult.layer_kind, 'dep');
  assert.deepEqual(toolResult.tokens[2], {
    index: 3, form: '这本书', system: { pos: 'n', head: 2, deprel: 'nmod' },
    annotation: { label: 'obj', head: 2, model_label: 'nmod', model_head: 2, status: 'modified', source: `human:${USER.id}` },
    effective: { pos: 'n', head: 2, deprel: 'obj' },
  });
  assert.equal(toolResult.tokens[0].annotation, null);
  assert.equal(toolResult.tokens[3].effective.deprel, 'punct');

  const message = events.at(-1)!.data.message;
  assert.deepEqual(message.parts.map((p: any) => p.type), ['text', 'ui']);
  const tree = createParser(library.toJSONSchema()).parse(message.parts[1].lang).root as any;
  assert.equal(tree?.typeName, 'DependencyTree');
  assert.equal(tree.props.document_id, 'doc1');
  assert.equal(tree.props.sentence_index, 3);
  assert.deepEqual(tree.props.arcs, [
    { head: 2, dep: 1, label: 'nsubj' }, { head: 0, dep: 2, label: 'root' }, { head: 2, dep: 3, label: 'obj' }, { head: 2, dep: 4, label: 'punct' },
  ]);
  assert.deepEqual(tree.props.tokens.map((t: any) => t.form), ['他们', '翻译', '这本书', '。']);
  assert.deepEqual(tree.props.highlight, [3]);
});

test('annot.suggest forwards the body with the agent token', async () => {
  const args = { layer_id: DEP_LAYER, document_id: 'doc1', sentence_index: 3, token_index: 3, label: 'obj', head: 2, note: '宾语' };
  const { api, model, call, createSession } = await setup([{ tool: 'annot_suggest', args }, { text: '已提出建议，待你确认。' }]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '建议把这本书改成 obj' })).text());
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([result.name, result.state], ['annot.suggest', 'succeeded']);
  const request = api.requests.find(r => r.path === `/layers/${DEP_LAYER}/suggest`)!;
  assert.equal(request.method, 'POST');
  assert.equal(request.headers.authorization, `Bearer ${AGENT_TOKEN}`);
  assert.deepEqual(request.body, { document_id: 'doc1', sentence_index: 3, token_index: 3, label: 'obj', head: 2, note: '宾语' });
  const toolResult = JSON.parse(model.requests[1].body.messages.find((m: any) => m.role === 'tool').content);
  assert.equal(toolResult.status, 'suggested');
  assert.equal(toolResult.annotation_id, 'annot-1');
  // no confirm path exists for the agent
  assert.ok(!api.requests.some(r => r.path.endsWith('/confirm') || r.path.endsWith('/annotations')));
});

test('annot.create_layer resolves the built-in label set and waits for preannotation', async () => {
  const { api, model, call, createSession } = await setup([
    { tool: 'annot_create_layer', args: { corpus_id: CORPUS, kind: 'pos', name: '词性' } },
    { text: '标注层已就绪。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '建一个词性层' })).text());
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([result.name, result.state], ['annot.create_layer', 'succeeded']);
  assert.deepEqual(result.result_ref, { kind: 'layer', id: 'layer-new' });
  const create = api.requests.find(r => r.path === `/projects/${PROJECT}/layers` && r.method === 'POST')!;
  assert.deepEqual(create.body, { corpus_id: CORPUS, kind: 'pos', name: '词性', label_set_id: 'ls-jieba' });
  assert.ok(api.requests.filter(r => r.path === '/jobs/job-preannotate').length >= 2);
  const toolResult = JSON.parse(model.requests[1].body.messages.find((m: any) => m.role === 'tool').content);
  assert.equal(toolResult.status, 'ready');
  assert.equal(toolResult.layer_id, 'layer-new');
});

test('annot.layers lists documents; annot.sentence resolves document_ordinal', async () => {
  const { api, model, call, createSession } = await setup([
    { tool: 'annot_layers', args: {} },
    { tool: 'annot_sentence', args: { layer_id: DEP_LAYER, document_ordinal: 2, sentence_index: 3 } },
    { text: '用的是第 2 个文档“新闻 01”。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '看第 2 个文档第 4 句' })).text());
  const results = events.filter(e => e.event === 'tool_result').map(e => e.data);
  assert.deepEqual(results.map(r => [r.name, r.state]), [['annot.layers', 'succeeded'], ['annot.sentence', 'succeeded']]);
  const tools = model.requests[2].body.messages.filter((m: any) => m.role === 'tool').map((m: any) => JSON.parse(m.content));
  assert.deepEqual(tools[0].items[0].documents, [{ document_id: 'doc0', title: '前言' }, { document_id: 'doc1', title: '新闻 01' }]);
  assert.deepEqual(tools[0].items[0].document_progress, { total: 1, done: 1 });
  assert.equal(tools[1].document_id, 'doc1');
  assert.equal(tools[1].document_title, '新闻 01');
  assert.ok(api.requests.some(r => r.path === `/layers/${DEP_LAYER}/sentences/doc1/3`));
  // the document list is fetched once per run
  assert.equal(api.requests.filter(r => r.path === `/layers/${DEP_LAYER}/documents`).length, 1);
});

// ---------------------------------------------------------------- P4 knowledge base

const CITATION = [
  'root = KbCitation(items)',
  'items = [{chunk_id: "chunk-1", document_id: "kb-doc-1", title: "翻译腔研究", locator: "第 3 页", text: "翻译腔指译文中受源语结构影响的表达。"}]',
].join('\n');

test('kb.search returns compact chunks and the answer cites them with KbCitation', async () => {
  const { api, model, call, createSession } = await setup([
    { tool: 'kb_search', args: { q: '翻译腔 定义', top_k: 8 } },
    { text: `翻译腔指受源语结构影响的表达（kb-doc-1 / chunk-1）。\n\`\`\`openui-lang\n${CITATION}\n\`\`\`\n` },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '文献里怎么定义翻译腔' })).text());
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([result.name, result.state], ['kb.search', 'succeeded']);
  const request = api.requests.find(r => r.path === `/projects/${PROJECT}/kb/search`)!;
  assert.equal(request.headers.authorization, `Bearer ${AGENT_TOKEN}`);
  assert.deepEqual(request.body, { q: '翻译腔 定义', top_k: 8, mode: 'hybrid' });

  const toolResult = JSON.parse(model.requests[1].body.messages.find((m: any) => m.role === 'tool').content);
  assert.deepEqual(toolResult.items[0], {
    chunk_id: 'chunk-1', document_id: 'kb-doc-1', title: '翻译腔研究', kind: 'literature', locator: '第 3 页',
    text: KB_SEARCH.items[0].chunk.text, score: 0.91,
  });
  assert.equal(toolResult.items[1].locator, '标注规范 › 词性');
  assert.equal(toolResult.items[1].text, LONG_CHUNK.slice(0, 600) + '…');
  assert.deepEqual(toolResult.terms.map((t: any) => [t.term_id, t.status]), [['term-1', 'confirmed']]);

  const message = events.at(-1)!.data.message;
  assert.deepEqual(message.parts.map((p: any) => p.type), ['text', 'ui']);
  const citation = createParser(library.toJSONSchema()).parse(message.parts[1].lang).root as any;
  assert.equal(citation?.typeName, 'KbCitation');
  assert.deepEqual(citation.props.items, [{
    chunk_id: 'chunk-1', document_id: 'kb-doc-1', title: '翻译腔研究', locator: '第 3 页', text: '翻译腔指译文中受源语结构影响的表达。',
  }]);
  const system = model.requests[0].body.messages[0].content;
  assert.match(system, /kb_search/);
  assert.match(system, /KbCitation\(items: /);
});

test('kb.save creates a note, adds refs and returns a note ref', async () => {
  const refs = [{ kind: 'chunk', ref: { chunk_id: 'chunk-1', document_id: 'kb-doc-1' } }];
  const { api, call, createSession } = await setup([
    { tool: 'kb_save', args: { body: '# 翻译腔\n\n定义见 chunk-1。', refs } },
    { text: '已保存为笔记。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '保存为笔记' })).text());
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([result.name, result.state], ['kb.save', 'succeeded']);
  assert.deepEqual(result.result_ref, { kind: 'note', id: 'note-1' });
  const create = api.requests.find(r => r.path === `/projects/${PROJECT}/kb/documents` && r.method === 'POST')!;
  assert.deepEqual(create.body, { kind: 'note', title: '翻译腔', body: '# 翻译腔\n\n定义见 chunk-1。' });
  const ref = api.requests.find(r => r.path === '/kb/documents/note-1/refs')!;
  assert.deepEqual(ref.body, refs[0]);
});

test('kb.extract_terms polls the job and returns the newest 20 drafts', async () => {
  const { api, model, call, createSession } = await setup([
    { tool: 'kb_extract_terms', args: { source: 'corpus' } },
    { text: '新增 25 条草稿术语。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '从语料抽取术语' })).text());
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([result.name, result.state], ['kb.extract_terms', 'succeeded']);
  assert.deepEqual(result.result_ref, { kind: 'job', id: 'job-kbextract' });
  const extract = api.requests.find(r => r.path === `/projects/${PROJECT}/kb/terms/extract`)!;
  assert.deepEqual(extract.body, { source: 'corpus', scope: { corpus_id: CORPUS }, method: 'pos_pattern', top: 100 });
  assert.ok(api.requests.filter(r => r.path === '/jobs/job-kbextract').length >= 2);
  assert.ok(api.requests.some(r => r.path === `/projects/${PROJECT}/kb/terms?status=draft`));
  const toolResult = JSON.parse(model.requests[1].body.messages.find((m: any) => m.role === 'tool').content);
  assert.equal(toolResult.created, 25);
  assert.equal(toolResult.terms.length, 20);
  assert.equal(toolResult.terms[0].term_id, 'draft-24');
  assert.ok(toolResult.terms.every((t: any) => t.status === 'draft'));
});

test('TermCard block parses with the contract props', () => {
  const lang = [
    'root = TermCard("term-1", "翻译腔", translations, "译文受源语影响而显得不自然的语言特征。", "翻译学", examples, "confirmed")',
    'translations = [{language: "en", text: "translationese"}]',
    'examples = [{text: "这种翻译腔在早期译本中很常见。", source: "文献：翻译腔研究 p.3"}]',
  ].join('\n');
  const card = createParser(library.toJSONSchema()).parse(lang).root as any;
  assert.equal(card?.typeName, 'TermCard');
  assert.equal(card.props.term_id, 'term-1');
  assert.deepEqual(card.props.translations, [{ language: 'en', text: 'translationese' }]);
  assert.equal(card.props.domain, '翻译学');
  assert.equal(card.props.examples[0].source, '文献：翻译腔研究 p.3');
  assert.equal(card.props.status, 'confirmed');
});

test('catalog lists the 12 components with the P3 and P4 signatures', () => {
  assert.equal(COMPONENTS.length, 12);
  const catalog = componentCatalog();
  for (const component of COMPONENTS) assert.ok(catalog.includes(component.name), component.name);
  assert.match(catalog, /DependencyTree\(document_id: string, sentence_index: number, tokens: .*arcs: .*highlight\?/);
  assert.match(catalog, /AnnotationDiff\(layer_id: string, document_id: string, sentence_index: number, tokens: /);
  assert.match(catalog, /TermCard\(term_id: string, term: string, translations: .*definition: string, domain: string, examples: .*status: /);
  assert.match(catalog, /KbCitation\(items: /);
});

test('system prompt states 1-based sentence numbering', () => {
  const prompt = systemPrompt('UD 中文');
  assert.ok(prompt.includes('用户说的“第 N 句”对应 sentence_index = N−1'));
  assert.ok(prompt.includes('组件中的 sentence_index 保持工具返回的原值'));
});
