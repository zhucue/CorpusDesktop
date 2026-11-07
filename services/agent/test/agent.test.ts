import assert from 'node:assert/strict';
import { rm } from 'node:fs/promises';
import { after, test } from 'node:test';
import { createParser } from '@openuidev/lang-core';
import { COMPONENTS, componentCatalog, library } from '../src/components.ts';
import type { Config } from '../src/config.ts';
import { createModel } from '../src/model.ts';
import { systemPrompt } from '../src/prompt.ts';
import { Runner } from '../src/runner.ts';
import { findSkill, readSkill, researchSkills } from '../src/skills.ts';
import { CONFIRM_TOOLS, piName, toolSpecs } from '../src/tools.ts';
import { createApp } from '../src/server.ts';
import {
  AGENT_TOKEN, AGREEMENT, SEMANTIC_HITS, VOCAB_LISTS, ALIGN_LAYER, APPENDIX, SAMPLE_LAYER, SAMPLE_SUMMARY, BUILTIN_CORPUS, CORPUS, COOKIE, DEP_LAYER, KB_SEARCH, SPAN_LAYER, LONG_CHUNK, MemoryStore, SKETCH_DIFF_STAT, ORIGIN, PROJECT, USER, fakeApi, fakeModel, parseSse, testConfig, type Reply,
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

type Call = (method: string, path: string, body?: unknown) => Response | Promise<Response>;

/** Pending proposals of the latest assistant message. */
async function pending(call: Call, sessionId: string): Promise<any[]> {
  const detail = await (await call('GET', `/agent/sessions/${sessionId}`)).json() as any;
  return detail.messages.findLast((m: any) => m.role === 'assistant').tool_calls.filter((t: any) => t.state === 'needs_confirmation');
}

/** Presses 执行 on the latest confirm card; returns the SSE events of the confirm run. */
async function confirmAll(call: Call, sessionId: string) {
  const ids = (await pending(call, sessionId)).map(t => t.id);
  assert.ok(ids.length > 0, 'a proposal awaits confirmation');
  const response = await call('POST', `/agent/sessions/${sessionId}/confirm`, { tool_call_ids: ids, action: 'execute' });
  assert.equal(response.status, 200);
  return parseSse(await response.text());
}

/** Tool results the confirm run handed to the model in its [平台消息] prompt. */
function confirmedResults(model: { requests: any[] }, index: number): any[] {
  const user = model.requests[index].body.messages.findLast((m: any) => m.role === 'user');
  const text = typeof user.content === 'string' ? user.content : user.content.map((c: any) => c.text ?? '').join('');
  assert.match(text, /^\[平台消息\]/);
  return [...text.matchAll(/：已执行，结果 (.*)$/gm)].map(m => JSON.parse(m[1]));
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
  assert.equal(toolNames.length, 53);
  // 'read' is the skills-only reader (skills.read); Pi's own file tools stay off
  assert.ok(!toolNames.some((n: string) => ['bash', 'edit', 'write'].includes(n)));
  assert.equal(toolNames.filter((n: string) => n === 'read').length, 1);
  assert.ok(toolNames.includes('stats_collocations') && toolNames.includes('jobs_cancel') && toolNames.includes('kb_search') && toolNames.includes('align_suggest'));

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
  // 429 and 5xx are retried twice: three answers in a row fail the run
  const cases: [Reply[], string][] = [
    [[{ status: 401 }], 'MODEL_AUTH_FAILED'],
    [[{ status: 429 }, { status: 429 }, { status: 429 }], 'MODEL_RATE_LIMITED'],
    [[{ status: 500 }, { status: 500 }, { status: 500 }], 'MODEL_REQUEST_FAILED'],
  ];
  for (const [replies, code] of cases) {
    const { app, call, createSession } = await setup(replies);
    assert.equal(((await (await app.request('/agent/health')).json()) as any).ok, true);
    const session = await createSession();
    const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '你好' })).text());
    assert.deepEqual(events.map(e => e.event), ['start', 'error']);
    assert.equal(events[1].data.code, code);
  }
});

test('model timeout maps to MODEL_TIMEOUT', async () => {
  const { call, createSession } = await setup([{ hang: true }, { hang: true }, { hang: true }], { modelTimeoutMs: 300 });
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

test('corpus.sentence reads system dependencies of a built-in corpus without a layer, then a DependencyTree block', async () => {
  const tree = [
    'root = DependencyTree("gsd-train", 0, tokens, arcs)',
    'tokens = [{index: 1, form: "他們", pos: "PRON"}, {index: 2, form: "翻譯", pos: "VERB"}, {index: 3, form: "這本書", pos: "NOUN"}, {index: 4, form: "。", pos: "PUNCT"}]',
    'arcs = [{head: 2, dep: 1, label: "nsubj"}, {head: 0, dep: 2, label: "root"}, {head: 2, dep: 3, label: "obj"}, {head: 2, dep: 4, label: "punct"}]',
  ].join('\n');
  const { api, model, call, createSession } = await setup([
    { tool: 'corpus_sentence', args: { corpus_id: BUILTIN_CORPUS, sentence_index: 0 } },
    { text: `zh_gsd-ud-train 第 1 句：\n\`\`\`openui-lang\n${tree}\n\`\`\`\n` },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '用依存树展示 UD 中文 GSD 的第 1 句' })).text());
  assert.equal(events.at(-1)!.event, 'done');
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([result.name, result.state], ['corpus.sentence', 'succeeded']);
  // read-only: no confirm card, no layer created
  assert.ok(!events.some(e => e.event === 'tool_result' && e.data.state === 'needs_confirmation'));
  assert.ok(!api.requests.some(r => r.method === 'POST' && r.path.startsWith('/layers')));
  const read = api.requests.find(r => r.path === `/corpora/${BUILTIN_CORPUS}/documents/gsd-train/sentences/0`)!;
  assert.equal(read.headers.authorization, `Bearer ${AGENT_TOKEN}`);
  const toolResult = JSON.parse(model.requests[1].body.messages.find((m: any) => m.role === 'tool').content);
  assert.equal(toolResult.document_title, 'zh_gsd-ud-train');
  assert.deepEqual(toolResult.tokens[0], { index: 1, form: '他們', pos: 'PRON', lemma: null, head: 2, deprel: 'nsubj' });
  const message = events.at(-1)!.data.message;
  const parsed = createParser(library.toJSONSchema()).parse(message.parts[1].lang).root as any;
  assert.equal(parsed?.typeName, 'DependencyTree');
  assert.equal(parsed.props.arcs.length, 4);
  assert.match(model.requests[0].body.messages[0].content, /corpus_sentence/);
});

test('annot.suggest forwards the body with the agent token', async () => {
  const args = { layer_id: DEP_LAYER, document_id: 'doc1', sentence_index: 3, token_index: 3, label: 'obj', head: 2, note: '宾语' };
  const { api, model, call, createSession } = await setup([
    { tool: 'annot_suggest', args }, { text: '将提出建议，请确认。' }, { text: '已提出建议，待你确认。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '建议把这本书改成 obj' })).text());
  const proposed = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([proposed.name, proposed.state], ['annot.suggest', 'needs_confirmation']);
  assert.deepEqual(proposed.confirm, { title: '提出标注建议（待人工确认）', lines: ['标注层：依存', '第 4 句第 3 个词 → obj，head 2', '理由：宾语'] });
  assert.ok(!api.requests.some(r => r.path === `/layers/${DEP_LAYER}/suggest`), 'nothing is written before 执行');

  const confirmed = await confirmAll(call, session.id);
  const result = confirmed.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([result.name, result.state], ['annot.suggest', 'succeeded']);
  assert.equal(confirmed.at(-1)!.event, 'done');
  const request = api.requests.find(r => r.path === `/layers/${DEP_LAYER}/suggest`)!;
  assert.equal(request.method, 'POST');
  assert.equal(request.headers.authorization, `Bearer ${AGENT_TOKEN}`);
  assert.deepEqual(request.body, { document_id: 'doc1', sentence_index: 3, token_index: 3, label: 'obj', head: 2, note: '宾语' });
  const [toolResult] = confirmedResults(model, 2);
  assert.equal(toolResult.status, 'suggested');
  assert.equal(toolResult.annotation_id, 'annot-1');
  // no confirm path exists for the agent
  assert.ok(!api.requests.some(r => r.path.endsWith('/confirm') || r.path.endsWith('/annotations')));
});

test('annot.create_layer resolves the built-in label set and waits for preannotation', async () => {
  const { api, model, call, createSession } = await setup([
    { tool: 'annot_create_layer', args: { corpus_id: CORPUS, kind: 'pos', name: '词性' } },
    { text: '将新建词性层，请确认。' },
    { text: '标注层已就绪。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '建一个词性层' })).text());
  const proposed = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([proposed.name, proposed.state], ['annot.create_layer', 'needs_confirmation']);
  assert.equal(proposed.confirm.title, '新建词性标注层「词性」并预标');
  assert.deepEqual(proposed.confirm.lines, ['语料库：UD 中文', '文档：全部', '标签集：jieba']);
  assert.ok(!api.requests.some(r => r.path === `/projects/${PROJECT}/layers` && r.method === 'POST'), 'no layer before 执行');
  // the model is told the call is only proposed
  const proposal = JSON.parse(model.requests[1].body.messages.find((m: any) => m.role === 'tool').content);
  assert.equal(proposal.status, 'NEEDS_CONFIRMATION');

  const confirmed = await confirmAll(call, session.id);
  const result = confirmed.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([result.name, result.state], ['annot.create_layer', 'succeeded']);
  assert.deepEqual(result.result_ref, { kind: 'layer', id: 'layer-new' });
  const create = api.requests.find(r => r.path === `/projects/${PROJECT}/layers` && r.method === 'POST')!;
  assert.deepEqual(create.body, { corpus_id: CORPUS, kind: 'pos', name: '词性', label_set_id: 'ls-jieba' });
  assert.ok(api.requests.filter(r => r.path === '/jobs/job-preannotate').length >= 2);
  const [toolResult] = confirmedResults(model, 2);
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
  const refs = [
    { kind: 'chunk', ref: { chunk_id: 'chunk-1', document_id: 'kb-doc-1' } },
    { kind: 'evidence', ref: { evidence_id: 'ev-cited' } },
  ];
  const { api, model, call, createSession } = await setup([
    { tool: 'kb_save', args: { body: '# 翻译腔\n\n定义见 chunk-1。', refs } },
    { text: '将新建笔记，请确认。' },
    { text: '已保存为笔记。' },
  ]);
  const session = await createSession();
  const first = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '保存为笔记' })).text());
  assert.equal(first.find(e => e.event === 'tool_result')!.data.confirm.title, '新建笔记「翻译腔」');
  const events = await confirmAll(call, session.id);
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([result.name, result.state], ['kb.save', 'succeeded']);
  assert.deepEqual(result.result_ref, { kind: 'note', id: 'note-1' });
  const create = api.requests.find(r => r.path === `/projects/${PROJECT}/kb/documents` && r.method === 'POST')!;
  assert.deepEqual(create.body, { kind: 'note', title: '翻译腔', body: '# 翻译腔\n\n定义见 chunk-1。' });
  const ref = api.requests.find(r => r.path === '/kb/documents/note-1/refs')!;
  // the quote is already in body, so the ref is recorded without appending it again
  assert.deepEqual(ref.body, { ...refs[0], append: false });
  // refs_added counts the refs the API stored, not the refs passed (the note already cited ev-cited)
  assert.equal(api.requests.filter(r => r.path === '/kb/documents/note-1/refs').length, 2);
  assert.equal(confirmedResults(model, 2)[0].refs_added, 1);
});

test('kb.extract_terms polls the job and returns the newest 20 drafts', async () => {
  const { api, model, call, createSession } = await setup([
    { tool: 'kb_extract_terms', args: { source: 'corpus' } },
    { text: '将抽取术语，请确认。' },
    { text: '新增 25 条草稿术语。' },
  ]);
  const session = await createSession();
  parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '从语料抽取术语' })).text());
  const events = await confirmAll(call, session.id);
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([result.name, result.state], ['kb.extract_terms', 'succeeded']);
  assert.deepEqual(result.result_ref, { kind: 'job', id: 'job-kbextract' });
  const extract = api.requests.find(r => r.path === `/projects/${PROJECT}/kb/terms/extract`)!;
  assert.deepEqual(extract.body, { source: 'corpus', scope: { corpus_id: CORPUS }, method: 'pos_pattern', top: 100 });
  assert.ok(api.requests.filter(r => r.path === '/jobs/job-kbextract').length >= 2);
  assert.ok(api.requests.some(r => r.path === `/projects/${PROJECT}/kb/terms?status=draft`));
  const [toolResult] = confirmedResults(model, 2);
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

test('catalog lists the 19 components with the P3, P4, P5, P8 and P10 signatures', () => {
  assert.equal(COMPONENTS.length, 19);
  const catalog = componentCatalog();
  for (const component of COMPONENTS) assert.ok(catalog.includes(component.name), component.name);
  assert.match(catalog, /DependencyTree\(document_id: string, sentence_index: number, tokens: .*arcs: .*highlight\?/);
  assert.match(catalog, /AnnotationDiff\(layer_id: string, document_id: string, sentence_index: number, tokens: /);
  assert.match(catalog, /TermCard\(term_id: string, term: string, translations: .*definition: string, domain: string, examples: .*status: /);
  assert.match(catalog, /KbCitation\(items: /);
  assert.match(catalog, /SpanView\(document_id: string, sentence_index: number, text: string, spans: .*relations: /);
  assert.match(catalog, /AlignmentGraph\(src_tokens: string\[\], tgt_tokens: string\[\], links: .*layer_id\?: string, src_document_id\?: string, src_sentence_index\?: number\)/);
});

test('system prompt states 1-based sentence numbering', () => {
  const prompt = systemPrompt('UD 中文');
  assert.ok(prompt.includes('用户说的“第 N 句”对应 sentence_index = N−1'));
  assert.ok(prompt.includes('组件中的 sentence_index 保持工具返回的原值'));
  assert.match(prompt, /annot_suggest_spans/);
  assert.match(prompt, /AlignmentGraph/);
});

// ---------------------------------------------------------------- P5 spans, alignment, agreement

const toolResults = (model: { requests: any[] }, index: number) =>
  model.requests[index].body.messages.filter((m: any) => m.role === 'tool').map((m: any) => JSON.parse(m.content));

test('kb.search sets a kb_document ref when all chunks come from one document', async () => {
  const { call, createSession } = await setup([
    { tool: 'kb_search', args: { q: '翻译腔', document_ids: ['kb-doc-1'] } },
    { tool: 'kb_search', args: { q: '翻译腔' } },
    { text: '见 chunk-1。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '翻译腔' })).text());
  const results = events.filter(e => e.event === 'tool_result').map(e => e.data);
  assert.deepEqual(results[0].result_ref, { kind: 'kb_document', id: 'kb-doc-1' });
  assert.equal(results[1].result_ref, undefined); // two documents → no single ref
});

test('annot.spans then a SpanView block; annot.suggest_spans posts the suggestion with the agent token', async () => {
  const spanView = [
    'root = SpanView("doc1", 3, "他们翻译这本书。", spans, relations)',
    'spans = [{start: 2, end: 4, label: "直译"}, {start: 4, end: 7, label: "增译"}, {start: 0, end: 2, label: "增译"}]',
    'relations = [{from: 1, to: 0, label: "cause"}]',
  ].join('\n');
  const suggest = {
    layer_id: SPAN_LAYER, document_id: 'doc1', sentence_index: 3,
    spans: [{ start_cp: 100, end_cp: 102, label: '增译', attrs: { note: '主语补出' } }], relations: [{ from: 0, to: 'span-1', label: 'cause' }],
  };
  const { api, model, call, createSession } = await setup([
    { tool: 'annot_spans', args: { layer_id: SPAN_LAYER, document_ordinal: 2, sentence_index: 3 } },
    { tool: 'annot_suggest_spans', args: suggest },
    { text: `doc1 第 4 句的翻译策略（待确认）：\n\`\`\`openui-lang\n${spanView}\n\`\`\`\n` },
    { text: '已提出片段建议。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '标出第 4 句里的翻译策略' })).text());
  assert.equal(events.at(-1)!.event, 'done');
  const results = events.filter(e => e.event === 'tool_result').map(e => e.data);
  assert.deepEqual(results.map(r => [r.name, r.state]), [['annot.spans', 'succeeded'], ['annot.suggest_spans', 'needs_confirmation']]);
  assert.deepEqual(results[0].result_ref, { kind: 'layer', id: SPAN_LAYER });
  assert.deepEqual(results[1].confirm.lines, ['标注层：片段', '第 4 句：他们（增译）', '关系：1 条']);
  assert.ok(!api.requests.some(r => r.path === `/layers/${SPAN_LAYER}/spans/suggest`));
  const executed = (await confirmAll(call, session.id)).find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([executed.name, executed.state, executed.result_ref], ['annot.suggest_spans', 'succeeded', { kind: 'layer', id: SPAN_LAYER }]);

  const read = api.requests.find(r => r.path.startsWith(`/layers/${SPAN_LAYER}/spans?`))!;
  assert.equal(read.path, `/layers/${SPAN_LAYER}/spans?document_id=doc1&cursor=doc1%3A2&page_size=1`);
  assert.equal(read.headers.authorization, `Bearer ${AGENT_TOKEN}`);
  const [spans] = toolResults(model, 2);
  const [suggested] = confirmedResults(model, 3);
  assert.equal(spans.document_title, '新闻 01');
  assert.equal(spans.start_cp, 100);
  assert.deepEqual(spans.spans.map((s: any) => [s.span_id, s.start, s.end, s.label, s.status]),
    [['span-1', 2, 4, '直译', 'confirmed'], ['span-2', 4, 7, '增译', 'suggested']]);
  assert.deepEqual(spans.relations, [{
    relation_id: 'rel-1', from: 1, to: 0, from_span_id: 'span-2', to_span_id: 'span-1', label: 'cause', status: 'confirmed', source: `human:${USER.id}`,
  }]);

  const post = api.requests.find(r => r.path === `/layers/${SPAN_LAYER}/spans/suggest`)!;
  assert.equal(post.method, 'POST');
  assert.equal(post.headers.authorization, `Bearer ${AGENT_TOKEN}`);
  assert.deepEqual(post.body, { document_id: 'doc1', sentence_index: 3, spans: suggest.spans, relations: suggest.relations });
  assert.deepEqual(suggested.spans, [{
    span_id: 'new-span-0', start: 0, end: 2, start_cp: 100, end_cp: 102, text: '他们', label: '增译', status: 'suggested', source: 'model:agent',
  }]);
  assert.deepEqual(suggested.relations, [{ relation_id: 'new-rel-0', from_span_id: 'new-span-0', to_span_id: 'span-1', label: 'cause', status: 'suggested' }]);
  // the agent never confirms
  assert.ok(!api.requests.some(r => r.method === 'PATCH' || r.path === `/layers/${SPAN_LAYER}/spans`));

  const message = events.at(-1)!.data.message;
  const view = createParser(library.toJSONSchema()).parse(message.parts[1].lang).root as any;
  assert.equal(view?.typeName, 'SpanView');
  assert.equal(view.props.document_id, 'doc1');
  assert.equal(view.props.sentence_index, 3);
  assert.equal(view.props.text, '他们翻译这本书。');
  assert.deepEqual(view.props.spans[1], { start: 4, end: 7, label: '增译' });
  assert.deepEqual(view.props.relations, [{ from: 1, to: 0, label: 'cause' }]);
});

test('annot.suggest_spans rejects spans outside the sentence before posting', async () => {
  const { api, call, createSession } = await setup([
    { tool: 'annot_suggest_spans', args: { layer_id: SPAN_LAYER, document_id: 'doc1', sentence_index: 3, spans: [{ start_cp: 2, end_cp: 4, label: '直译' }] } },
    { text: '偏移有误。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '标出' })).text());
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.equal(result.state, 'failed');
  assert.match(JSON.stringify(result), /SPAN_OUT_OF_SENTENCE/);
  assert.ok(!api.requests.some(r => r.path.endsWith('/spans/suggest')));
});

test('align.pairs then an AlignmentGraph block; align.suggest posts links with the agent token', async () => {
  const graph = [
    `root = AlignmentGraph(["He", "translated", "the", "book", "."], ["他", "翻译", "了", "这本书", "。"], links, "${ALIGN_LAYER}", "src-doc", 0)`,
    'links = [{src: [1], tgt: [1], status: "confirmed"}, {src: [3, 4], tgt: [4], status: "suggested"}, {src: [2], tgt: [2, 3], status: "suggested"}]',
  ].join('\n');
  const suggest = {
    layer_id: ALIGN_LAYER, src_document_id: 'src-doc', src_sentence_index: 0, tgt_document_id: 'tgt-doc', tgt_sentence_index: 0,
    links: [{ src: [2], tgt: [2, 3] }],
  };
  const { api, model, call, createSession } = await setup([
    { tool: 'align_pairs', args: { layer_id: ALIGN_LAYER, src_document_id: 'src-doc', src_sentence_index: 0 } },
    { tool: 'align_suggest', args: suggest },
    { text: `src-doc 第 1 句的对齐：\n\`\`\`openui-lang\n${graph}\n\`\`\`\n` },
    { text: '已提出对齐建议。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '看这对句子的对齐' })).text());
  const results = events.filter(e => e.event === 'tool_result').map(e => e.data);
  assert.deepEqual(results.map(r => [r.name, r.state]), [['align.pairs', 'succeeded'], ['align.suggest', 'needs_confirmation']]);
  assert.deepEqual(results[1].confirm, { title: '提出词级对齐建议（待人工确认）', lines: ['对齐层：对齐', '源文第 1 句：1 条连线'] });
  const executed = (await confirmAll(call, session.id)).find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([executed.name, executed.state, executed.result_ref], ['align.suggest', 'succeeded', { kind: 'layer', id: ALIGN_LAYER }]);

  const read = api.requests.find(r => r.path.startsWith(`/layers/${ALIGN_LAYER}/alignments?`))!;
  assert.equal(read.path, `/layers/${ALIGN_LAYER}/alignments?src_document_id=src-doc&page_size=10`);
  const [pairs] = toolResults(model, 2);
  const [suggested] = confirmedResults(model, 3);
  assert.deepEqual(pairs.pairs[0].src.tokens, ['He', 'translated', 'the', 'book', '.']);
  // the AlignmentGraph locator fields travel with each pair
  assert.equal(pairs.pairs[0].layer_id, ALIGN_LAYER);
  assert.equal(pairs.pairs[0].src_document_id, 'src-doc');
  assert.equal(pairs.pairs[0].src_sentence_index, 0);
  assert.deepEqual(pairs.pairs[0].tgt.tokens, ['他', '翻译', '了', '这本书', '。']);
  assert.deepEqual(pairs.pairs[0].alignments[1], {
    alignment_id: 'al-2', level: 'word', src_tokens: [3, 4], tgt_tokens: [4], score: null, source: 'model:fake-model', status: 'suggested',
  });
  assert.equal(pairs.next_cursor, 'src-doc:0');

  const post = api.requests.find(r => r.path === `/layers/${ALIGN_LAYER}/alignments/suggest`)!;
  assert.equal(post.method, 'POST');
  assert.equal(post.headers.authorization, `Bearer ${AGENT_TOKEN}`);
  const { layer_id: _layer, ...body } = suggest;
  assert.deepEqual(post.body, body);
  assert.deepEqual(suggested.alignments, [{ alignment_id: 'new-al-0', src_tokens: [2], tgt_tokens: [2, 3], status: 'suggested', source: 'model:agent' }]);

  const message = events.at(-1)!.data.message;
  const view = createParser(library.toJSONSchema()).parse(message.parts[1].lang).root as any;
  assert.equal(view?.typeName, 'AlignmentGraph');
  assert.equal(view.props.src_tokens.length, 5);
  assert.deepEqual(view.props.links[1], { src: [3, 4], tgt: [4], status: 'suggested' });
  assert.equal(view.props.layer_id, ALIGN_LAYER);
  assert.equal(view.props.src_document_id, 'src-doc');
  assert.equal(view.props.src_sentence_index, 0);
});

test('align.pairs starts at a given source sentence via the exclusive cursor', async () => {
  const { api, call, createSession } = await setup([
    { tool: 'align_pairs', args: { layer_id: ALIGN_LAYER, src_document_id: 'src-doc', src_sentence_index: 5 } },
    { text: '好。' },
  ]);
  const session = await createSession();
  parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '第 6 句' })).text());
  assert.ok(api.requests.some(r => r.path === `/layers/${ALIGN_LAYER}/alignments?src_document_id=src-doc&cursor=src-doc%3A4&page_size=10`));
});

test('annot.agreement reads kappa, alpha and the top 10 disagreements', async () => {
  const { api, model, call, createSession } = await setup([
    { tool: 'annot_agreement', args: { layer_id: SPAN_LAYER } },
    { text: 'κ = 0.72。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '一致性如何' })).text());
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([result.name, result.state], ['annot.agreement', 'succeeded']);
  assert.deepEqual(result.result_ref, { kind: 'layer', id: SPAN_LAYER });
  for (const path of [`/layers/${SPAN_LAYER}/agreement`, `/layers/${SPAN_LAYER}/disagreements`]) {
    assert.equal(api.requests.find(r => r.path === path)!.headers.authorization, `Bearer ${AGENT_TOKEN}`);
  }
  const [agreement] = toolResults(model, 1);
  assert.equal(agreement.alpha, 0.71);
  assert.deepEqual(agreement.pairwise, AGREEMENT.pairwise);
  assert.deepEqual(agreement.per_label, AGREEMENT.per_label);
  assert.equal(agreement.annotators.length, 2);
  assert.equal(agreement.disagreements.length, 10);
  assert.equal(agreement.more_disagreements, true);
});

// ---------------------------------------------------------------- write-tool confirmation, regenerate, stop

test('write tools on a built-in corpus fail before any proposal; no layer is created', async () => {
  const { api, call, createSession } = await setup([
    { tool: 'annot_create_layer', args: { corpus_id: BUILTIN_CORPUS, kind: 'dep', name: '依存' } },
    { text: '内置语料不能由助手建层。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '用依存树展示 UD 中文 GSD 的第 1 句' })).text());
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([result.name, result.state], ['annot.create_layer', 'failed']);
  assert.match(result.result_summary, /BUILTIN_CORPUS/);
  assert.equal(result.confirm, undefined);
  assert.ok(!api.requests.some(r => r.method === 'POST' && r.path.endsWith('/layers')));
  assert.deepEqual(await pending(call, session.id), []);
});

test('decline: nothing runs, the card answer is final, and the model hears about it with the next message', async () => {
  const { api, model, call, createSession } = await setup([
    { tool: 'evidence_add', args: { kind: 'text', ref: {}, text: '翻译是再创作。', source: '笔记' } },
    { text: '要把这句加入证据篮吗？' },
    { text: '好的，不加入。' },
  ]);
  const session = await createSession();
  parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '把这句放进证据篮' })).text());
  const [proposal] = await pending(call, session.id);
  assert.deepEqual(proposal.confirm, { title: '加入证据篮', lines: ['翻译是再创作。', '出处：笔记'] });

  const declined = await call('POST', `/agent/sessions/${session.id}/confirm`, { tool_call_ids: [proposal.id], action: 'decline' });
  assert.equal(declined.status, 200);
  const message = ((await declined.json()) as any).message;
  assert.equal(message.tool_calls[0].state, 'declined');
  // a handled proposal cannot be answered again
  const again = await call('POST', `/agent/sessions/${session.id}/confirm`, { tool_call_ids: [proposal.id], action: 'execute' });
  assert.equal(again.status, 409);
  assert.equal(((await again.json()) as any).error.code, 'CONFIRMATION_EXPIRED');
  const invalid = await call('POST', `/agent/sessions/${session.id}/confirm`, { tool_call_ids: [], action: 'execute' });
  assert.equal(invalid.status, 422);

  parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '那算了' })).text());
  assert.ok(!api.requests.some(r => r.path === `/projects/${PROJECT}/evidence`));
  const user = model.requests[2].body.messages.findLast((m: any) => m.role === 'user');
  const text = typeof user.content === 'string' ? user.content : user.content.map((c: any) => c.text ?? '').join('');
  assert.match(text, /^\[平台消息\] 用户取消了你上次提出的操作：加入证据篮/);
  assert.match(text, /那算了$/);
});

test('regenerate replaces the last question and answer, in the store and in the model context', async () => {
  const { model, call, createSession } = await setup([{ text: '第一次回答。' }, { text: '第二次回答。' }]);
  const session = await createSession();
  parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '翻译腔是什么' })).text());
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { regenerate: true })).text());
  assert.equal(events.at(-1)!.event, 'done');
  const detail = await (await call('GET', `/agent/sessions/${session.id}`)).json() as any;
  assert.deepEqual(detail.messages.map((m: any) => [m.role, m.content]), [['user', '翻译腔是什么'], ['assistant', '第二次回答。']]);
  const contents = model.requests[1].body.messages.map((m: any) => typeof m.content === 'string' ? m.content : JSON.stringify(m.content));
  assert.ok(!contents.some((c: string) => c.includes('第一次回答')), 'the replaced answer left the context');
  assert.equal(contents.filter((c: string) => c.includes('翻译腔是什么')).length, 1);
});

test('a stopped run is persisted as stopped', async () => {
  const { api, call, createSession } = await setup(
    [{ tool: 'stats_frequency', args: {} }],
    { api: { statJobState: 'running' }, config: { jobWaitMs: 60000 } },
  );
  const session = await createSession();
  const body = (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '统计词频' })).text();
  await api.firstJobPoll;
  await call('POST', `/agent/sessions/${session.id}/cancel`);
  const events = parseSse(await body);
  assert.equal(events.at(-1)!.data.message.stopped, true);
  const detail = await (await call('GET', `/agent/sessions/${session.id}`)).json() as any;
  assert.equal(detail.messages[1].stopped, true);
});

test('system prompt: read-only requests never call write tools, and prose carries no internal IDs', () => {
  const prompt = systemPrompt('UD 中文');
  assert.ok(prompt.includes('绝不调用写操作工具'));
  assert.ok(prompt.includes('NEEDS_CONFIRMATION'));
  assert.ok(prompt.includes('你不在内置语料上建标注层'));
  assert.ok(prompt.includes('正文和思考中都不写内部 ID'));
  assert.ok(!prompt.includes('写出 hit_id') && !prompt.includes('写出 document_id'));
});

test('page context reaches the model before the question; the stored message shows only the question', async () => {
  const { model, call, createSession } = await setup([{ text: '这两条都是动词用法。' }, { text: '再答一次。' }]);
  const session = await createSession();
  const context = {
    page: 'search', label: 'UD 中文', query: '翻译/v', search_id: 'search-1', hit_ids: ['doc1:10-12', 'doc2:4-6'],
    scope: { corpus_id: CORPUS },
  };
  const response = await call('POST', `/agent/sessions/${session.id}/messages`, { content: '选中的两条有什么区别', context });
  assert.equal(response.status, 200);
  const events = parseSse(await response.text());
  assert.equal(events.at(-1)!.event, 'done');

  const userText = (index: number) => {
    const user = model.requests[index].body.messages.findLast((m: any) => m.role === 'user');
    return typeof user.content === 'string' ? user.content : user.content.map((c: any) => c.text ?? '').join('');
  };
  const sent = userText(0);
  assert.match(sent, /^\[当前页面：检索\] 范围：UD 中文（语料库，工具参数 corpus_id=22222222-2222-4222-8222-222222222222）；查询式：翻译\/v；检索结果 search_id=search-1；选中命中 hit_id：doc1:10-12、doc2:4-6\n\n选中的两条有什么区别$/);
  assert.match(model.requests[0].body.messages[0].content, /\[当前页面：…\]/);

  const detail = await (await call('GET', `/agent/sessions/${session.id}`)).json() as any;
  const user = detail.messages[0];
  assert.equal(user.content, '选中的两条有什么区别');
  assert.deepEqual(user.parts, [{ type: 'text', text: '选中的两条有什么区别' }]);
  assert.deepEqual(user.context, context);
  assert.equal(detail.title, '选中的两条有什么区别');

  // regenerate re-asks with the stored context
  parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { regenerate: true })).text());
  assert.match(userText(1), /^\[当前页面：检索\][^\n]*search_id=search-1/);

  // other pages send page, label and scope only; bad context is rejected before the run
  const plain = await call('POST', `/agent/sessions/${session.id}/messages`, { content: 'x', context: { page: 'search', label: 'a', scope: null, hit_ids: Array(21).fill('h') } });
  assert.equal(plain.status, 422);
  assert.equal(((await plain.json()) as any).error.code, 'INVALID_CONTEXT');
  assert.equal((await call('POST', `/agent/sessions/${session.id}/messages`, { content: 'x', context: { page: 'home', label: 'a', scope: null } })).status, 422);
});

test('a user who must change the password gets 403 PASSWORD_CHANGE_REQUIRED from every session route', async () => {
  const { api, call, createSession } = await setup([]);
  const session = await createSession();
  api.me.must_change_password = true;
  const routes: [string, string, unknown?][] = [
    ['GET', `/agent/sessions?project_id=${PROJECT}`],
    ['POST', '/agent/sessions', { project_id: PROJECT, scope: null }],
    ['GET', `/agent/sessions/${session.id}`],
    ['PATCH', `/agent/sessions/${session.id}`, { title: 'x' }],
    ['DELETE', `/agent/sessions/${session.id}`],
    ['POST', `/agent/sessions/${session.id}/messages`, { content: '你好' }],
    ['POST', `/agent/sessions/${session.id}/cancel`],
    ['POST', `/agent/sessions/${session.id}/confirm`, { tool_call_ids: ['x'], action: 'decline' }],
  ];
  for (const [method, path, body] of routes) {
    const response = await call(method, path, body);
    assert.equal(response.status, 403, `${method} ${path}`);
    assert.equal(((await response.json()) as any).error.code, 'PASSWORD_CHANGE_REQUIRED');
  }
  api.me.must_change_password = false;
  assert.equal((await call('GET', `/agent/sessions/${session.id}`)).status, 200);
});

// ---------------------------------------------------------------- P8 research tools (contracts/p8.md §七)

const TRANSLATIONS = [
  'root = TranslationTable("stat-tr", "\\"翻译\\"", "dice", rows)',
  'rows = [{item: "translate", cooc: 55, pct: 78.6, score: 0.9, search_query: "\\"翻译\\"", search_aligned: {op: "+", query: "\\"translate\\""}}]',
].join('\n');

test('stats.translations and stats.breakdown: request bodies, first 50 rows with stat_id and row links, TranslationTable block', async () => {
  const { api, model, call, createSession } = await setup([
    { tool: 'stats_translations', args: { query: '"翻译"', target_language: 'en' } },
    { tool: 'stats_breakdown', args: { query: '翻译', by: 'meta:year' } },
    { text: `“翻译”最常见的译法是 translate。\n\n\`\`\`openui-lang\n${TRANSLATIONS}\n\`\`\`\n` },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '统计 翻译 的译法' })).text());
  const results = events.filter(e => e.event === 'tool_result').map(e => e.data);
  assert.deepEqual(results.map(r => [r.name, r.state]), [['stats.translations', 'succeeded'], ['stats.breakdown', 'succeeded']]);
  assert.deepEqual(results[0].result_ref, { kind: 'stat', id: 'stat-tr' });
  assert.equal(results[0].result_summary, '译法：55 行');
  assert.deepEqual(results[1].result_ref, { kind: 'stat', id: 'stat-bd' });

  const tr = api.requests.find(r => r.path === '/stats/translations')!;
  assert.equal(tr.headers.authorization, `Bearer ${AGENT_TOKEN}`);
  assert.deepEqual(tr.body, {
    scope: { corpus_id: CORPUS }, query: '"翻译"', unit: 'word', target_language: 'en', measure: 'dice', top: 100, min_freq: 2, exclude_punct: true,
  });
  const bd = api.requests.find(r => r.path === '/stats/breakdown')!;
  assert.deepEqual(bd.body, { scope: { corpus_id: CORPUS }, query: '翻译', by: 'meta:year', top: 200, min_freq: 1 });

  const [trResult, bdResult] = toolResults(model, 2);
  assert.equal(trResult.stat_id, 'stat-tr');
  assert.equal(trResult.rows.length, 50);
  assert.equal(trResult.row_count, 55);
  assert.equal(trResult.totals.unaligned, 4);
  // same scope as the session (null fields aside): no search_scope on the row
  assert.deepEqual(trResult.rows[0], {
    key: 'translate', values: { item: 'translate', cooc: 55, pct: 78.6, target_freq: 120, dice: 0.9, ll: 30.5 },
    search_query: '"翻译"', search_aligned: { op: '+', query: '"translate"' },
  });
  // meta rows filter the scope: search_scope kept; rows that cannot be searched keep search_query null
  assert.deepEqual(bdResult.rows[0].search_scope, { corpus_id: CORPUS, filter: { year: ['2001'] } });
  assert.equal(bdResult.rows[1].search_query, null);
  assert.equal(bdResult.rows[1].search_scope, undefined);

  const message = events.at(-1)!.data.message;
  const root = createParser(library.toJSONSchema()).parse(message.parts.find((p: any) => p.type === 'ui').lang).root as any;
  assert.equal(root?.typeName, 'TranslationTable');
  assert.deepEqual([root.props.rows[0].item, root.props.rows[0].cooc], ['translate', 55]);
  assert.deepEqual(root.props.rows[0].search_aligned, { op: '+', query: '"translate"' });
});

test('new stats parameters and corpus.search aligned map onto the api bodies', async () => {
  const { api, call, createSession } = await setup([
    { tool: 'stats_frequency', args: { parts: 'field:year', dispersion: true } },
    { tool: 'stats_keywords', args: { reference: { corpus_id: 'ref-corpus' }, measure: 'pct_diff', direction: 'negative', items: ['翻译', '译者'] } },
    { tool: 'stats_collocations', args: { node: '翻译', measures: ['mi3', 'delta_p', 'z'] } },
    { tool: 'corpus_search', args: { query: '"翻译"', aligned: { op: '-', query: '"translate"' } } },
    { tool: 'stats_distribution', args: { query: '"翻译"', field: 'year', aligned: { op: '+', query: '{lemma=translate}' } } },
    { text: '完成。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '对比' })).text());
  const results = events.filter(e => e.event === 'tool_result').map(e => e.data);
  assert.ok(results.every(r => r.state === 'succeeded'), JSON.stringify(results.map(r => [r.name, r.result_summary])));
  assert.match(results[3].result_summary, /含译文条件/);

  const body = (path: string) => api.requests.find(r => r.path === path)!.body;
  assert.deepEqual(body('/stats/frequency'), { scope: { corpus_id: CORPUS }, unit: 'word', top: 200, min_freq: 1, parts: 'field:year', dispersion: true });
  assert.deepEqual(body('/stats/keywords'), {
    target: { corpus_id: CORPUS }, reference: { corpus_id: 'ref-corpus' }, unit: 'word', measure: 'pct_diff', min_freq: 3, top: 200,
    direction: 'negative', items: ['翻译', '译者'],
  });
  assert.deepEqual(body('/stats/collocations').measures, ['mi3', 'delta_p', 'z']);
  assert.deepEqual(body('/search').aligned, { op: '-', query: '"translate"' });
  assert.equal(body('/search').query, '"翻译"');
  assert.deepEqual(body('/stats/distribution').aligned, { op: '+', query: '{lemma=translate}' });
});

test('methods.appendix posts the sources and returns the markdown without a confirmation', async () => {
  const { api, model, call, createSession } = await setup([
    { tool: 'methods_appendix', args: { stat_ids: ['stat-1'], searches: [{ query: '"翻译"', aligned: { op: '+', query: '"translate"' } }], layer_ids: [SAMPLE_LAYER] } },
    { text: '方法附录如下。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '写方法部分' })).text());
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([result.name, result.state], ['methods.appendix', 'succeeded']);
  const request = api.requests.find(r => r.path === `/projects/${PROJECT}/method-appendix`)!;
  assert.equal(request.method, 'POST');
  assert.deepEqual(request.body, {
    stat_ids: ['stat-1'], searches: [{ query: '"翻译"', scope: { corpus_id: CORPUS }, aligned: { op: '+', query: '"translate"' } }],
    layer_ids: [SAMPLE_LAYER], style: 'gbt7714',
  });
  const [data] = toolResults(model, 1);
  assert.equal(data.markdown, APPENDIX.markdown);
  assert.deepEqual(data.citations, APPENDIX.citations);
});

test('sample.create needs confirmation, resolves the span label set by name; sample.summary reads the summary', async () => {
  const args = { query: '"翻译"', n: 2, seed: 7, layer_name: '翻译策略抽样', label_set_name: '翻译策略' };
  const { api, model, call, createSession } = await setup([
    { tool: 'sample_create', args }, { text: '将新建抽样层，请确认。' }, { text: '已抽样 2 条。' },
    { tool: 'sample_summary', args: { layer_id: SAMPLE_LAYER } }, { text: '已编码 1 条。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '抽 2 条编码翻译策略' })).text());
  const proposed = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([proposed.name, proposed.state], ['sample.create', 'needs_confirmation']);
  assert.deepEqual(proposed.confirm, {
    title: '抽样编码：新建抽样层「翻译策略抽样」', lines: ['查询式："翻译"', '范围：UD 中文', '抽样：2 条，seed 7', '标签集：翻译策略'],
  });
  assert.ok(!api.requests.some(r => r.path === `/projects/${PROJECT}/samples`), 'nothing is written before 执行');

  const confirmed = await confirmAll(call, session.id);
  assert.deepEqual(confirmed.filter(e => e.event === 'tool_result').map(e => [e.data.name, e.data.state, e.data.result_ref]),
    [['sample.create', 'succeeded', { kind: 'layer', id: SAMPLE_LAYER }]]);
  const request = api.requests.find(r => r.path === `/projects/${PROJECT}/samples`)!;
  assert.equal(request.headers.authorization, `Bearer ${AGENT_TOKEN}`);
  assert.deepEqual(request.body, { scope: { corpus_id: CORPUS }, query: '"翻译"', n: 2, seed: 7, layer: { name: '翻译策略抽样', label_set_id: 'ls-strategy' } });
  assert.equal(confirmedResults(model, 2)[0].sampled, 2);

  const summary = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '编码结果如何' })).text());
  assert.deepEqual(summary.filter(e => e.event === 'tool_result').map(e => [e.data.name, e.data.state, e.data.result_summary]),
    [['sample.summary', 'succeeded', '已编码 1 / 抽样 2']]);
  assert.deepEqual(toolResults(model, 4).at(-1).labels, SAMPLE_SUMMARY.labels);
});

test('sample.create without a label set fails before any proposal and lists the span label sets', async () => {
  const { api, call, createSession } = await setup([
    { tool: 'sample_create', args: { query: '"翻译"', n: 5, layer_name: '抽样' } }, { text: '需要标签集。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '抽 5 条' })).text());
  const result = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([result.name, result.state], ['sample.create', 'failed']);
  assert.match(result.result_summary, /LABEL_SET_REQUIRED.*翻译策略、偏误类型/);
  assert.ok(!api.requests.some(r => r.path === `/projects/${PROJECT}/samples`));
});

test('P8 write gate and system prompt rules', () => {
  assert.ok(CONFIRM_TOOLS.has('sample.create'));
  for (const name of ['methods.appendix', 'sample.summary', 'stats.translations', 'stats.breakdown']) assert.ok(!CONFIRM_TOOLS.has(name), name);
  const prompt = systemPrompt('UD 中文');
  assert.ok(prompt.includes('某词的译法、对应译文用 stats_translations'));
  assert.ok(prompt.includes('用 stats_breakdown'));
  assert.ok(prompt.includes('methods_appendix'));
  assert.ok(prompt.includes('不代写研究结论'));
  assert.ok(prompt.includes('抽样编码'));
  const catalog = componentCatalog();
  assert.match(catalog, /TranslationTable\(stat_id: string, query: string, measure: string, rows: /);
  assert.match(catalog, /BreakdownTable\(stat_id: string, query: string, by: string, rows: /);
});

// ---- P9 model usage, quota and concurrent runs (contracts/p9.md §二)

test('every model call writes an llm_usage row with the provider usage', async () => {
  const { store, call, createSession } = await setup([
    { tool: 'corpus_search', args: { query: '翻译' }, usage: { prompt_tokens: 1200, completion_tokens: 30, total_tokens: 1230 } },
    { text: '有 2 条命中。', usage: { prompt_tokens: 1400, completion_tokens: 12, total_tokens: 1412 } },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '找 翻译' })).text());
  assert.equal(events.at(-1)!.event, 'done');
  assert.deepEqual(store.usage.map(({ created_at: _at, ...row }) => row), [
    { user_id: USER.id, project_id: PROJECT, session_id: session.id, source: 'agent', model: 'fake-model', prompt_tokens: 1200, completion_tokens: 30, total_tokens: 1230 },
    { user_id: USER.id, project_id: PROJECT, session_id: session.id, source: 'agent', model: 'fake-model', prompt_tokens: 1400, completion_tokens: 12, total_tokens: 1412 },
  ]);
});

test('openai-responses usage is recorded from response.completed', async () => {
  const { store, call, createSession } = await setup([{ text: '好的。' }], { modelApi: 'openai-responses' });
  const session = await createSession();
  parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '你好' })).text());
  assert.deepEqual(store.usage.map(row => [row.source, row.prompt_tokens, row.completion_tokens, row.total_tokens]), [['agent', 8, 4, 12]]);
});

test('without usage the tokens are estimated as characters / 2; a failed request writes nothing', async () => {
  const { model, store, call, createSession } = await setup([{ text: '翻译腔是受源语影响的表达。' }, { status: 500 }, { status: 500 }, { status: 500 }]);
  const session = await createSession();
  parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '翻译腔是什么' })).text());
  assert.equal(store.usage.length, 1);
  const [row] = store.usage;
  assert.equal(row.source, 'agent:estimated');
  assert.equal(row.completion_tokens, Math.ceil('翻译腔是受源语影响的表达。'.length / 2));
  // the prompt carries the system prompt and the tool schemas: far more than the question
  const system = model.requests[0].body.messages[0].content as string;
  assert.ok(row.prompt_tokens >= Math.ceil(system.length / 2));
  assert.equal(row.total_tokens, row.prompt_tokens + row.completion_tokens);

  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '再说一次' })).text());
  assert.equal(events.at(-1)!.event, 'error');
  assert.equal(store.usage.length, 1);
});

test('LLM_QUOTA_EXCEEDED once the month total reaches the limit, for new messages and regenerate', async () => {
  const { store, call, createSession } = await setup(
    [{ text: '第一次回答。', usage: { prompt_tokens: 900, completion_tokens: 100, total_tokens: 1000 } }],
    { config: { monthlyTokensPerUser: 1000 } },
  );
  const session = await createSession();
  const first = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '你好' })).text());
  assert.equal(first.at(-1)!.event, 'done');
  for (const body of [{ content: '继续' }, { regenerate: true }]) {
    const response = await call('POST', `/agent/sessions/${session.id}/messages`, body);
    assert.equal(response.status, 429);
    assert.deepEqual(((await response.json()) as any).error, { code: 'LLM_QUOTA_EXCEEDED', message: '本月模型用量已达上限（1000 token），请联系管理员' });
  }
  // last month's usage does not count
  store.usage[0].created_at = new Date(new Date().getFullYear(), new Date().getMonth(), 0, 12);
  const again = await call('POST', `/agent/sessions/${session.id}/messages`, { content: '继续' });
  assert.equal(again.status, 200);
  await again.text();
});

test('TOO_MANY_RUNS for a third concurrent session; stopping one lets it start', async () => {
  const { model, call, createSession } = await setup([{ hang: true }, { hang: true }, { text: '第三个对话的回答。' }]);
  const [a, b, c] = [await createSession(), await createSession(), await createSession()];
  const bodyA = (await call('POST', `/agent/sessions/${a.id}/messages`, { content: '一' })).text();
  const bodyB = (await call('POST', `/agent/sessions/${b.id}/messages`, { content: '二' })).text();
  while (model.requests.length < 2) await new Promise(resolve => setTimeout(resolve, 10));

  const busy = await call('POST', `/agent/sessions/${c.id}/messages`, { content: '三' });
  assert.equal(busy.status, 429);
  assert.deepEqual(((await busy.json()) as any).error, { code: 'TOO_MANY_RUNS', message: '已有 2 个对话在运行，请等待完成或停止后再试' });
  // the per-session rule still comes first
  assert.equal((await call('POST', `/agent/sessions/${a.id}/messages`, { content: '再来' })).status, 409);

  assert.equal((await call('POST', `/agent/sessions/${a.id}/cancel`)).status, 204);
  assert.equal(parseSse(await bodyA).at(-1)!.data.message.stopped, true);
  const third = parseSse(await (await call('POST', `/agent/sessions/${c.id}/messages`, { content: '三' })).text());
  assert.equal(third.at(-1)!.event, 'done');
  assert.equal(third.at(-1)!.data.message.content, '第三个对话的回答。');

  await call('POST', `/agent/sessions/${b.id}/cancel`);
  await bodyB;
});

test('a deleted project (api 404) gives NOT_FOUND 项目不存在或已删除 on session routes', async () => {
  const { call } = await setup([]);
  const other = '55555555-5555-4555-8555-555555555555';
  for (const response of [await call('GET', `/agent/sessions?project_id=${other}`), await call('POST', '/agent/sessions', { project_id: other })]) {
    assert.equal(response.status, 404);
    assert.deepEqual(((await response.json()) as any).error, { code: 'NOT_FOUND', message: '项目不存在或已删除' });
  }
});

test('confirm execute is refused with LLM_QUOTA_EXCEEDED over the limit and nothing runs; decline still answers', async () => {
  const { api, call, createSession } = await setup(
    [
      { tool: 'evidence_add', args: { kind: 'text', ref: {}, text: '翻译是再创作。', source: '笔记' }, usage: { prompt_tokens: 500, completion_tokens: 20, total_tokens: 520 } },
      { text: '要把这句加入证据篮吗？', usage: { prompt_tokens: 560, completion_tokens: 10, total_tokens: 570 } },
    ],
    { config: { monthlyTokensPerUser: 1000 } },
  );
  const session = await createSession();
  parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '把这句放进证据篮' })).text());
  const [proposal] = await pending(call, session.id);
  const refused = await call('POST', `/agent/sessions/${session.id}/confirm`, { tool_call_ids: [proposal.id], action: 'execute' });
  assert.equal(refused.status, 429);
  assert.equal(((await refused.json()) as any).error.code, 'LLM_QUOTA_EXCEEDED');
  assert.ok(!api.requests.some(r => r.path === `/projects/${PROJECT}/evidence`));
  assert.equal((await pending(call, session.id)).length, 1, 'the card stays open');
  const declined = await call('POST', `/agent/sessions/${session.id}/confirm`, { tool_call_ids: [proposal.id], action: 'decline' });
  assert.equal(declined.status, 200);
});

// ---- P10 research tools, skills and components (contracts/p10.md §九)

test('P10 stats tools and search.semantic map their parameters onto the api bodies', async () => {
  const { api, model, call, createSession } = await setup([
    { tool: 'stats_text_metrics', args: { group_by: 'level' } },
    { tool: 'vocab_lists', args: {} },
    { tool: 'stats_vocab_profile', args: { list_id: 'vl-ngsl', by: 'document' } },
    { tool: 'stats_compare', args: { items: [{ label: 'big', query: '{lemma=big}' }, { label: 'large', query: '{lemma=large}', scope: { subcorpus_id: 'sub-1' } }], by: 'year', test: 'spearman' } },
    { tool: 'search_semantic', args: { text: '我喜欢读书' } },
    { text: '完成。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '研究' })).text());
  const results = events.filter(e => e.event === 'tool_result').map(e => e.data);
  assert.deepEqual(results.map(r => [r.name, r.state]), [
    ['stats.text_metrics', 'succeeded'], ['vocab.lists', 'succeeded'], ['stats.vocab_profile', 'succeeded'],
    ['stats.compare', 'succeeded'], ['search.semantic', 'succeeded'],
  ]);
  assert.equal(results[4].result_summary, '语义相近 25 句');

  const body = (path: string) => api.requests.find(r => r.path === path)!.body;
  assert.deepEqual(body('/stats/text_metrics'), { scope: { corpus_id: CORPUS }, group_by: 'level', sttr_window: 1000 });
  assert.deepEqual(body('/stats/vocab_profile'), { scope: { corpus_id: CORPUS }, list_id: 'vl-ngsl', by: 'document' });
  assert.deepEqual(body('/stats/compare'), {
    items: [{ label: 'big', scope: { corpus_id: CORPUS }, query: '{lemma=big}' }, { label: 'large', scope: { subcorpus_id: 'sub-1' }, query: '{lemma=large}' }],
    by: 'year', test: 'spearman',
  });
  assert.deepEqual(body('/search/semantic'), { scope: { corpus_id: CORPUS }, text: '我喜欢读书', top: 50 });
  assert.equal(api.requests.find(r => r.path === '/search/semantic')!.headers.authorization, `Bearer ${AGENT_TOKEN}`);

  const [, lists, , compare, semantic] = toolResults(model, 5);
  assert.deepEqual(lists.items.map((l: any) => [l.list_id, l.name, l.builtin, l.levels.length]), [['vl-ngsl', 'NGSL 1.2', true, 3], ['vl-hsk', 'HSK 3.0', false, 2]]);
  assert.equal(lists.items[0].license, VOCAB_LISTS[0].license);
  assert.equal(compare.stat_id, 'stat-cmp');
  assert.deepEqual(compare.rows[0].search_scope, { corpus_id: CORPUS, filter: { year: ['2001'] } });
  assert.equal(compare.rows[1].search_scope, undefined);
  assert.equal(compare.rows[0].search_query, '{lemma=big}');
  assert.equal(semantic.hits.length, 20);
  assert.deepEqual(semantic.hits[0], {
    hit_id: SEMANTIC_HITS[0].hit_id, sentence_index: 0, left: '', match: '我爱看书 0', right: '', source: '文档 0', score: 0.9,
  });
  assert.deepEqual(semantic.counts, { hits: 25, sentences: 25, documents: 3 });
  assert.equal(semantic.scope_name, 'UD 中文');
});

test('sketch_diff: each side keeps its most distinctive rows first and reports the full counts (B14)', async () => {
  // 17 rows favouring large (as big/large on UD EWT): the cap must drop the weakest, not the strongest
  const extra = Array.from({ length: 15 }, (_, i) => ({
    key: `b:w${i}`, values: { relation: 'amod', relation_label: '修饰', collocate: `w${i}`, freq_a: 0, freq_b: 2, diff: -(1 + i / 10), group: 'b' },
    search_query: `{lemma=big} {lemma=w${i}}`, search_query_b: `{lemma=large} {lemma=w${i}}`,
  }));
  const rows = SKETCH_DIFF_STAT.rows;
  SKETCH_DIFF_STAT.rows = [...rows, ...extra] as any;
  try {
    const { model, call, createSession } = await setup([
      { tool: 'stats_sketch_diff', args: { lemma_a: 'big', lemma_b: 'large' } },
      { text: '已对比。' },
    ]);
    const session = await createSession();
    await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '比较 big 和 large' })).text();
    const [sd] = toolResults(model, 1);
    assert.equal(sd.row_count, 5);
    assert.deepEqual(sd.side_totals, { a: 2, common: 1, b: 17 });
    assert.equal(sd.sides.b.length, 15);
    // B ascending by diff: number (−10.2) and scale (−5) lead, the two weakest extras are cut
    assert.deepEqual(sd.sides.b.slice(0, 3).map((r: any) => r.collocate), ['number', 'scale', 'w14']);
    assert.ok(!sd.sides.b.some((r: any) => r.collocate === 'w0' || r.collocate === 'w1'));
    // a B row opens B's search
    assert.equal(sd.sides.b.find((r: any) => r.collocate === 'w14').search_query, '{lemma=large} {lemma=w14}');
  } finally {
    SKETCH_DIFF_STAT.rows = rows;
  }
});

test('word_sketch groups rows by relation; sketch_diff splits the sides; WordSketch and SketchDiff blocks parse', async () => {
  const sketch = [
    'root = WordSketch("stat-ws", "make", relations, "VERB")',
    'relations = [{relation: "宾语", rows: [{collocate: "decision", freq: 40, logdice: 11, search_query: "{lemma=make} []{0,3} {lemma=decision}"}]}, {relation: "主语", rows: [{collocate: "we", freq: 9, logdice: 8.2}]}]',
  ].join('\n');
  const diff = [
    'root = SketchDiff("stat-sd", "big", "large", a, common, b, {dep: "layer-dep"})',
    'a = [{relation: "修饰", collocate: "deal", freq_a: 12, freq_b: 0, diff: 9.1, search_query: "{lemma=big} {lemma=deal}"}]',
    'common = [{relation: "修饰", collocate: "house", freq_a: 5, freq_b: 6, diff: -0.3, search_query: null}]',
    'b = [{relation: "修饰", collocate: "number", freq_a: 0, freq_b: 20, diff: -10.2}]',
  ].join('\n');
  const { api, model, call, createSession } = await setup([
    { tool: 'stats_word_sketch', args: { lemma: 'make', pos: 'VERB' } },
    { tool: 'stats_sketch_diff', args: { lemma_a: 'big', lemma_b: 'large', pos: 'ADJ' } },
    { text: `make 的宾语以 decision 最强。\n\n\`\`\`openui-lang\n${sketch}\n\`\`\`\n\n\`\`\`openui-lang\n${diff}\n\`\`\`\n` },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '比较 big 和 large 的用法' })).text());
  const results = events.filter(e => e.event === 'tool_result').map(e => e.data);
  assert.deepEqual(results.map(r => [r.name, r.state, r.result_ref?.id]), [['stats.word_sketch', 'succeeded', 'stat-ws'], ['stats.sketch_diff', 'succeeded', 'stat-sd']]);
  assert.equal(results[0].result_summary, 'Word Sketch：14 行');

  const body = (path: string) => api.requests.find(r => r.path === path)!.body;
  assert.deepEqual(body('/stats/word_sketch'), { scope: { corpus_id: CORPUS }, lemma: 'make', pos: 'VERB', min_freq: 2, top: 25 });
  assert.deepEqual(body('/stats/sketch_diff'), { scope: { corpus_id: CORPUS }, lemma_a: 'big', lemma_b: 'large', pos: 'ADJ', min_freq: 2, top: 25 });

  const [ws, sd] = toolResults(model, 2);
  assert.equal(ws.rows, undefined);
  // totals.relations order; a relation without rows is left out; at most 10 per relation
  assert.deepEqual(ws.relations.map((r: any) => [r.relation, r.rows.length]), [['宾语', 10], ['主语', 2]]);
  assert.deepEqual(ws.relations[0].rows[0], { collocate: 'decision', freq: 40, logdice: 11, search_query: '{lemma=make} []{0,3} {lemma=decision}' });
  assert.equal(ws.relations[1].rows[1].search_query, null);
  assert.deepEqual(Object.fromEntries(Object.entries(sd.sides).map(([side, rows]: [string, any]) => [side, rows.map((r: any) => r.collocate)])),
    { a: ['deal', 'size'], common: ['house'], b: ['number', 'scale'] });
  assert.deepEqual(sd.sides.a[0], {
    relation: '修饰', collocate: 'deal', freq_a: 12, freq_b: 0, logdice_a: 9.1, logdice_b: null, diff: 9.1, search_query: '{lemma=big} {lemma=deal}',
  });
  // the dependency layer of the sketch goes with the card, not with every row
  assert.deepEqual(sd.search_layers, { dep: 'layer-dep' });
  assert.equal(ws.search_layers, undefined);

  const parser = createParser(library.toJSONSchema());
  const blocks = events.at(-1)!.data.message.parts.filter((p: any) => p.type === 'ui').map((p: any) => parser.parse(p.lang).root as any);
  assert.deepEqual(blocks.map((b: any) => b?.typeName), ['WordSketch', 'SketchDiff']);
  assert.equal(blocks[0].props.pos, 'VERB');
  assert.equal(blocks[0].props.relations[0].rows[0].collocate, 'decision');
  assert.deepEqual([blocks[1].props.a[0].collocate, blocks[1].props.common[0].search_query, blocks[1].props.b[0].freq_b], ['deal', null, 20]);
  assert.deepEqual(blocks[1].props.layers, { dep: 'layer-dep' });
});

test('export.tidy needs confirmation, then posts the tidy export and returns the job', async () => {
  const { api, model, call, createSession } = await setup([
    { tool: 'export_tidy', args: { queries: ['"翻译"', '{lemma=译}'], metrics: true, format: 'xlsx' } },
    { text: '将导出整洁数据，请确认。' }, { text: '已提交导出。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '导出给 R 用的数据表' })).text());
  const proposed = events.find(e => e.event === 'tool_result')!.data;
  assert.deepEqual([proposed.name, proposed.state], ['export.tidy', 'needs_confirmation']);
  assert.deepEqual(proposed.confirm, { title: '导出整洁数据（XLSX）', lines: ['范围：UD 中文', '查询："翻译"；{lemma=译}', '附文本指标'] });
  assert.ok(!api.requests.some(r => r.path === '/stats/tidy_export'), 'nothing is exported before 执行');

  const confirmed = await confirmAll(call, session.id);
  assert.deepEqual(confirmed.filter(e => e.event === 'tool_result').map(e => [e.data.name, e.data.state, e.data.result_ref]),
    [['export.tidy', 'succeeded', { kind: 'job', id: 'job-tidy' }]]);
  assert.deepEqual(api.requests.find(r => r.path === '/stats/tidy_export')!.body, {
    scope: { corpus_id: CORPUS }, queries: ['"翻译"', '{lemma=译}'], metrics: true, format: 'xlsx',
  });
  const [result] = confirmedResults(model, 2);
  assert.deepEqual([result.job_id, result.kind, result.state], ['job-tidy', 'export', 'queued']);
});

test('research skills: five Pi skills load from services/agent/skills; every tool they name exists', () => {
  const { skills, diagnostics } = researchSkills();
  assert.deepEqual(diagnostics, []);
  assert.deepEqual(skills.map(s => s.name).sort(), ['keyword-analysis', 'learner-error-analysis', 'methods-section', 'synonym-comparison', 'translation-study']);
  const piNames = new Set(toolSpecs({ api: null as never, projectId: '', scope: null, jobPollMs: 0, jobWaitMs: 0 }).map(t => piName(t.name)));
  for (const skill of skills) {
    assert.ok(skill.description.trim().length > 10, skill.name);
    assert.equal(skill.disableModelInvocation, false);
    const { title, content } = readSkill(skill);
    assert.ok(title.length > 0);
    for (const heading of ['## 适用问题', '## 步骤', '## 工具与参数', '## 呈现', '## 口径与局限']) assert.ok(content.includes(heading), `${skill.name} ${heading}`);
    const named = content.match(/\b(?:corpora|corpus|subcorpora|stats|methods|sample|evidence|queries|export|jobs|annot|align|kb|vocab)_[a-z_]+\b/g) ?? [];
    assert.ok(named.length > 0, skill.name);
    for (const name of named) assert.ok(piNames.has(name), `${skill.name}: ${name}`);
  }
  assert.equal(findSkill(String.raw`C:\elsewhere\synonym-comparison.md`)?.name, 'synonym-comparison');
  assert.equal(findSkill('/etc/passwd'), undefined);
});

test('the system prompt lists the skills; read loads a skill file and refuses other files', async () => {
  const location = researchSkills().skills.find(s => s.name === 'synonym-comparison')!.filePath;
  const { model, call, createSession } = await setup([
    { tool: 'read', args: { path: location } },
    { tool: 'read', args: { path: '/etc/passwd' } },
    { text: '按近义词辨析流程进行。' },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '比较 big 和 large 的用法' })).text());
  const request = JSON.stringify(model.requests[0].body);
  assert.ok(request.includes('<available_skills>'));
  for (const name of ['keyword-analysis', 'synonym-comparison', 'translation-study', 'learner-error-analysis', 'methods-section']) assert.ok(request.includes(name), name);
  assert.ok(request.includes('先用 read 读取该流程文件'));
  const readTool = model.requests[0].body.tools.find((t: any) => t.function?.name === 'read');
  assert.match(readTool.function.description, /研究流程/);

  const results = events.filter(e => e.event === 'tool_result').map(e => e.data);
  assert.deepEqual(results.map(r => [r.name, r.state]), [['skills.read', 'succeeded'], ['skills.read', 'failed']]);
  assert.equal(results[0].result_summary, '研究流程：近义词辨析');
  assert.match(results[1].result_summary, /SKILL_NOT_FOUND/);
  const [skill] = toolResults(model, 1);
  assert.equal(skill.name, 'synonym-comparison');
  assert.match(skill.content, /stats_sketch_diff/);
  assert.ok(!skill.content.startsWith('---'), 'frontmatter stripped');
});

test('P10 components: catalog signatures, semantic KwicTable block, prompt rules and write gate', () => {
  const catalog = componentCatalog();
  assert.match(catalog, /WordSketch\(stat_id: string, lemma: string, relations: .*pos\?: string, layers\?: /);
  assert.match(catalog, /SketchDiff\(stat_id: string, lemma_a: string, lemma_b: string, a: .*common: .*b: .*layers\?: /);
  assert.match(catalog, /CompareChart\(stat_id: string, title: string, unit: string, categories: string\[\], series: .*chart: /);
  assert.match(catalog, /KwicTable\(search_id: string, .*rows: .*score\?: number.*mode\?: /);
  const parser = createParser(library.toJSONSchema());
  const card = parser.parse('root = KwicTable("", "我喜欢读书", "UD 中文", {hits: 2, sentences: 2, documents: 1}, [{hit_id: "doc0:0-6", left: "", match: "我爱看书", right: "", source: "文档 0", score: 0.9}], 2, "semantic")').root as any;
  assert.equal(card?.typeName, 'KwicTable');
  assert.equal(card.props.search_id, '');
  assert.equal(card.props.mode, 'semantic');
  assert.equal(card.props.rows[0].score, 0.9);
  const chart = parser.parse('root = CompareChart("stat-cmp", "big / large", "每百万词", ["2001", "2002"], [{name: "big", values: [120.5, 98]}, {name: "large", values: [80, null]}], "line")').root as any;
  assert.equal(chart?.typeName, 'CompareChart');
  assert.deepEqual(chart.props.series[1].values, [80, null]);

  assert.ok(CONFIRM_TOOLS.has('export.tidy'));
  for (const name of ['stats.text_metrics', 'vocab.lists', 'stats.vocab_profile', 'stats.compare', 'stats.word_sketch', 'stats.sketch_diff', 'search.semantic', 'skills.read']) {
    assert.ok(!CONFIRM_TOOLS.has(name), name);
  }
  const prompt = systemPrompt('UD 中文');
  for (const text of ['stats_word_sketch 用 WordSketch', 'stats_sketch_diff 用 SketchDiff', 'CompareChart', 'search_semantic 用 KwicTable', '近义词辨析', '数字只来自工具结果', '不代写研究结论']) {
    assert.ok(prompt.includes(text), text);
  }
});

test('model 503 twice then an answer: the run succeeds, Retry-After is waited, usage is recorded once', async () => {
  const { model, store, call, createSession } = await setup([
    { status: 503, retryAfter: '1' }, { status: 503 }, { text: '好的。', usage: { prompt_tokens: 10, completion_tokens: 2, total_tokens: 12 } },
  ]);
  const session = await createSession();
  const events = parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '你好' })).text());
  assert.equal(events.at(-1)!.event, 'done', JSON.stringify(events.at(-1)));
  assert.equal(model.requests.length, 3);
  assert.ok(model.requests[1].at - model.requests[0].at >= 900, 'waited for Retry-After: 1');
  assert.equal(store.usage.length, 1);
  assert.equal(store.usage[0].total_tokens, 12);
});

test('corpus.parse sends the session scope, or the scope given', async () => {
  const { api, call, createSession } = await setup([
    { tool: 'corpus_parse', args: { query: '翻译/v' } },
    { tool: 'corpus_parse', args: { query: '翻译/v', scope: { subcorpus_id: 'sub-1' } } },
    { text: '语法正确。' },
  ]);
  const session = await createSession();
  parseSse(await (await call('POST', `/agent/sessions/${session.id}/messages`, { content: '检查' })).text());
  const bodies = api.requests.filter(r => r.path === '/search/parse').map(r => r.body);
  assert.deepEqual(bodies, [{ query: '翻译/v', scope: { corpus_id: CORPUS } }, { query: '翻译/v', scope: { subcorpus_id: 'sub-1' } }]);
});
