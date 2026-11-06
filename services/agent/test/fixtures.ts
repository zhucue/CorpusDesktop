/** Loopback fakes: an OpenAI-compatible SSE model server, the business api, and an in-memory store. */
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { randomUUID } from 'node:crypto';
import { mkdirSync, mkdtempSync } from 'node:fs';
import { join } from 'node:path';
import type { AddressInfo } from 'node:net';
import type { Config } from '../src/config.ts';
import type { SessionRecord, Store, UsageRow } from '../src/store.ts';
import type { Message, Part, Scope, Session, ToolCall } from '../src/types.ts';

export const PROJECT = '11111111-1111-4111-8111-111111111111';
export const CORPUS = '22222222-2222-4222-8222-222222222222';
/** A built-in corpus (project_id null): the assistant never builds layers on it. */
export const BUILTIN_CORPUS = '44444444-4444-4444-8444-444444444444';
export const USER = { id: '33333333-3333-4333-8333-333333333333', email: 'r@example.edu', display_name: '研究生', is_admin: false };
export const COOKIE = 'corpus_session=good';
export const ORIGIN = 'http://localhost:8080';
export const AGENT_TOKEN = 'agent-token-1';
export const MODEL_KEY = 'model-key-1';

async function readBody(request: IncomingMessage): Promise<string> {
  let text = '';
  for await (const chunk of request) text += String(chunk);
  return text;
}

async function listen(server: ReturnType<typeof createServer>) {
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = (server.address() as AddressInfo).port;
  return {
    url: `http://127.0.0.1:${port}`,
    close: async () => { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); },
  };
}

// ---------------------------------------------------------------- model server

/** OpenAI chat usage; openai-completions sends it as the last chunk only when given (the responses fake always reports 8/4/12). */
export type Usage = { prompt_tokens: number; completion_tokens: number; total_tokens: number };
type Answer = ({ text: string; thinking?: string } | { tool: string; args: Record<string, unknown> }) & { usage?: Usage };
export type Reply = Answer | { status: number } | { hang: true };

function writeReply(response: ServerResponse, api: string, reply: Answer) {
  response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
  const emit = (value: unknown) => response.write(`data: ${JSON.stringify(value)}\n\n`);
  const id = 'call_' + randomUUID().replaceAll('-', '');
  // Small uneven chunks exercise the fence splitter across delta boundaries.
  const pieces = (text: string) => text.match(/[\s\S]{1,7}/g) ?? [];
  if (api === 'openai-completions') {
    const chunk = (delta: unknown, finish_reason: string | null = null) => emit({
      id: 'chatcmpl_test', object: 'chat.completion.chunk', created: 1, model: 'fake-model',
      choices: [{ index: 0, delta, finish_reason }],
    });
    chunk({ role: 'assistant' });
    if ('text' in reply) {
      for (const piece of pieces(reply.thinking ?? '')) chunk({ reasoning_content: piece });
      for (const piece of pieces(reply.text)) chunk({ content: piece });
      chunk({}, 'stop');
    } else {
      const args = JSON.stringify(reply.args);
      const split = Math.floor(args.length / 2);
      chunk({ tool_calls: [{ index: 0, id, type: 'function', function: { name: reply.tool, arguments: args.slice(0, split) } }] });
      chunk({ tool_calls: [{ index: 0, function: { arguments: args.slice(split) } }] });
      chunk({}, 'tool_calls');
    }
    if (reply.usage) emit({ id: 'chatcmpl_test', object: 'chat.completion.chunk', created: 1, model: 'fake-model', choices: [], usage: reply.usage });
    response.end('data: [DONE]\n\n');
    return;
  }
  emit({ type: 'response.created', response: { id: 'resp_' + id, status: 'in_progress', output: [] } });
  let item;
  if ('text' in reply) {
    item = { type: 'message', id: 'msg_' + id, role: 'assistant', status: 'completed', content: [{ type: 'output_text', text: reply.text, annotations: [] }] };
    emit({ type: 'response.output_item.added', output_index: 0, item: { ...item, content: [] } });
    emit({ type: 'response.content_part.added', item_id: item.id, output_index: 0, content_index: 0, part: { type: 'output_text', text: '', annotations: [] } });
    for (const piece of pieces(reply.text)) emit({ type: 'response.output_text.delta', item_id: item.id, output_index: 0, content_index: 0, delta: piece });
  } else {
    const args = JSON.stringify(reply.args);
    item = { type: 'function_call', id: 'fc_' + id, call_id: id, name: reply.tool, arguments: args, status: 'completed' };
    emit({ type: 'response.output_item.added', output_index: 0, item: { ...item, arguments: '', status: 'in_progress' } });
    emit({ type: 'response.function_call_arguments.delta', output_index: 0, item_id: item.id, delta: args });
    emit({ type: 'response.function_call_arguments.done', output_index: 0, item_id: item.id, arguments: args });
  }
  emit({ type: 'response.output_item.done', output_index: 0, item });
  emit({ type: 'response.completed', response: { id: 'resp_' + id, status: 'completed', output: [item], usage: { input_tokens: 8, output_tokens: 4, total_tokens: 12 } } });
  response.end();
}

/** Replies are consumed in order, one per model request. */
export async function fakeModel(api: string, replies: Reply[]) {
  const requests: any[] = [];
  const server = createServer(async (request, response) => {
    const body = JSON.parse(await readBody(request));
    requests.push({ body, authorization: request.headers.authorization });
    if (request.headers.authorization !== `Bearer ${MODEL_KEY}`) {
      response.writeHead(401, { 'Content-Type': 'application/json' }).end(JSON.stringify({ error: { message: 'bad key' } }));
      return;
    }
    const reply = replies[requests.length - 1] ?? { text: '（无更多脚本回复）' };
    if ('status' in reply) { response.writeHead(reply.status, { 'Content-Type': 'application/json' }).end('{"error":{"message":"x"}}'); return; }
    if ('hang' in reply) return; // never answers; the client aborts
    writeReply(response, api, reply);
  });
  const handle = await listen(server);
  return { ...handle, url: `${handle.url}/v1`, requests };
}

// ---------------------------------------------------------------- api server

export interface ApiRequest { method: string; path: string; headers: IncomingMessage['headers']; body: any }

export const HITS = [
  { hit_id: 'doc1:10-12', document_id: 'doc1', document_title: '新闻 01', sentence_index: 3, left: '他们决定', match: '翻译', right: '这本书。', start_cp: 10, end_cp: 12, metadata: {}, aligned: [] },
  { hit_id: 'doc2:4-6', document_id: 'doc2', document_title: '小说 07', sentence_index: 0, left: '请', match: '翻译', right: '成英文。', start_cp: 4, end_cp: 6, metadata: {}, aligned: [{ language: 'en', text: 'Please translate it.' }] },
];

export const DEP_LAYER = 'layer-dep';
export const LABEL_SETS = [
  { id: 'ls-upos', project_id: null, name: 'upos', kind: 'pos', language: null, labels: [] },
  { id: 'ls-jieba', project_id: null, name: 'jieba', kind: 'pos', language: 'zh', labels: [] },
  { id: 'ls-deprel', project_id: null, name: 'ud-deprel', kind: 'dep', language: null, labels: [] },
  { id: 'ls-strategy', project_id: PROJECT, name: '翻译策略', kind: 'span', language: null, labels: [] },
  { id: 'ls-error', project_id: PROJECT, name: '偏误类型', kind: 'span', language: null, labels: [] },
];
const layer = (id: string, kind: string, name: string, status: string) => ({
  id, project_id: PROJECT, corpus_id: CORPUS, corpus_name: 'UD 中文', kind, name, label_set_id: kind === 'dep' ? 'ls-deprel' : 'ls-jieba',
  source_model: kind === 'dep' ? 'stanza 1.9 zh' : 'jieba 0.42', status, job_id: null,
  progress: { total: 4, suggested: 3, confirmed: 0, modified: 1, rejected: 0 }, documents: { total: 1, done: status === 'ready' ? 1 : 0 },
  error: null, created_by: USER.id, created_at: '2026-10-27T00:00:00Z', updated_at: '2026-10-27T00:00:00Z',
});
/** 他们 翻译 这本书 。 — token 2 (翻译) is root; the reviewer moved 这本书 from nmod to obj. */
export const SENTENCE = {
  document_id: 'doc1', sentence_index: 3, text: '他们翻译这本书。', status: 'pending',
  tokens: [
    { index: 1, form: '他们', start_cp: 0, end_cp: 2, system: { pos: 'r', head: 2, deprel: 'nsubj' } },
    { index: 2, form: '翻译', start_cp: 2, end_cp: 4, system: { pos: 'v', head: 0, deprel: 'root' } },
    { index: 3, form: '这本书', start_cp: 4, end_cp: 7, system: { pos: 'n', head: 2, deprel: 'nmod' } },
    { index: 4, form: '。', start_cp: 7, end_cp: 8, system: { pos: 'x', head: 2, deprel: 'punct' } },
  ],
  annotations: [
    { id: 'a3', token_index: 3, label: 'obj', head: 2, model_label: 'nmod', model_head: 2, source: `human:${USER.id}`, status: 'modified', revision: 2, updated_by: USER.id, updated_at: '2026-10-27T00:00:00Z' },
    { id: 'a4', token_index: 4, label: 'punct', head: 2, model_label: 'punct', model_head: 2, source: 'model:stanza-zh', status: 'suggested', revision: 1, updated_by: null, updated_at: '2026-10-27T00:00:00Z' },
  ],
};

/** Layer documents in corpus order: document_ordinal 2 → doc1. */
export const LAYER_DOCS = [
  { document_id: 'doc0', title: '前言', sentences: 5, done: 5, pending: 0 },
  { document_id: 'doc1', title: '新闻 01', sentences: 12, done: 3, pending: 9 },
];

// ---- P4 knowledge base fixtures (contracts/p4.md §四)
export const TERM = {
  id: 'term-1', project_id: PROJECT, term: '翻译腔', language: 'zh', translations: [{ language: 'en', text: 'translationese' }],
  definition: '译文受源语影响而显得不自然的语言特征。', domain: '翻译学',
  examples: [{ text: '这种翻译腔在早期译本中很常见。', source: '文献：翻译腔研究 p.3', document_id: 'kb-doc-1' }],
  source: 'manual', status: 'confirmed', created_by: USER.id, confirmed_by: USER.id,
  created_at: '2026-10-20T00:00:00Z', updated_at: '2026-10-20T00:00:00Z',
};
export const LONG_CHUNK = '翻译腔'.repeat(250); // 750 chars, clipped to 600
export const KB_SEARCH = {
  items: [
    {
      chunk: { id: 'chunk-1', document_id: 'kb-doc-1', ordinal: 2, text: '翻译腔指译文中受源语结构影响的表达。', locator: { page: 3 } },
      document: { id: 'kb-doc-1', title: '翻译腔研究', kind: 'literature', source: 'translationese.pdf' }, score: 0.91, highlight: '翻译腔',
    },
    {
      chunk: { id: 'chunk-2', document_id: 'kb-doc-2', ordinal: 0, text: LONG_CHUNK, locator: { heading_path: ['标注规范', '词性'] } },
      document: { id: 'kb-doc-2', title: '标注规范', kind: 'guideline', source: null }, score: 0.5, highlight: '',
    },
  ],
  terms: [TERM],
};
const draftTerms = Array.from({ length: 25 }, (_, i) => ({
  ...TERM, id: `draft-${i}`, term: `候选${i}`, source: 'corpus', status: 'draft', confirmed_by: null,
  created_at: `2026-10-27T00:00:${String(i).padStart(2, '0')}Z`,
}));

// ---- P5 spans, alignment, agreement fixtures (contracts/p5.md §三)
export const SPAN_LAYER = 'layer-span';
export const ALIGN_LAYER = 'layer-align';
/** doc1 sentence 3 starts at code point 100. */
export const SPAN_SENTENCE = {
  document_id: 'doc1', sentence_index: 3, text: '他们翻译这本书。', start_cp: 100, end_cp: 108,
  spans: [
    { id: 'span-1', start_cp: 102, end_cp: 104, text: '翻译', label: '直译', attrs: {}, source: `human:${USER.id}`, status: 'confirmed', model_label: null, revision: 1, annotator_id: USER.id, updated_at: '2026-10-27T00:00:00Z' },
    { id: 'span-2', start_cp: 104, end_cp: 107, text: '这本书', label: '增译', attrs: { note: '量词' }, source: 'model:fake-model', status: 'suggested', model_label: '增译', revision: 1, annotator_id: USER.id, updated_at: '2026-10-27T00:00:00Z' },
  ],
  relations: [
    { id: 'rel-1', from_span_id: 'span-2', to_span_id: 'span-1', label: 'cause', source: `human:${USER.id}`, status: 'confirmed', revision: 1, annotator_id: USER.id },
  ],
};
export const ALIGN_PAGE = {
  items: [{
    src: { document_id: 'src-doc', sentence_index: 0, text: 'He translated the book.', tokens: [
      { index: 1, form: 'He' }, { index: 2, form: 'translated' }, { index: 3, form: 'the' }, { index: 4, form: 'book' }, { index: 5, form: '.' }] },
    tgt: { document_id: 'tgt-doc', sentence_index: 0, text: '他翻译了这本书。', tokens: ['他', '翻译', '了', '这本书', '。'] },
    alignments: [
      { id: 'al-1', level: 'word', src_tokens: [1], tgt_tokens: [1], score: 0.9, source: 'model:fake-model', status: 'confirmed', revision: 1, annotator_id: USER.id },
      { id: 'al-2', level: 'word', src_tokens: [3, 4], tgt_tokens: [4], score: null, source: 'model:fake-model', status: 'suggested', revision: 1, annotator_id: USER.id },
    ],
  }],
  next_cursor: 'src-doc:0',
};
export const AGREEMENT = {
  annotators: [{ user_id: USER.id, email: USER.email, done: 50 }, { user_id: 'u2', email: 'b@example.edu', done: 50 }],
  pairwise: [{ a: USER.id, b: 'u2', kappa: 0.72, n: 50 }], alpha: 0.71, per_label: [{ label: '直译', kappa: 0.8 }],
};
export const DISAGREEMENTS = Array.from({ length: 12 }, (_, i) => ({
  target_kind: 'span', target_key: `doc1:${i}:0-2`, document_id: 'doc1', sentence_index: i,
  values: [{ annotator_id: USER.id, label: '直译' }, { annotator_id: 'u2', label: '意译' }],
}));

// ---- P8 translations, breakdown, method appendix, samples (contracts/p8.md)
const STAT_OF_JOB: Record<string, string> = {
  'job-translations': 'stat-tr', 'job-breakdown': 'stat-bd', 'job-word_sketch': 'stat-ws', 'job-sketch_diff': 'stat-sd', 'job-compare': 'stat-cmp',
};
const statBase = (id: string, method: string) => ({
  id, project_id: PROJECT, method, params: {}, scope: { corpus_id: CORPUS, subcorpus_id: null, name: 'UD 中文' },
  index_version: 'v1', created_at: '2026-11-05T00:00:00Z',
});
export const TRANSLATION_STAT = {
  ...statBase('stat-tr', 'translations'),
  totals: { tokens: 1000, sentences: 80, documents: 5, hit_sentences: 70, aligned_sentences: 66, unaligned: 4 },
  columns: [{ key: 'item', label: '译文词', type: 'string' }, { key: 'cooc', label: '共现句数', type: 'number' }, { key: 'dice', label: 'Dice', type: 'number' }],
  rows: Array.from({ length: 55 }, (_, i) => {
    const word = i === 0 ? 'translate' : `t${i}`;
    return {
      key: word, values: { item: word, cooc: 55 - i, pct: i === 0 ? 78.6 : 1, target_freq: 120, dice: 0.9 - i / 100, ll: i === 0 ? 30.5 : 1 },
      search_query: '"翻译"', search_aligned: { op: '+', query: `"${word}"` }, search_scope: { corpus_id: CORPUS, subcorpus_id: null },
    };
  }),
  row_count: 55,
};
export const BREAKDOWN_STAT = {
  ...statBase('stat-bd', 'breakdown'),
  totals: { tokens: 1000, sentences: 80, documents: 5, hits: 12 },
  columns: [{ key: 'item', label: '项', type: 'string' }, { key: 'hits', label: '命中数', type: 'number' }],
  rows: [
    { key: '2001', values: { item: '2001', hits: 7 }, search_query: '翻译', search_scope: { corpus_id: CORPUS, filter: { year: ['2001'] } } },
    { key: '（无）', values: { item: '（无）', hits: 5 }, search_query: null, search_scope: { corpus_id: CORPUS } },
  ],
  row_count: 2,
};
export const APPENDIX = { markdown: '## 语料\n\nUD 中文，1000 词。\n\n## 统计\n\nlogDice（Rychlý 2008）。', citations: ['Rychlý P. A lexicographer-friendly association score[C]. 2008.'] };
export const SAMPLE_LAYER = 'layer-sample';
export const SAMPLE_SUMMARY = {
  total_hits: 2, sampled: 2, coded: 1, rejected: 0,
  labels: [{ label: '直译', count: 1, pct: 100, ci_low: 20.65, ci_high: 100, estimate: 2 }],
};

// ---- P10 research tools (contracts/p10.md)
export const WORD_SKETCH_STAT = {
  ...statBase('stat-ws', 'word_sketch'),
  totals: { lemma: 'make', node_freq: 300, relations: [{ key: 'obj', label: '宾语', freq: 200, rows: 12 }, { key: 'nsubj', label: '主语', freq: 14, rows: 2 }, { key: 'pp:with', label: 'with + N', freq: 0, rows: 0 }] },
  columns: [{ key: 'relation', label: '关系', type: 'string' }, { key: 'collocate', label: '搭配词', type: 'string' }, { key: 'freq', label: '频次', type: 'number' }, { key: 'logdice', label: 'logDice', type: 'number' }],
  // 12 objects, 2 subjects; the third relation has no rows
  rows: [
    ...Array.from({ length: 12 }, (_, i) => {
      const word = i ? `w${i}` : 'decision';
      return {
        key: `obj	${word}`, values: { relation: 'obj', relation_label: '宾语', collocate: word, freq: 40 - i, coll_freq: 90, logdice: 11 - i / 10 },
        search_query: i ? null : '{lemma=make} []{0,3} {lemma=decision}',
      };
    }),
    { key: 'nsubj	we', values: { relation: 'nsubj', relation_label: '主语', collocate: 'we', freq: 9, coll_freq: 50, logdice: 8.2 }, search_query: '{lemma=we} {lemma=make}' },
    { key: 'nsubj	they', values: { relation: 'nsubj', relation_label: '主语', collocate: 'they', freq: 5, coll_freq: 40, logdice: 7.1 }, search_query: null },
  ],
  row_count: 14,
};
export const SKETCH_DIFF_STAT = {
  ...statBase('stat-sd', 'sketch_diff'),
  totals: { lemma_a: 'big', lemma_b: 'large', relations: [{ key: 'amod', label: '修饰', freq_a: 18, freq_b: 35, rows: 5 }] },
  columns: [{ key: 'collocate', label: '搭配词', type: 'string' }, { key: 'diff', label: '差', type: 'number' }],
  rows: [
    { key: 'a:deal', values: { relation: 'amod', relation_label: '修饰', collocate: 'deal', freq_a: 12, freq_b: 0, logdice_a: 9.1, logdice_b: null, diff: 9.1, group: 'a' }, search_query: '{lemma=big} {lemma=deal}', search_layers: { dep: 'layer-dep' } },
    { key: 'c:house', values: { relation: 'amod', relation_label: '修饰', collocate: 'house', freq_a: 5, freq_b: 6, logdice_a: 7.2, logdice_b: 7.5, diff: -0.3, group: 'common' }, search_query: null },
    { key: 'b:number', values: { relation: 'amod', relation_label: '修饰', collocate: 'number', freq_a: 0, freq_b: 20, logdice_a: 0, logdice_b: 10.2, diff: -10.2, group: 'b' }, search_query: '{lemma=large} {lemma=number}' },
    { key: 's:scale', values: { relation: 'amod', relation_label: '修饰', collocate: 'scale', freq_a: 1, freq_b: 9, logdice_a: 3, logdice_b: 8, diff: -5, group: 'b' }, search_query: null },
    { key: 'amod	size', values: { relation: 'amod', relation_label: '修饰', collocate: 'size', freq_a: 3, freq_b: 0, logdice_a: 5, logdice_b: null, diff: 5 }, search_query: null },
  ],
  row_count: 5,
};
export const COMPARE_STAT = {
  ...statBase('stat-cmp', 'compare'),
  totals: { tokens: 1000, sentences: 80, documents: 5 },
  columns: [{ key: 'item', label: '字段值', type: 'string' }, { key: 'big', label: 'big', type: 'number' }, { key: 'large', label: 'large', type: 'number' }],
  rows: [
    { key: '2001', values: { item: '2001', big: 120.5, large: 80 }, search_query: '{lemma=big}', search_scope: { corpus_id: CORPUS, filter: { year: ['2001'] } } },
    { key: '2002', values: { item: '2002', big: 98, large: 101.2 }, search_query: '{lemma=big}', search_scope: { corpus_id: CORPUS } },
  ],
  row_count: 2,
};
export const VOCAB_LISTS = [
  { id: 'vl-ngsl', project_id: null, name: 'NGSL 1.2', language: 'en', levels: ['1', '2', '3'], source: 'Browne et al.', license: 'CC BY-SA 4.0', created_by: null, created_at: '2026-11-05T00:00:00Z' },
  { id: 'vl-hsk', project_id: PROJECT, name: 'HSK 3.0', language: 'zh', levels: ['HSK1', 'HSK2'], source: '用户上传', license: null, created_by: USER.id, created_at: '2026-11-05T00:00:00Z' },
];
export const SEMANTIC_HITS = Array.from({ length: 25 }, (_, i) => ({
  hit_id: `doc${i % 3}:0-6`, document_id: `doc${i % 3}`, document_title: `文档 ${i % 3}`, sentence_index: i, left: '', match: `我爱看书 ${i}`, right: '',
  start_cp: 0, end_cp: 6, metadata: {}, aligned: [], score: 0.9 - i / 100,
}));

export async function fakeApi(options: { statJobState?: 'succeeded' | 'running' } = {}) {
  const requests: ApiRequest[] = [];
  const jobPolls = new Map<string, number>();
  let jobPolled: () => void = () => {};
  const firstJobPoll = new Promise<void>(resolve => { jobPolled = resolve; });
  /** What /auth/me returns; tests flip must_change_password. */
  const me: typeof USER & { must_change_password?: boolean } = { ...USER };
  const json = (response: ServerResponse, status: number, value: unknown) =>
    response.writeHead(status, { 'Content-Type': 'application/json' }).end(JSON.stringify(value));
  const fail = (response: ServerResponse, status: number, code: string) => json(response, status, { error: { code, message: code } });

  const server = createServer(async (request, response) => {
    const url = new URL(request.url!, 'http://x');
    const text = await readBody(request);
    const body = text ? JSON.parse(text) : null;
    const path = url.pathname.replace(/^\/api/, '');
    requests.push({ method: request.method!, path: path + url.search, headers: request.headers, body });
    const cookieOk = request.headers.cookie === COOKIE;
    const bearerOk = request.headers.authorization === `Bearer ${AGENT_TOKEN}`;

    if (path === '/auth/me') return cookieOk ? json(response, 200, me) : fail(response, 401, 'AUTH_REQUIRED');
    if (path === '/auth/agent-token' && request.method === 'POST') {
      if (!cookieOk) return fail(response, 401, 'AUTH_REQUIRED');
      if (request.headers.origin !== ORIGIN) return fail(response, 403, 'ORIGIN_REJECTED');
      if (body?.project_id !== PROJECT) return fail(response, 403, 'FORBIDDEN');
      return json(response, 200, { token: AGENT_TOKEN, expires_at: new Date(Date.now() + 1800e3).toISOString() });
    }
    if (path === `/projects/${PROJECT}` && cookieOk) return json(response, 200, { id: PROJECT, name: '毕业论文', role: 'owner' });
    if (path.startsWith('/projects/') && cookieOk) return fail(response, 404, 'NOT_FOUND');
    if (!bearerOk) return fail(response, 401, 'AUTH_REQUIRED');

    if (path === `/corpora/${CORPUS}`) return json(response, 200, { id: CORPUS, name: 'UD 中文', language: 'zh', status: 'ready' });
    if (path === `/corpora/${BUILTIN_CORPUS}`) {
      return json(response, 200, { id: BUILTIN_CORPUS, project_id: null, name: 'UD 中文 GSD', language: 'zh', status: 'ready', stats: { documents: 1, sentences: 4997, tokens: 111279 } });
    }
    // system tokens of a built-in UD sentence, no layer (corpus.sentence)
    if (path === `/corpora/${BUILTIN_CORPUS}/documents`) return json(response, 200, { items: [{ id: 'gsd-train', title: 'zh_gsd-ud-train', sentences: 3997 }], total: 1 });
    if (path === `/corpora/${BUILTIN_CORPUS}/documents/gsd-train/sentences/0`) {
      return json(response, 200, {
        document_id: 'gsd-train', sentence_index: 0, text: '他們翻譯這本書。', start_cp: 0, end_cp: 8,
        tokens: [
          { index: 1, form: '他們', pos: 'PRON', lemma: null, head: 2, deprel: 'nsubj' },
          { index: 2, form: '翻譯', pos: 'VERB', lemma: null, head: 0, deprel: 'root' },
          { index: 3, form: '這本書', pos: 'NOUN', lemma: null, head: 2, deprel: 'obj' },
          { index: 4, form: '。', pos: 'PUNCT', lemma: null, head: 2, deprel: 'punct' },
        ],
      });
    }
    if (path === '/search' && request.method === 'POST') {
      return json(response, 200, {
        search_id: 'search-1', parse: { ok: true }, counts: { hits: 2, sentences: 2, documents: 2, complete: true },
        items: HITS, page: 1, page_size: 20,
      });
    }
    const statJob = /^\/stats\/(frequency|ngrams|collocations|keywords|distribution|breakdown|translations|text_metrics|vocab_profile|compare|word_sketch|sketch_diff)$/.exec(path);
    if (statJob && request.method === 'POST') {
      return json(response, 200, { id: `job-${statJob[1]}`, project_id: PROJECT, kind: 'stats', state: 'queued', progress: { done: 0, total: null, message: '' }, result: null, error: null });
    }
    // ---- P4 knowledge base (contracts/p4.md §四)
    if (path === `/projects/${PROJECT}/kb/search` && request.method === 'POST') {
      const ids: string[] | undefined = body.document_ids;
      return json(response, 200, ids ? { ...KB_SEARCH, items: KB_SEARCH.items.filter(item => ids.includes(item.document.id)) } : KB_SEARCH);
    }
    if (path === `/projects/${PROJECT}/kb/documents` && request.method === 'POST') {
      return json(response, 201, {
        id: 'note-1', project_id: PROJECT, kind: body.kind, title: body.title, source: null, meta: {}, status: 'ready', error: null,
        chunk_count: 0, created_by: USER.id, created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
      });
    }
    if (path === '/kb/documents/note-1/refs' && request.method === 'POST') return json(response, 201, { note_id: 'note-1', ...body });
    if (path === `/projects/${PROJECT}/kb/terms/extract` && request.method === 'POST') {
      return json(response, 200, { id: 'job-kbextract', project_id: PROJECT, kind: 'kb_extract', state: 'queued', progress: null, result: null, error: null });
    }
    if (path === '/jobs/job-kbextract') {
      const polls = (jobPolls.get('job-kbextract') ?? 0) + 1;
      jobPolls.set('job-kbextract', polls);
      const done = polls >= 2;
      return json(response, 200, {
        id: 'job-kbextract', project_id: PROJECT, kind: 'kb_extract', state: done ? 'succeeded' : 'running',
        progress: { done: done ? 1 : 0, total: 1, message: '' }, result: done ? { created: 25, skipped: 3 } : null, error: null,
      });
    }
    if (path === `/projects/${PROJECT}/kb/terms` && request.method === 'GET') {
      const status = url.searchParams.get('status');
      return json(response, 200, status === 'draft' ? draftTerms : [TERM]);
    }
    if (path === `/projects/${PROJECT}/layers` && request.method === 'GET') return json(response, 200, [layer(DEP_LAYER, 'dep', '依存', 'ready')]);
    if (path === `/layers/${DEP_LAYER}/documents`) return json(response, 200, { items: LAYER_DOCS, total: LAYER_DOCS.length });
    const job = /^\/jobs\/(job-\w+)$/.exec(path);
    if (job) {
      const polls = (jobPolls.get(job[1]) ?? 0) + 1;
      jobPolls.set(job[1], polls);
      jobPolled();
      const done = options.statJobState !== 'running' && polls >= 2;
      return json(response, 200, {
        id: job[1], project_id: PROJECT, kind: 'stats', state: done ? 'succeeded' : 'running',
        progress: { done: done ? 1 : 0, total: 1, message: '' }, result: done ? { stat_id: STAT_OF_JOB[job[1]] ?? 'stat-1' } : null, error: null,
      });
    }
    if (path === '/stats/stat-1') {
      return json(response, 200, {
        id: 'stat-1', project_id: PROJECT, method: 'collocations', params: {}, scope: { corpus_id: CORPUS, subcorpus_id: null, name: 'UD 中文' },
        index_version: 'v1', totals: { tokens: 1000, sentences: 80, documents: 5 }, created_at: new Date().toISOString(),
        columns: [{ key: 'collocate', label: '搭配词', type: 'string' }, { key: 'cooc', label: '共现频次', type: 'number' }, { key: 'logdice', label: 'logDice', type: 'number' }],
        rows: Array.from({ length: 60 }, (_, i) => ({ key: `w${i}`, values: { collocate: `w${i}`, cooc: 60 - i, logdice: 10 - i / 10 }, search_query: null, search_scope: { corpus_id: CORPUS } })),
        row_count: 60,
      });
    }
    if (path === '/stats/stat-tr') return json(response, 200, TRANSLATION_STAT);
    if (path === '/stats/stat-bd') return json(response, 200, BREAKDOWN_STAT);
    if (path === '/stats/stat-ws') return json(response, 200, WORD_SKETCH_STAT);
    if (path === '/stats/stat-sd') return json(response, 200, SKETCH_DIFF_STAT);
    if (path === '/stats/stat-cmp') return json(response, 200, COMPARE_STAT);
    if (path === `/projects/${PROJECT}/vocab-lists` && request.method === 'GET') return json(response, 200, VOCAB_LISTS);
    if (path === '/search/semantic' && request.method === 'POST') return json(response, 200, { items: SEMANTIC_HITS.slice(0, body.top) });
    if (path === '/stats/tidy_export' && request.method === 'POST') {
      return json(response, 200, { id: 'job-tidy', project_id: PROJECT, kind: 'export', state: 'queued', progress: { done: 0, total: null, message: '' }, result: null, error: null });
    }
    // ---- P8 method appendix and samples (contracts/p8.md §五–六)
    if (path === `/projects/${PROJECT}/method-appendix` && request.method === 'POST') return json(response, 200, APPENDIX);
    if (path === `/projects/${PROJECT}/samples` && request.method === 'POST') return json(response, 201, { layer_id: SAMPLE_LAYER, sampled: body.n, total: 2 });
    if (path === `/layers/${SAMPLE_LAYER}/sample-summary`) return json(response, 200, SAMPLE_SUMMARY);
    // ---- P3 annotation (contracts/p3.md §三)
    if (path === '/label-sets' && request.method === 'GET') {
      const kind = url.searchParams.get('kind');
      return json(response, 200, LABEL_SETS.filter(set => !kind || set.kind === kind));
    }
    if (path === `/projects/${PROJECT}/layers` && request.method === 'POST') {
      return json(response, 201, { ...layer('layer-new', body.kind, body.name, 'preannotating'), label_set_id: body.label_set_id, job_id: 'job-preannotate' });
    }
    if (path === '/layers/layer-new') {
      const ready = (jobPolls.get('job-preannotate') ?? 0) >= 2;
      return json(response, 200, { ...layer('layer-new', 'pos', '词性', ready ? 'ready' : 'preannotating'), job_id: 'job-preannotate' });
    }
    if (path === `/layers/${DEP_LAYER}`) return json(response, 200, layer(DEP_LAYER, 'dep', '依存', 'ready'));
    if (path === `/layers/${SPAN_LAYER}`) return json(response, 200, layer(SPAN_LAYER, 'span', '片段', 'ready'));
    if (path === `/layers/${ALIGN_LAYER}`) return json(response, 200, layer(ALIGN_LAYER, 'alignment', '对齐', 'ready'));
    if (path === `/layers/${DEP_LAYER}/sentences/doc1/3`) return json(response, 200, SENTENCE);
    if (path === `/layers/${DEP_LAYER}/suggest` && request.method === 'POST') {
      return json(response, 200, {
        id: 'annot-1', token_index: body.token_index, label: body.label ?? null, head: body.head ?? null, model_label: 'obj', model_head: 2,
        source: 'model:fake-model', status: 'suggested', revision: 1, updated_by: USER.id, updated_at: new Date().toISOString(),
      });
    }
    // ---- P5 spans, alignment, agreement (contracts/p5.md §三)
    if (path === `/layers/${SPAN_LAYER}/documents`) return json(response, 200, { items: LAYER_DOCS, total: LAYER_DOCS.length });
    if (path === `/layers/${SPAN_LAYER}/spans` && request.method === 'GET') {
      const at = url.searchParams.get('document_id') === 'doc1' && url.searchParams.get('cursor') === 'doc1:2';
      return json(response, 200, { items: at ? [SPAN_SENTENCE] : [], next_cursor: null });
    }
    if (path === `/layers/${SPAN_LAYER}/spans/suggest` && request.method === 'POST') {
      const spans = body.spans.map((s: any, i: number) => ({
        id: `new-span-${i}`, ...s, attrs: s.attrs ?? {}, text: null, source: 'model:agent', status: 'suggested', model_label: s.label, revision: 1, annotator_id: USER.id,
      }));
      const relations = (body.relations ?? []).map((r: any, i: number) => ({
        id: `new-rel-${i}`, from_span_id: typeof r.from === 'number' ? spans[r.from].id : r.from,
        to_span_id: typeof r.to === 'number' ? spans[r.to].id : r.to, label: r.label, source: 'model:agent', status: 'suggested', revision: 1,
      }));
      return json(response, 200, { spans, relations, skipped: [] });
    }
    if (path === `/layers/${SPAN_LAYER}/agreement`) return json(response, 200, AGREEMENT);
    if (path === `/layers/${SPAN_LAYER}/disagreements`) return json(response, 200, { items: DISAGREEMENTS, next_cursor: 'doc1:11' });
    if (path === `/layers/${ALIGN_LAYER}/alignments` && request.method === 'GET') return json(response, 200, ALIGN_PAGE);
    if (path === `/layers/${ALIGN_LAYER}/alignments/suggest` && request.method === 'POST') {
      return json(response, 200, {
        items: body.links.map((l: any, i: number) => ({
          id: `new-al-${i}`, level: 'word', src_tokens: l.src, tgt_tokens: l.tgt, score: null, source: 'model:agent', status: 'suggested', revision: 1, annotator_id: USER.id,
        })),
        skipped: [],
      });
    }
    return fail(response, 404, 'NOT_FOUND');
  });
  return { ...(await listen(server)), requests, firstJobPoll, me };
}

// ---------------------------------------------------------------- store + config

export class MemoryStore implements Store {
  sessions = new Map<string, SessionRecord>();
  messages = new Map<string, Message & { session_id: string }>();
  async resetRunning() { for (const s of this.sessions.values()) s.state = 'idle'; }
  async createSession(session: Omit<SessionRecord, 'message_count' | 'created_at' | 'updated_at'>) {
    const now = new Date().toISOString();
    this.sessions.set(session.id, { ...session, created_at: now, updated_at: now, message_count: 0 });
    return (await this.getSession(session.id))!;
  }
  async getSession(id: string) {
    const s = this.sessions.get(id);
    if (!s) return null;
    return structuredClone({ ...s, message_count: [...this.messages.values()].filter(m => m.session_id === id).length });
  }
  async listSessions(projectId: string, ownerId: string) {
    const ids = [...this.sessions.values()].filter(s => s.project_id === projectId && s.owner_id === ownerId).map(s => s.id);
    return Promise.all(ids.map(async id => (await this.getSession(id))!));
  }
  async updateSession(id: string, fields: { title?: string; scope?: Scope; state?: Session['state'] }) {
    const s = this.sessions.get(id);
    if (s) Object.assign(s, structuredClone(fields), { updated_at: new Date().toISOString() });
  }
  async deleteSession(id: string) {
    this.sessions.delete(id);
    for (const [key, m] of this.messages) if (m.session_id === id) this.messages.delete(key);
  }
  async listMessages(sessionId: string) {
    return [...this.messages.values()].filter(m => m.session_id === sessionId)
      .sort((a, b) => a.created_at.localeCompare(b.created_at))
      .map(({ session_id: _s, ...m }) => structuredClone(m));
  }
  async insertMessage(sessionId: string, message: Message) { this.messages.set(message.id, structuredClone({ ...message, session_id: sessionId })); }
  async updateMessage(id: string, fields: { content: string; parts: Part[]; tool_calls: ToolCall[]; duration_ms?: number | null }) {
    const m = this.messages.get(id);
    if (m) Object.assign(m, structuredClone(fields));
  }
  async deleteMessage(id: string) { this.messages.delete(id); }
  usage: (UsageRow & { created_at: Date })[] = [];
  async recordUsage(row: UsageRow) { this.usage.push({ ...row, created_at: new Date() }); }
  async monthlyTokens(userId: string, since: Date) {
    return this.usage.filter(row => row.user_id === userId && row.created_at >= since).reduce((sum, row) => sum + row.total_tokens, 0);
  }
  async close() {}
}

export function testConfig(overrides: Partial<Config> & { apiUrl: string; modelUrl?: string; modelApi?: 'openai-completions' | 'openai-responses' }): Config {
  const root = join(import.meta.dirname, '..', '..', '..', 'tmp');
  mkdirSync(root, { recursive: true });
  const { apiUrl, modelUrl, modelApi, ...rest } = overrides;
  return {
    port: 0, apiBaseUrl: `${apiUrl}/api`, databaseUrl: '', dataDir: mkdtempSync(join(root, 'agent-test-')),
    publicOrigin: ORIGIN,
    model: modelUrl ? {
      baseUrl: modelUrl, apiKey: MODEL_KEY, id: 'fake-model', api: modelApi ?? 'openai-completions',
      contextWindow: 32000, maxTokens: 2048, timeoutMs: 10000, reasoning: false,
    } : null,
    jobPollMs: 10, jobWaitMs: 5000, monthlyTokensPerUser: 0, maxRunsPerUser: 2,
    ...rest,
  };
}

/** Parses a complete SSE body into [{event, data}] (comment lines ignored). */
export function parseSse(text: string): { event: string; data: any }[] {
  return text.split('\n\n').filter(block => block.trim() && !block.startsWith(':')).map(block => {
    const event = /^event: ?(.*)$/m.exec(block)?.[1] ?? 'message';
    const data = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.replace(/^data: ?/, '')).join('\n');
    return { event, data: JSON.parse(data) };
  });
}
