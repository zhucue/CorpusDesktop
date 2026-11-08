/**
 * Pi customTools (contracts/p2.md §五 工具, p3.md §五 annot.*, p4.md §五 kb.*, p5.md §四 annot.spans / align.*). Each tool is a thin call to the api
 * with the run's agent token; the api decides permissions. Results stay compact.
 *
 * Write tools (those with `confirm`) never run from the model directly: the call returns NEEDS_CONFIRMATION
 * with a proposal for the confirm card, and the server runs it after the user presses 执行 (contracts/p2.md 第十二节).
 */
import { setTimeout as sleep } from 'node:timers/promises';
import type { ToolDefinition } from '@earendil-works/pi-coding-agent';
import { Type, type Static, type TSchema } from 'typebox';
import { ApiError, query, type ApiClient, type Job } from './api.ts';
import { findSkill, readSkill, researchSkills } from './skills.ts';
import type { Proposal, Scope } from './types.ts';

export interface ToolContext {
  api: ApiClient;
  projectId: string;
  scope: Scope;
  jobPollMs: number;
  jobWaitMs: number;
}

export interface ToolOutput {
  data: unknown;
  summary: string;
  ref?: { kind: string; id: string };
  /** Set when a write tool was only proposed. */
  proposal?: Proposal;
}

interface Spec<T extends TSchema = TSchema> {
  name: string;
  description: string;
  parameters: T;
  run: (args: Static<T>, signal: AbortSignal | undefined) => Promise<ToolOutput>;
  /** Write tool: describe (and pre-check) the action for the confirm card; `run` happens only after the user confirms. */
  confirm?: (args: Static<T>, signal: AbortSignal | undefined) => Promise<Proposal>;
}

const spec = <T extends TSchema>(value: Spec<T>) => value as unknown as Spec;

const scopeObject = () => Type.Object({
  corpus_id: Type.Optional(Type.String()),
  subcorpus_id: Type.Optional(Type.String()),
}, { description: '{corpus_id} 或 {subcorpus_id}；省略则用会话范围' });
const ScopeArg = Type.Optional(scopeObject());
type ScopeInput = { corpus_id?: string; subcorpus_id?: string } | undefined;

const oneOf = (values: string[]) => Type.Optional(Type.Union(values.map(value => Type.Literal(value))));
const positiveInt = () => Type.Optional(Type.Integer({ minimum: 1 }));
/** Translation condition of a parallel corpus (contracts/p8.md §四): keep hits whose aligned sentence has (+) or lacks (-) a match. */
const AlignedArg = Type.Optional(Type.Object({
  op: Type.Union([Type.Literal('+'), Type.Literal('-')], { description: '+ 对齐句含该译文，- 不含' }),
  query: Type.String({ minLength: 1, description: '译文一侧的查询式，如 "translate" 或 {lemma=translate}' }),
}, { description: '译文条件，只用于平行语料：只保留对齐译文含（+）或不含（-）该查询命中的结果' }));
type AlignedInput = { op: '+' | '-'; query: string } | undefined;
const alignedBody = (aligned: AlignedInput) => aligned ? { aligned: { op: aligned.op, query: aligned.query } } : {};
const alignedLine = (aligned: AlignedInput) => aligned ? [`译文条件：${aligned.op === '+' ? '含' : '不含'} ${aligned.query}`] : [];
/** Scope compared for stat row links: null fields dropped, keys sorted. */
const scopeKey = (scope: unknown) => JSON.stringify(Object.fromEntries(
  Object.entries((scope ?? {}) as Record<string, unknown>).filter(([, v]) => v !== null && v !== undefined).sort(([a], [b]) => a.localeCompare(b))));
/** Methods whose rows the assistant opens in the search page: rows carry their search link fields. */
const ROW_LINK_METHODS = new Set(['breakdown', 'translations', 'vocab_profile', 'compare', 'word_sketch', 'sketch_diff']);
/** Word sketch: collocates kept per relation column; sketch diff: per side (偏 A / 共同 / 偏 B). */
const MAX_SKETCH_PER_RELATION = 10;
const MAX_DIFF_PER_SIDE = 15;
const MAX_SEMANTIC_HITS = 20;
const MAX_APPENDIX_CHARS = 12000;
/** Document selector of the sentence-level annotation tools (one of; none → the layer's first document). */
const DocArgs = {
  document_id: Type.Optional(Type.String()),
  document_title: Type.Optional(Type.String({ minLength: 1 })),
  document_ordinal: Type.Optional(Type.Integer({ minimum: 1 })),
};
const MAX_STAT_ROWS = 50;
const MAX_HITS = 20;
const MAX_DIFF_SENTENCES = 10;
const MAX_LABELS = 30;
const EFFECTIVE = new Set(['confirmed', 'modified']);
const MAX_LAYER_DOCS = 50;
const MAX_KB_ITEMS = 8;
const MAX_CHUNK_CHARS = 600;
const MAX_DRAFT_TERMS = 20;
const MAX_LIST = 50;
const MAX_PAIRS = 10;
const MAX_DISAGREEMENTS = 10;
const seg = (value: string | number) => encodeURIComponent(String(value));
/** List endpoints return either a bare array or {items, total}. */
const listItems = (list: any): any[] => Array.isArray(list) ? list : list?.items ?? [];
const clip = (text: unknown, max: number) => {
  const value = String(text ?? '');
  return value.length > max ? value.slice(0, max) + '…' : value;
};
/** Chunk locator ({page} | {heading_path} | {line}) as display text, e.g. "第 5 页", "引言 › 方法", "第 12 行". */
export const locatorText = (locator: any): string => {
  if (!locator || typeof locator !== 'object') return '';
  if (locator.page !== undefined && locator.page !== null) return `第 ${locator.page} 页`;
  if (Array.isArray(locator.heading_path) && locator.heading_path.length) return locator.heading_path.join(' › ');
  if (typeof locator.heading_path === 'string' && locator.heading_path) return locator.heading_path;
  if (locator.line !== undefined && locator.line !== null) return `第 ${locator.line} 行`;
  return '';
};
const compactTerm = (term: any) => ({
  term_id: term.id, term: term.term, language: term.language, translations: term.translations ?? [],
  definition: term.definition ?? '', domain: term.domain ?? '', status: term.status, source: term.source,
  examples: (term.examples ?? []).slice(0, 3).map((e: any) => ({ text: clip(e.text, 200), source: e.source ?? '' })),
});
const compactKbDocument = (doc: any) => ({
  document_id: doc.id, kind: doc.kind, title: doc.title, source: doc.source ?? null, status: doc.status,
  chunk_count: doc.chunk_count ?? 0, error: doc.error ?? null, updated_at: doc.updated_at,
});

/**
 * Pi tool names must match [A-Za-z0-9_-]; the contract name keeps the dot. `skills.read` takes Pi's `read` name:
 * Pi lists skills in the system prompt only when a `read` tool exists, and this one reads skill files only.
 */
export const piName = (name: string) => name === 'skills.read' ? 'read' : name.replace('.', '_');

/** Step and citation summaries are shown to users: Chinese names, no internal values. */
const METHOD_NAMES: Record<string, string> = {
  frequency: '频次', ngrams: 'n-gram', collocations: '搭配', keywords: '关键词', distribution: '分布', breakdown: '命中分解', translations: '译法',
  text_metrics: '文本指标', vocab_profile: '词汇等级', compare: '对比', word_sketch: 'Word Sketch', sketch_diff: '近义词对比',
};
const CORPUS_STATUS: Record<string, string> = { ready: '就绪', indexing: '索引中', importing: '导入中', failed: '失败', pending: '等待中' };

const compactJob = (job: Job) => ({
  job_id: job.id, kind: job.kind, state: job.state, progress: job.progress, result: job.result, error: job.error,
});

/** Subcorpus filter as text: {"year": {"gte": 2000, "lte": 2010}, "genre": ["news"]} → "year 2000–2010；genre news". */
const filterText = (filter: Record<string, unknown>) => Object.entries(filter).map(([key, value]) => {
  if (Array.isArray(value)) return `${key} ${value.join('、')}`;
  if (value && typeof value === 'object') {
    const range = value as { gte?: unknown; lte?: unknown };
    return `${key} ${range.gte ?? ''}–${range.lte ?? ''}`;
  }
  return `${key} ${String(value)}`;
}).join('；') || '无';

export function toolSpecs(ctx: ToolContext): Spec[] {
  const { api, projectId } = ctx;
  const names = new Map<string, string>();

  function resolveScope(input: ScopeInput): NonNullable<Scope> {
    if (input?.subcorpus_id) return { subcorpus_id: input.subcorpus_id };
    if (input?.corpus_id) return { corpus_id: input.corpus_id };
    if (ctx.scope) return ctx.scope;
    throw new Error('SCOPE_REQUIRED: 会话未指定范围，请传入 scope（先用 corpora_list 选择语料库）');
  }

  async function scopeName(scope: NonNullable<Scope>, signal?: AbortSignal): Promise<string> {
    const key = JSON.stringify(scope);
    if (!names.has(key)) {
      const path = 'subcorpus_id' in scope ? `/subcorpora/${scope.subcorpus_id}` : `/corpora/${scope.corpus_id}`;
      names.set(key, (await api.get<{ name: string }>(path, signal)).name);
    }
    return names.get(key)!;
  }

  const corpora = new Map<string, any>();
  async function getCorpus(corpusId: string, signal?: AbortSignal): Promise<any> {
    if (!corpora.has(corpusId)) corpora.set(corpusId, await api.get<any>(`/corpora/${seg(corpusId)}`, signal));
    return corpora.get(corpusId);
  }

  /** The assistant does not create layers on built-in corpora (project_id null): a whole-corpus preannotation job is too heavy to start from a chat. */
  async function projectCorpus(corpusId: string, signal?: AbortSignal): Promise<any> {
    const corpus = await getCorpus(corpusId, signal);
    if (corpus.project_id === null) {
      throw new Error(`BUILTIN_CORPUS: “${corpus.name}”是内置语料，助手不在内置语料上建标注层；请告诉用户可以自己在标注页建层，或改用本项目语料`);
    }
    return corpus;
  }

  async function scopeLine(scope: NonNullable<Scope>, signal?: AbortSignal): Promise<string> {
    return `范围：${await scopeName(scope, signal).catch(() => '未知范围')}`;
  }

  async function waitJob(job: Job, signal?: AbortSignal): Promise<Job> {
    const deadline = Date.now() + ctx.jobWaitMs;
    let current = job;
    while ((current.state === 'queued' || current.state === 'running') && Date.now() < deadline) {
      await sleep(ctx.jobPollMs, undefined, { signal });
      current = await api.get<Job>(`/jobs/${job.id}`, signal);
    }
    return current;
  }

  const layers = new Map<string, any>();
  async function getLayer(layerId: string, signal?: AbortSignal): Promise<any> {
    if (!layers.has(layerId)) layers.set(layerId, await api.get<any>(`/layers/${seg(layerId)}`, signal));
    return layers.get(layerId);
  }

  /** Default built-in label set: dep → ud-deprel; pos → jieba for Chinese corpora, upos otherwise. */
  async function defaultLabelSet(corpusId: string, kind: string, signal?: AbortSignal): Promise<string> {
    const list = await api.get<any>(`/label-sets${query({ project_id: projectId, kind })}`, signal);
    const items: any[] = Array.isArray(list) ? list : list?.items ?? [];
    let wanted = 'ud-deprel';
    if (kind === 'pos') {
      const corpus = await getCorpus(corpusId, signal);
      wanted = String(corpus.language ?? '').startsWith('zh') ? 'jieba' : 'upos';
    }
    const builtin = items.filter(set => set.project_id === null);
    const found = builtin.find(set => set.name === wanted) ?? builtin[0];
    if (!found) throw new Error(`LABEL_SET_REQUIRED: 没有可用的 ${kind} 标签集，请传入 label_set_id`);
    return found.id;
  }

  /** Span label set of a sample layer: by id, else by name (exact, then unique substring); none → list the choices. */
  async function spanLabelSet(args: { label_set_id?: string; label_set_name?: string }, signal?: AbortSignal): Promise<{ id: string; name: string }> {
    const sets = listItems(await api.get<any>(`/label-sets${query({ project_id: projectId, kind: 'span' })}`, signal));
    const names = sets.map((set: any) => set.name).join('、') || '无';
    if (args.label_set_id) {
      const found = sets.find((set: any) => set.id === args.label_set_id);
      if (!found) throw new Error(`LABEL_SET_NOT_FOUND: 没有该片段标签集；可用：${names}`);
      return { id: found.id, name: found.name };
    }
    if (!args.label_set_name) throw new Error(`LABEL_SET_REQUIRED: 请传入 label_set_name；可用的片段标签集：${names}（没有合适的请用户在标注页新建）`);
    const wanted = args.label_set_name.trim().toLowerCase();
    const exact = sets.filter((set: any) => String(set.name).toLowerCase() === wanted);
    const pick = exact.length ? exact : sets.filter((set: any) => String(set.name).toLowerCase().includes(wanted));
    if (pick.length !== 1) throw new Error(`LABEL_SET_${pick.length ? 'AMBIGUOUS' : 'NOT_FOUND'}: “${args.label_set_name}”${pick.length ? '匹配多个' : '不存在'}；可用的片段标签集：${names}`);
    return { id: pick[0].id, name: pick[0].name };
  }

  /** `documents` here is the layer's progress by document ({total, done}); annot.layers adds the list separately. */
  const compactLayer = (layer: any) => ({
    layer_id: layer.id, corpus_id: layer.corpus_id, corpus_name: layer.corpus_name, kind: layer.kind, name: layer.name,
    label_set_id: layer.label_set_id, source_model: layer.source_model, status: layer.status, job_id: layer.job_id ?? null,
    progress: layer.progress, document_progress: layer.documents, error: layer.error ?? null,
    ...Object.fromEntries(['mode', 'level', 'base_layer_id', 'src_corpus_id', 'tgt_corpus_id', 'guideline_document_id']
      .filter(key => layer[key] !== undefined).map(key => [key, layer[key]])),
  });

  /** Documents of a layer in corpus order (GET /layers/{id}/documents), cached per run. */
  const layerDocs = new Map<string, { document_id: string; title: string }[]>();
  async function getLayerDocs(layerId: string, signal?: AbortSignal) {
    if (!layerDocs.has(layerId)) {
      const docs = listItems(await api.get<any>(`/layers/${seg(layerId)}/documents`, signal));
      layerDocs.set(layerId, docs.map(d => ({ document_id: String(d.document_id), title: String(d.title ?? '') })));
    }
    return layerDocs.get(layerId)!;
  }

  /** document_id as given, else by title (exact, then unique substring) or 1-based ordinal; none → first document. */
  async function resolveDocument(layerId: string, args: { document_id?: string; document_title?: string; document_ordinal?: number },
    signal?: AbortSignal): Promise<{ document_id: string; title: string | null; note?: string }> {
    if (args.document_id) return { document_id: args.document_id, title: null };
    const docs = await getLayerDocs(layerId, signal);
    if (!docs.length) throw new Error('NO_DOCUMENTS: 该标注层没有文档');
    if (args.document_title) {
      const wanted = args.document_title.trim().toLowerCase();
      const exact = docs.filter(d => d.title.toLowerCase() === wanted);
      const partial = exact.length ? exact : docs.filter(d => d.title.toLowerCase().includes(wanted));
      if (partial.length === 1) return partial[0];
      const names = docs.slice(0, 20).map((d, i) => `${i + 1}. ${d.title}`).join('；');
      throw new Error(partial.length
        ? `DOCUMENT_AMBIGUOUS: 有 ${partial.length} 个文档标题包含“${args.document_title}”，请指定 document_ordinal：${names}`
        : `DOCUMENT_NOT_FOUND: 没有标题为“${args.document_title}”的文档：${names}`);
    }
    if (args.document_ordinal !== undefined) {
      const doc = docs[args.document_ordinal - 1];
      if (!doc) throw new Error(`DOCUMENT_NOT_FOUND: 该层只有 ${docs.length} 个文档`);
      return doc;
    }
    return { ...docs[0], note: `未指定文档，使用该层第一个文档“${docs[0].title}”` };
  }

  /** One sentence of a span layer: GET /layers/{id}/spans with the (exclusive) cursor at the previous sentence. */
  async function readSpanSentence(layerId: string, documentId: string, sentenceIndex: number, signal?: AbortSignal): Promise<any> {
    const page = await api.get<any>(`/layers/${seg(layerId)}/spans${query({
      document_id: documentId, cursor: sentenceIndex > 0 ? `${documentId}:${sentenceIndex - 1}` : undefined, page_size: 1,
    })}`, signal);
    const sentence = listItems(page).find((s: any) => s.document_id === documentId && s.sentence_index === sentenceIndex);
    if (!sentence) throw new Error(`SENTENCE_NOT_FOUND: 文档 ${documentId} 没有第 ${sentenceIndex + 1} 句`);
    return sentence;
  }

  /** Spans get sentence-relative start/end (code points); relations point at span array indices. */
  const compactSpanSentence = (sentence: any) => {
    const base = Number(sentence.start_cp ?? 0);
    const spans: any[] = sentence.spans ?? [];
    const indexOf = new Map(spans.map((s, i) => [s.id, i]));
    return {
      document_id: sentence.document_id, sentence_index: sentence.sentence_index, text: sentence.text,
      start_cp: sentence.start_cp, end_cp: sentence.end_cp,
      spans: spans.map(s => ({
        span_id: s.id, start: s.start_cp - base, end: s.end_cp - base, start_cp: s.start_cp, end_cp: s.end_cp, text: s.text,
        label: s.label, attrs: s.attrs ?? {}, status: s.status, source: s.source, model_label: s.model_label ?? null,
        ...(s.annotator_id ? { annotator_id: s.annotator_id } : {}),
      })),
      relations: (sentence.relations ?? []).map((r: any) => ({
        relation_id: r.id, from: indexOf.get(r.from_span_id) ?? null, to: indexOf.get(r.to_span_id) ?? null,
        from_span_id: r.from_span_id, to_span_id: r.to_span_id, label: r.label, status: r.status, source: r.source,
      })),
    };
  };

  /** Spans must lie inside the sentence; relation indices inside the new spans (checked before proposing and before posting). */
  async function checkSpans(args: {
    layer_id: string; document_id?: string; document_title?: string; document_ordinal?: number; sentence_index: number;
    spans: { start_cp: number; end_cp: number }[]; relations?: { from: number | string; to: number | string }[];
  }, signal?: AbortSignal) {
    const doc = await resolveDocument(args.layer_id, args, signal);
    const sentence = await readSpanSentence(args.layer_id, doc.document_id, args.sentence_index, signal);
    const [lo, hi] = [Number(sentence.start_cp ?? 0), Number(sentence.end_cp ?? 0)];
    for (const span of args.spans) {
      if (span.start_cp >= span.end_cp || span.start_cp < lo || span.end_cp > hi) {
        throw new Error(`SPAN_OUT_OF_SENTENCE: 片段 ${span.start_cp}-${span.end_cp} 不在该句范围 ${lo}-${hi} 内（start_cp/end_cp 为文档内偏移 = 句子 start_cp + 句内偏移）`);
      }
    }
    for (const rel of args.relations ?? []) {
      for (const end of [rel.from, rel.to]) {
        if (typeof end === 'number' && end >= args.spans.length) throw new Error(`INVALID_RELATION: 下标 ${end} 超出 spans 数量 ${args.spans.length}`);
      }
    }
    return { doc, sentence, lo };
  }

  /** A job still running after the wait: hand back job_id instead of failing. */
  const pendingOutput = (job: Job, what: string, extra: Record<string, unknown> = {}): ToolOutput => ({
    data: {
      ...extra, job_id: job.id, kind: job.kind, state: job.state, progress: job.progress,
      note: `${what}等待超过 ${Math.round(ctx.jobWaitMs / 1000)} 秒仍未完成，请用户到任务页查看；不要重复提交。`,
    },
    summary: '任务仍在运行',
    ref: { kind: 'job', id: job.id },
  });
  const jobFailed = (job: Job, what: string) =>
    new Error(`${job.error?.code ?? 'JOB_' + job.state.toUpperCase()}: ${job.error?.message ?? what + '任务未成功'}`);
  const running = (job: Job) => job.state === 'queued' || job.state === 'running';

  /** Diff-view value of one token: pos → label; dep → "label→head". */
  const annotValue = (kind: string, label: unknown, head: unknown) =>
    label === null || label === undefined ? '' : kind === 'dep' ? `${label}→${head ?? ''}` : String(label);

  /**
   * Runs a stat job and returns its first rows. `shape` replaces the flat `rows` (word sketch: per relation;
   * sketch diff: per side) and gets the compacted rows.
   */
  async function runStat(path: string, body: Record<string, unknown>, signal?: AbortSignal,
    shape?: (rows: any[], stat: any) => Record<string, unknown>): Promise<ToolOutput> {
    const job = await waitJob(await api.post<Job>(path, body, signal), signal);
    if (running(job)) return pendingOutput(job, '');
    if (job.state !== 'succeeded') throw jobFailed(job, '统计');
    const statId = String(job.result?.stat_id ?? '');
    if (!statId) throw new Error('STAT_RESULT_MISSING: 任务成功但没有 stat_id');
    const stat = await api.get<any>(`/stats/${statId}`, signal);
    // Rows of these methods open the search page with their own query (and translation condition);
    // search_scope only when it differs from the session scope (meta rows filter the scope).
    const links = ROW_LINK_METHODS.has(stat.method);
    const sessionScope = scopeKey(ctx.scope);
    const compact = (row: any) => ({
      key: row.key, values: row.values,
      ...(links ? { search_query: row.search_query ?? null } : {}),
      ...(links && row.search_query_b ? { search_query_b: row.search_query_b } : {}),
      ...(links && row.search_aligned ? { search_aligned: row.search_aligned } : {}),
      ...(links && row.search_layers ? { search_layers: row.search_layers } : {}),
      ...(links && row.search_scope && scopeKey(row.search_scope) !== sessionScope ? { search_scope: row.search_scope } : {}),
    });
    const rows: any[] = stat.rows ?? [];
    return {
      data: {
        stat_id: statId, method: stat.method, scope: stat.scope, index_version: stat.index_version,
        columns: stat.columns, row_count: stat.row_count, totals: stat.totals,
        ...(shape ? shape(rows.map(compact), stat) : { rows: rows.slice(0, MAX_STAT_ROWS).map(compact) }),
      },
      summary: `${METHOD_NAMES[stat.method] ?? '统计'}：${stat.row_count ?? 0} 行`,
      ref: { kind: 'stat', id: statId },
    };
  }

  /** Sketch rows in the WordSketch / SketchDiff card shape (values keys as the api names them). */
  const num = (value: unknown) => value === null || value === undefined ? null : Number(value);
  const collocateOf = (row: any) => String(row.values?.collocate ?? row.values?.item ?? row.key ?? '');
  const linkOf = (row: any) => ({ search_query: row.search_query ?? null, ...(row.search_scope ? { search_scope: row.search_scope } : {}) });
  const sketchRow = (row: any) => ({
    collocate: collocateOf(row), freq: num(row.values?.freq ?? row.values?.cooc), logdice: num(row.values?.logdice), ...linkOf(row),
  });
  const relationLabel = (row: any) => String(row.values?.relation_label ?? row.values?.relation ?? '');
  /** Chinese sketches search on a dependency layer: the rows' search_layers (one per stat) go with the card. */
  const layersOf = (rows: any[]) => {
    const layers = rows.find(row => row.search_layers)?.search_layers;
    return layers ? { search_layers: layers } : {};
  };
  /** B's rows open B's search (search_query_b), as on the stats page. */
  const diffRow = (row: any, side: 'a' | 'common' | 'b') => ({
    relation: relationLabel(row), collocate: collocateOf(row),
    freq_a: num(row.values?.freq_a), freq_b: num(row.values?.freq_b),
    logdice_a: num(row.values?.logdice_a), logdice_b: num(row.values?.logdice_b), diff: num(row.values?.diff),
    ...linkOf(side === 'b' && row.search_query_b ? { ...row, search_query: row.search_query_b } : row),
  });

  /**
   * Word sketch rows grouped by relation column (values.relation), in totals.relations order ([{key, label}] or names),
   * each column named by its label; rows without a relation stay flat.
   */
  const byRelation = (rows: any[], stat: any) => {
    const relationOf = (row: any) => String(row.values?.relation ?? '');
    if (!rows.some(relationOf)) return { rows: rows.slice(0, MAX_STAT_ROWS) };
    const order = ((stat.totals?.relations ?? []) as any[]).map(rel => String(rel && typeof rel === 'object' ? rel.key : rel));
    const groups = new Map<string, { relation: string; rows: any[] }>(order.map(key => [key, { relation: key, rows: [] }]));
    for (const row of rows) {
      const key = relationOf(row);
      if (!groups.has(key)) groups.set(key, { relation: key, rows: [] });
      const group = groups.get(key)!;
      group.relation = relationLabel(row);
      if (group.rows.length < MAX_SKETCH_PER_RELATION) group.rows.push(sketchRow(row));
    }
    return { relations: [...groups.values()].filter(group => group.rows.length), ...layersOf(rows) };
  };

  /** Sketch diff side of a row: the api's side / group field when given, else unique to A, unique to B or shared. */
  const sideOf = (row: any): 'a' | 'common' | 'b' => {
    const given = String(row.values?.side ?? row.values?.group ?? '').toLowerCase().replace(/[\s偏]/g, '');
    if (given === 'a' || given === 'b') return given;
    if (given === 'common' || given === '共同') return 'common';
    const [fa, fb] = [Number(row.values?.freq_a ?? 0), Number(row.values?.freq_b ?? 0)];
    return fb === 0 ? 'a' : fa === 0 ? 'b' : 'common';
  };
  /**
   * Rows by side, most distinctive first (A and common by diff descending, B ascending, as on the stats page), each
   * cut to MAX_DIFF_PER_SIDE; side_totals are the full counts, total = every row (the SketchDiff card loads every row by stat_id).
   */
  const bySide = (rows: any[]) => {
    const groups: Record<'a' | 'common' | 'b', any[]> = { a: [], common: [], b: [] };
    for (const row of rows) groups[sideOf(row)].push(row);
    const diff = (row: any) => Number(row.values?.diff ?? 0) || 0;
    const sides = Object.fromEntries((['a', 'common', 'b'] as const).map(side => [side,
      [...groups[side]].sort((x, y) => side === 'b' ? diff(x) - diff(y) : diff(y) - diff(x))
        .slice(0, MAX_DIFF_PER_SIDE).map(row => diffRow(row, side))]));
    const side_totals = { a: groups.a.length, common: groups.common.length, b: groups.b.length, total: rows.length };
    return { sides, side_totals, ...layersOf(rows) };
  };

  return [
    spec({
      name: 'corpora.list',
      description: '列出可用语料库（内置语料与本项目语料），含状态与规模。',
      parameters: Type.Object({}),
      run: async (_args, signal) => {
        const page = await api.get<{ items: any[]; total: number }>(`/corpora${query({ project_id: projectId, page_size: 200 })}`, signal);
        return {
          data: {
            total: page.total,
            items: page.items.map(c => ({ id: c.id, name: c.name, language: c.language, builtin: c.project_id === null,
              parallel: c.parallel, status: c.status, stats: c.stats })),
          },
          summary: `${page.total} 个语料库`,
        };
      },
    }),
    spec({
      name: 'corpora.get',
      description: '读取一个语料库的信息与可筛选的元数据字段。',
      parameters: Type.Object({ corpus_id: Type.String() }),
      run: async (args, signal) => {
        const corpus = await api.get<any>(`/corpora/${args.corpus_id}`, signal);
        const fields = await api.get<unknown[]>(`/corpora/${args.corpus_id}/metadata-fields`, signal).catch(() => null);
        return { data: { ...corpus, metadata_fields: fields }, summary: `${corpus.name}（${CORPUS_STATUS[corpus.status] ?? corpus.status}）`, ref: { kind: 'corpus', id: corpus.id } };
      },
    }),
    spec({
      name: 'corpora.documents',
      description: `列出一个语料库的文档（最多 ${MAX_LIST} 个，按语料顺序）：document_id、标题、句数。q 匹配标题。`,
      parameters: Type.Object({ corpus_id: Type.String(), q: Type.Optional(Type.String()) }),
      run: async (args, signal) => {
        const page = await api.get<any>(`/corpora/${seg(args.corpus_id)}/documents${query({ q: args.q, page_size: MAX_LIST })}`, signal);
        const items = listItems(page);
        return {
          data: {
            total: page?.total ?? items.length,
            items: items.slice(0, MAX_LIST).map((d: any) => ({
              document_id: d.id, title: d.title, sentences: d.sentences ?? null, tokens: d.tokens ?? null,
            })),
          },
          summary: `${page?.total ?? items.length} 个文档`,
        };
      },
    }),
    spec({
      name: 'subcorpora.list',
      description: '列出本项目的子库。',
      parameters: Type.Object({}),
      run: async (_args, signal) => {
        const page = await api.get<{ items: any[]; total: number }>(`/projects/${projectId}/subcorpora${query({ page_size: 200 })}`, signal);
        return { data: page, summary: `${page.total} 个子库` };
      },
    }),
    spec({
      name: 'subcorpora.create',
      description: '按元数据筛选创建子库。filter 形如 {"year": {"gte": 2000, "lte": 2010}, "genre": ["news"]}，字段来自 corpora_get 的 metadata_fields。',
      parameters: Type.Object({
        name: Type.String({ minLength: 1 }),
        corpus_id: Type.String(),
        filter: Type.Record(Type.String(), Type.Unknown()),
      }),
      confirm: async (args, signal) => ({
        title: `新建子库「${args.name}」`,
        lines: [`语料库：${(await getCorpus(args.corpus_id, signal)).name}`, `筛选：${filterText(args.filter)}`],
      }),
      run: async (args, signal) => {
        const sub = await api.post<any>(`/projects/${projectId}/subcorpora`, args, signal);
        return { data: sub, summary: `子库 ${sub.name}：${sub.stats?.documents ?? 0} 篇`, ref: { kind: 'subcorpus', id: sub.id } };
      },
    }),
    spec({
      name: 'corpus.parse',
      description: '检查查询式语法，返回解析结果或错误位置。按范围（默认会话范围）语料的词性体系解析，并检查所需的标注层。',
      parameters: Type.Object({ query: Type.String({ minLength: 1 }), scope: ScopeArg }),
      run: async (args, signal) => {
        const scope = args.scope?.subcorpus_id || args.scope?.corpus_id ? resolveScope(args.scope) : ctx.scope;
        const result = await api.post<any>('/search/parse', { query: args.query, ...(scope ? { scope } : {}) }, signal);
        return { data: result, summary: result.ok ? '语法正确' : `语法错误：${result.error?.message ?? ''}` };
      },
    }),
    spec({
      name: 'corpus.search',
      description: `按查询式检索，返回命中、句、文档三项计数、前 ${MAX_HITS} 条命中（含 hit_id）和 search_id。平行语料可加 aligned 译文条件，如只看译成 translate 的例句：aligned={op:"+", query:"\\"translate\\""}；含与不含两次计数之和等于无条件计数。`,
      parameters: Type.Object({
        query: Type.String({ minLength: 1 }),
        scope: ScopeArg,
        sort: oneOf(['position', 'left', 'right', 'random']),
        aligned: AlignedArg,
      }),
      run: async (args, signal) => {
        const scope = resolveScope(args.scope);
        const result = await api.post<any>('/search', {
          scope, query: args.query, ...alignedBody(args.aligned), context: { unit: 'char', size: 40 }, sort: args.sort ?? 'position',
          page: 1, page_size: MAX_HITS,
        }, signal);
        const counts = result.counts;
        return {
          data: {
            search_id: result.search_id, query: args.query, ...alignedBody(args.aligned), scope, scope_name: await scopeName(scope, signal), counts,
            hits: (result.items ?? []).slice(0, MAX_HITS).map((hit: any) => ({
              hit_id: hit.hit_id, sentence_index: hit.sentence_index, left: hit.left, match: hit.match, right: hit.right,
              source: hit.document_title,
              ...(hit.aligned?.length ? { aligned: hit.aligned.map((a: any) => a.text).join(' / ') } : {}),
            })),
          },
          summary: `命中 ${counts.hits}，句 ${counts.sentences}，文档 ${counts.documents}${args.aligned ? '（含译文条件）' : ''}${counts.complete === false ? '（计数未完成）' : ''}`,
          ref: { kind: 'search', id: result.search_id },
        };
      },
    }),
    spec({
      name: 'corpus.context',
      description: '读取一条命中的上下文句子。hit_id 与 sentence_index 取自 corpus_search 结果。',
      parameters: Type.Object({
        hit_id: Type.String(),
        sentence_index: Type.Integer({ minimum: 0 }),
        before: Type.Optional(Type.Integer({ minimum: 0, maximum: 5 })),
        after: Type.Optional(Type.Integer({ minimum: 0, maximum: 5 })),
      }),
      run: async (args, signal) => {
        const match = /^(.+):(\d+)-(\d+)$/.exec(args.hit_id);
        if (!match) throw new Error('INVALID_HIT_ID: hit_id 应为 <document_id>:<start_cp>-<end_cp>');
        const result = await api.get<any>(`/search/context${query({
          document_id: match[1], sentence_index: args.sentence_index, before: args.before ?? 1, after: args.after ?? 1,
          start_cp: match[2], end_cp: match[3],
        })}`, signal);
        return {
          data: { document: { id: result.document?.id, title: result.document?.title, metadata: result.document?.metadata }, sentences: result.sentences },
          summary: `${result.document?.title ?? ''} ${result.sentences?.length ?? 0} 句`,
        };
      },
    }),
    spec({
      name: 'corpus.sentence',
      description: '读取语料中的一句及其系统标注（不需要标注层）：每个 token 的 index（1 起）、form、pos、lemma、head（句内 token 序号，0 为根）、deprel。内置 UD 语料自带词性和依存，用户要看某句的依存结构或词性时用它，再用 DependencyTree 呈现。文档用 document_id、document_title 或 document_ordinal（语料顺序 1 起）之一指定；都省略时用第一个文档。',
      parameters: Type.Object({
        corpus_id: Type.Optional(Type.String({ description: '省略则用会话范围的语料库' })),
        ...DocArgs,
        sentence_index: Type.Integer({ minimum: 0 }),
      }),
      run: async (args, signal) => {
        const scope = resolveScope(args.corpus_id ? { corpus_id: args.corpus_id } : undefined);
        if (!('corpus_id' in scope) || !scope.corpus_id) throw new Error('CORPUS_REQUIRED: 子库范围请传入所属语料库的 corpus_id');
        const corpusId = scope.corpus_id;
        let doc: { document_id: string; title: string | null; note?: string } = { document_id: args.document_id ?? '', title: null };
        if (!args.document_id) {
          const page = await api.get<any>(`/corpora/${seg(corpusId)}/documents${query({ q: args.document_title, page_size: MAX_LIST })}`, signal);
          const docs = listItems(page).map((d: any) => ({ document_id: String(d.id), title: String(d.title ?? '') }));
          if (!docs.length) throw new Error(args.document_title ? `DOCUMENT_NOT_FOUND: 没有标题包含“${args.document_title}”的文档` : 'NO_DOCUMENTS: 该语料没有文档');
          if (args.document_title) {
            const exact = docs.filter(d => d.title.toLowerCase() === args.document_title!.trim().toLowerCase());
            const pick = exact.length === 1 ? exact : docs;
            if (pick.length > 1) throw new Error(`DOCUMENT_AMBIGUOUS: 有 ${docs.length} 个文档标题包含“${args.document_title}”：${docs.slice(0, 20).map(d => d.title).join('；')}`);
            doc = pick[0];
          } else if (args.document_ordinal !== undefined) {
            const found = docs[args.document_ordinal - 1];
            if (!found) throw new Error(`DOCUMENT_NOT_FOUND: 前 ${docs.length} 个文档中没有第 ${args.document_ordinal} 个`);
            doc = found;
          } else {
            doc = { ...docs[0], note: `未指定文档，使用第一个文档“${docs[0].title}”` };
          }
        }
        const sentence = await api.get<any>(
          `/corpora/${seg(corpusId)}/documents/${seg(doc.document_id)}/sentences/${seg(args.sentence_index)}`, signal);
        const tokens = (sentence.tokens ?? []).map((t: any) => ({
          index: t.index, form: t.form, pos: t.pos ?? null, lemma: t.lemma ?? null, head: t.head ?? null, deprel: t.deprel ?? null,
        }));
        const hasDep = tokens.some((t: any) => t.deprel);
        return {
          data: {
            corpus_id: corpusId, document_id: doc.document_id, ...(doc.title !== null ? { document_title: doc.title } : {}),
            ...(doc.note ? { note: doc.note } : {}), sentence_index: sentence.sentence_index, text: sentence.text, tokens,
            ...(hasDep ? {} : { note_dep: '该句没有系统依存标注（语料未自带依存）' }),
          },
          summary: `第 ${args.sentence_index + 1} 句，${tokens.length} 个词${hasDep ? '' : '，无依存'}`,
          ref: { kind: 'corpus', id: corpusId },
        };
      },
    }),
    spec({
      name: 'stats.frequency',
      description: '整个范围的词频表（后台任务，最多等待 90 秒），返回 stat_id 与前 50 行。默认附离散度列：range（出现的部分数）、range_pct、dp（Gries DP，0 均匀、越大越集中）、dp_norm、juilland_d；parts 决定“部分”怎么分。用户问“哪些词最常用”“某词分布是否均匀、是否集中在少数文档”时用它。只统计某个查询的命中由哪些词形构成时用 stats_breakdown。',
      parameters: Type.Object({
        scope: ScopeArg,
        unit: oneOf(['word', 'lemma', 'pos']),
        pos: Type.Optional(Type.String({ description: '只统计该词性，如 n、v' })),
        top: positiveInt(),
        min_freq: positiveInt(),
        parts: Type.Optional(Type.String({
          pattern: '^(document|segments|field:.+)$',
          description: '离散度的部分：document 每篇文档一部分（默认）；segments 按语料顺序等分 10 段；field:<字段> 每个元数据字段值一部分，如 field:year',
        })),
        dispersion: Type.Optional(Type.Boolean({ description: '是否计算离散度列，默认 true' })),
      }),
      run: (args, signal) => runStat('/stats/frequency', {
        scope: resolveScope(args.scope), unit: args.unit ?? 'word', pos: args.pos, top: args.top ?? 200, min_freq: args.min_freq ?? 1,
        ...(args.parts !== undefined ? { parts: args.parts } : {}), ...(args.dispersion !== undefined ? { dispersion: args.dispersion } : {}),
      }, signal),
    }),
    spec({
      name: 'stats.breakdown',
      description: '命中频次分解（后台任务）：一个查询的全部命中按 by 分组计数，返回 stat_id 与前 50 行（项、命中数、占比 %、每百万词；totals.hits 为全部命中数，等于检索计数）。用户问“命中里各词形 / 词元 / 词性各多少”“左边 / 右边第一个词是什么”“各年份 / 体裁各多少条”时用它。by：word 词形、lemma 词元、pos 词性、left1 左一词、right1 右一词、meta:<字段> 文档元数据（如 meta:year）。每行的 search_query 可打开该行例句（null 表示无法回到检索）。',
      parameters: Type.Object({
        scope: ScopeArg,
        query: Type.String({ minLength: 1, description: '查询式，与检索相同' }),
        by: Type.String({ pattern: '^(word|lemma|pos|left1|right1|meta:.+)$', description: 'word | lemma | pos | left1 | right1 | meta:<字段>' }),
        top: positiveInt(),
        min_freq: positiveInt(),
        layers: Type.Optional(Type.Object({
          pos: Type.Optional(Type.String()), dep: Type.Optional(Type.String()), span: Type.Optional(Type.String()),
        }, { description: '查询用到 {pos=}、{dep=}、[标签] 时所用的标注层 layer_id；一般省略' })),
      }),
      run: (args, signal) => runStat('/stats/breakdown', {
        scope: resolveScope(args.scope), query: args.query, by: args.by, top: args.top ?? 200, min_freq: args.min_freq ?? 1,
        ...(args.layers ? { layers: args.layers } : {}),
      }, signal),
    }),
    spec({
      name: 'stats.translations',
      description: '平行语料的译法统计（后台任务）：取查询命中句的对齐译文句，统计译文中各词出现的句数，按 Dice 或 LL 排序，返回 stat_id 与前 50 行（译文词、共现句数、占命中句 %、目标侧句数、Dice、LL；totals 含 hit_sentences、aligned_sentences、unaligned）。用户问“某词怎么译”“有哪些译法”“对应的英文 / 中文”时用它；只用于平行语料（corpora_list 中 parallel 为 true），否则返回 NOT_PARALLEL。scope 一般用源语言一侧。每行的 search_query 与 search_aligned 可打开含该译法的例句；要比较几种译法的数量或分布，用 corpus_search / stats_distribution 加 aligned 条件。',
      parameters: Type.Object({
        scope: ScopeArg,
        query: Type.String({ minLength: 1, description: '源语言一侧的查询式，如 "翻译"' }),
        unit: oneOf(['word', 'lemma']),
        target_language: Type.Optional(Type.String({ description: '译文语言代码，如 en；省略时取平行语料中与命中句不同的一侧' })),
        measure: oneOf(['dice', 'll']),
        top: positiveInt(),
        min_freq: positiveInt(),
        exclude_punct: Type.Optional(Type.Boolean({ description: '排除标点，默认 true' })),
      }),
      run: (args, signal) => runStat('/stats/translations', {
        scope: resolveScope(args.scope), query: args.query, unit: args.unit ?? 'word',
        ...(args.target_language ? { target_language: args.target_language } : {}),
        measure: args.measure ?? 'dice', top: args.top ?? 100, min_freq: args.min_freq ?? 2, exclude_punct: args.exclude_punct ?? true,
      }, signal),
    }),
    spec({
      name: 'stats.ngrams',
      description: 'n-gram 统计（后台任务），返回 stat_id 与前 50 行。',
      parameters: Type.Object({
        scope: ScopeArg,
        n: Type.Union([Type.Literal(2), Type.Literal(3), Type.Literal(4)]),
        unit: oneOf(['word', 'lemma']),
        pos_pattern: Type.Optional(Type.Array(Type.String(), { description: '词性序列，如 ["v","n"]' })),
        top: positiveInt(),
        min_freq: positiveInt(),
      }),
      run: (args, signal) => runStat('/stats/ngrams', {
        scope: resolveScope(args.scope), n: args.n, unit: args.unit ?? 'word', pos_pattern: args.pos_pattern,
        top: args.top ?? 200, min_freq: args.min_freq ?? 2,
      }, signal),
    }),
    spec({
      name: 'stats.collocations',
      description: '搭配统计（后台任务）：node 为节点查询式，返回 stat_id 与前 50 行。measures 可选 mi、logdice、t、ll（默认这四项），以及 mi3（MI³，偏向高频搭配）、delta_p（ΔP，有方向：delta_p_node = P(搭配词|节点) − P(搭配词|非节点)，delta_p_coll 反向）、z（z-score）；用户点名某个指标或问搭配的方向性时再加。',
      parameters: Type.Object({
        scope: ScopeArg,
        node: Type.String({ minLength: 1 }),
        window: Type.Optional(Type.Integer({ minimum: 1, maximum: 10 })),
        unit: oneOf(['word', 'lemma']),
        pos: Type.Optional(Type.String({ description: '只保留该词性的搭配词' })),
        measures: Type.Optional(Type.Array(Type.Union(['mi', 'logdice', 't', 'll', 'mi3', 'delta_p', 'z'].map(value => Type.Literal(value))))),
        min_freq: positiveInt(),
        top: positiveInt(),
      }),
      run: (args, signal) => runStat('/stats/collocations', {
        scope: resolveScope(args.scope), node: args.node, window: args.window ?? 5, unit: args.unit ?? 'word', pos: args.pos,
        measures: args.measures ?? ['mi', 'logdice', 't', 'll'], min_freq: args.min_freq ?? 3, top: args.top ?? 200,
      }, signal),
    }),
    spec({
      name: 'stats.keywords',
      description: '关键词与两库对比（后台任务）：target 相对 reference，返回 stat_id 与前 50 行。列含 LL、log ratio 及其 95% 置信区间（log_ratio_ci_low / log_ratio_ci_high）、%DIFF（pct_diff）、odds ratio、Bonferroni 校正后的显著性。measure 为排序指标：ll（默认）、log_ratio、pct_diff、odds_ratio。direction：positive 目标库显著多用的词（默认）、negative 参照库多用的词、both 两者。只比较指定的几个词在两库的用量时传 items（≤ 50 个词），此时忽略 min_freq 与 direction。',
      parameters: Type.Object({
        target: ScopeArg,
        reference: scopeObject(),
        unit: oneOf(['word', 'lemma']),
        measure: oneOf(['ll', 'log_ratio', 'pct_diff', 'odds_ratio']),
        direction: oneOf(['positive', 'negative', 'both']),
        items: Type.Optional(Type.Array(Type.String({ minLength: 1 }), { minItems: 1, maxItems: 50, description: '只返回这些词的行' })),
        min_freq: positiveInt(),
        top: positiveInt(),
      }),
      run: (args, signal) => {
        const ref = args.reference;
        const reference = ref.subcorpus_id ? { subcorpus_id: ref.subcorpus_id } : ref.corpus_id ? { corpus_id: ref.corpus_id } : null;
        if (!reference) throw new Error('REFERENCE_REQUIRED: reference 需要 corpus_id 或 subcorpus_id');
        return runStat('/stats/keywords', {
          target: resolveScope(args.target), reference, unit: args.unit ?? 'word', measure: args.measure ?? 'll',
          min_freq: args.min_freq ?? 3, top: args.top ?? 200,
          ...(args.direction ? { direction: args.direction } : {}), ...(args.items ? { items: args.items } : {}),
        }, signal);
      },
    }),
    spec({
      name: 'stats.distribution',
      description: '命中在元数据字段（如 year）或文本位置（field="position"）上的分布（后台任务），返回 stat_id 与各区间。平行语料可加 aligned 译文条件，比较某种译法的分布。',
      parameters: Type.Object({
        scope: ScopeArg,
        query: Type.Optional(Type.String()),
        field: Type.String({ minLength: 1 }),
        bins: Type.Optional(Type.Integer({ minimum: 2, maximum: 50 })),
        aligned: AlignedArg,
      }),
      run: (args, signal) => runStat('/stats/distribution', {
        scope: resolveScope(args.scope), query: args.query, field: args.field, bins: args.bins, ...alignedBody(args.aligned),
      }, signal),
    }),
    // ---- P10 research tools (contracts/p10.md §一–六)
    spec({
      name: 'stats.text_metrics',
      description: '文本指标（后台任务）：每篇文档一行——词数、句数、TTR、STTR（每 sttr_window 词一段）、MTLD、词汇密度、平均句长、平均依存距离，英文另有 Flesch Reading Ease 与 Flesch-Kincaid Grade；返回 stat_id 与前 50 行，totals.notes 说明哪些值为 null 及原因（如词数不足 100 时 STTR、MTLD 为 null）。用户问“词汇丰富度 / 多样性”“句子长度、句法复杂度”“可读性”“学习者作文的复杂度”“几组文本的指标差异”时用它；group_by 按元数据字段（如学习者水平、体裁）另给分组均值与标准差（totals.groups）。',
      parameters: Type.Object({
        scope: ScopeArg,
        metrics: Type.Optional(Type.Array(Type.String({ minLength: 1 }), { minItems: 1, description: '只算这些指标；一般省略（全部）' })),
        group_by: Type.Optional(Type.String({ minLength: 1, description: '分组汇总所用的元数据字段，如 level' })),
        sttr_window: positiveInt(),
      }),
      run: (args, signal) => runStat('/stats/text_metrics', {
        scope: resolveScope(args.scope), ...(args.metrics ? { metrics: args.metrics } : {}),
        ...(args.group_by ? { group_by: args.group_by } : {}), sttr_window: args.sttr_window ?? 1000,
      }, signal),
    }),
    spec({
      name: 'vocab.lists',
      description: '列出可用词表（内置 NGSL 与本项目上传的词表）：list_id、名称、语言、等级顺序、来源与许可。做词汇等级画像（stats_vocab_profile）前用它选词表；中文 HSK、AWL 等词表不内置，没有时请用户在统计页“词汇等级”处上传。',
      parameters: Type.Object({}),
      run: async (_args, signal) => {
        const items = listItems(await api.get<any>(`/projects/${seg(projectId)}/vocab-lists`, signal));
        return {
          data: {
            total: items.length,
            items: items.map((list: any) => ({
              list_id: list.id, name: list.name, language: list.language, levels: list.levels ?? [], builtin: list.builtin ?? list.project_id === null,
              source: list.source ?? null, license: list.license ?? null,
            })),
          },
          summary: `${items.length} 个词表`,
        };
      },
    }),
    spec({
      name: 'stats.vocab_profile',
      description: '词汇等级画像（后台任务）：按词表统计各等级的词次、词种、词次覆盖率 %，另有“表外”一行。by=corpus 整个范围（默认）；by=document 每篇一行、各等级覆盖率；by=<元数据字段> 按字段值分组。返回 stat_id 与前 50 行；等级行的 search_query 可打开该等级词的例句（词太多时为 null）。用户问“用词难度 / 词汇等级分布”“NGSL / HSK 覆盖率”“表外词有哪些”时用它；list_id 取自 vocab_lists。',
      parameters: Type.Object({
        scope: ScopeArg,
        list_id: Type.String({ minLength: 1, description: '词表 list_id，取自 vocab_lists' }),
        by: Type.Optional(Type.String({ minLength: 1, description: 'corpus | document | <元数据字段>' })),
      }),
      run: (args, signal) => runStat('/stats/vocab_profile', {
        scope: resolveScope(args.scope), list_id: args.list_id, by: args.by ?? 'corpus',
      }, signal),
    }),
    spec({
      name: 'stats.compare',
      description: '多项对比与历时（后台任务）：2–10 项，每项 label、query、可选 scope（省略用会话范围；可以同一查询比较不同子库，或同一范围比较不同查询）。不带 by：每项一行——命中数、词数、每百万词、文档数、文档频率 %，恰两项时附 LL 与 log ratio。带 by（元数据字段，如 year、genre）：每个字段值一行，列为各项的每百万词，用于看趋势。test：mann_whitney 恰两项时按文档比较（U、z、p、效应量 r）；spearman 在 by 为数值字段时给每项与该字段的秩相关（ρ、p、n）。返回 stat_id 与前 50 行，行的 search_query、search_scope 可打开例句。用户问“A 和 B 哪个更常用”“几个词或几个子库的用量比较”“某词随年代的变化”“差异是否显著”时用它；两库之间全词表比较用 stats_keywords。',
      parameters: Type.Object({
        items: Type.Array(Type.Object({
          label: Type.String({ minLength: 1, description: '该项的显示名' }),
          query: Type.String({ minLength: 1, description: '查询式，与检索相同' }),
          scope: ScopeArg,
        }), { minItems: 2, maxItems: 10 }),
        by: Type.Optional(Type.String({ minLength: 1, description: '元数据字段，如 year；省略则每项一行' })),
        test: oneOf(['none', 'mann_whitney', 'spearman']),
      }),
      run: (args, signal) => runStat('/stats/compare', {
        items: args.items.map(item => ({ label: item.label, scope: resolveScope(item.scope), query: item.query })),
        by: args.by ?? null, test: args.test ?? 'none',
      }, signal),
    }),
    spec({
      name: 'stats.word_sketch',
      description: 'Word Sketch 词汇画像（后台任务）：按 UD 依存关系分栏列出一个词元的搭配——主语、宾语、修饰 / 被修饰、并列、介词短语（如 with + N）、作主语的谓词等；每栏搭配词元、共现频次、logDice（按该关系计）。返回 stat_id 与按栏分组的 relations（每栏前 10 个；totals.relations 为全部栏名），行的 search_query 可打开例句（null 表示无法回到检索）。用户问“某词按语法关系常和哪些词搭配”“某动词常带什么宾语”“某名词常被什么形容词修饰”时用它；只看窗口内共现用 stats_collocations。英文语料自带依存；中文语料要用依存标注层（layers.dep，省略则用该语料最新的依存层），没有时返回 NO_DEPENDENCIES，请用户先在标注页建依存层。',
      parameters: Type.Object({
        scope: ScopeArg,
        lemma: Type.String({ minLength: 1, description: '节点词元，如 make' }),
        pos: Type.Optional(Type.String({ description: '节点词性（UPOS），如 NOUN、VERB、ADJ' })),
        layers: Type.Optional(Type.Object({ dep: Type.Optional(Type.String()) }, { description: '依存标注层 layer_id；一般省略' })),
        min_freq: positiveInt(),
        top: positiveInt(),
      }),
      run: (args, signal) => runStat('/stats/word_sketch', {
        scope: resolveScope(args.scope), lemma: args.lemma, ...(args.pos ? { pos: args.pos } : {}),
        ...(args.layers ? { layers: args.layers } : {}), min_freq: args.min_freq ?? 2, top: args.top ?? 25,
      }, signal, byRelation),
    }),
    spec({
      name: 'stats.sketch_diff',
      description: '近义词对比（Sketch Diff，后台任务）：两个词元在各依存关系栏的共同与独有搭配，每行 relation、搭配词元、freq_a、freq_b、logdice_a、logdice_b、diff（logDice 差，A 减 B）。返回 stat_id 与分好的 sides：a（偏 A）、common（共同）、b（偏 B），每组按差异最明显的前 15 个，side_totals 为各组全部行数，side_totals.total 为全部搭配数，回答中说总数时用它（SketchDiff 卡按 stat_id 显示全部行）。用户问“A 和 B 的用法有什么区别”“近义词辨析”时用它；依存要求同 stats_word_sketch。',
      parameters: Type.Object({
        scope: ScopeArg,
        lemma_a: Type.String({ minLength: 1 }),
        lemma_b: Type.String({ minLength: 1 }),
        pos: Type.Optional(Type.String({ description: '两个词元的词性（UPOS），如 ADJ' })),
        layers: Type.Optional(Type.Object({ dep: Type.Optional(Type.String()) }, { description: '依存标注层 layer_id；一般省略' })),
        min_freq: positiveInt(),
        top: positiveInt(),
      }),
      run: (args, signal) => runStat('/stats/sketch_diff', {
        scope: resolveScope(args.scope), lemma_a: args.lemma_a, lemma_b: args.lemma_b, ...(args.pos ? { pos: args.pos } : {}),
        ...(args.layers ? { layers: args.layers } : {}), min_freq: args.min_freq ?? 2, top: args.top ?? 25,
      }, signal, bySide),
    }),
    spec({
      name: 'search.semantic',
      description: `语义检索：按句子语义相似度（余弦）找与一句话意思相近的句子，返回最相近的前 ${MAX_SEMANTIC_HITS} 句与相似度 score（越接近 1 越相近）。用户要“找意思相近的句子”“类似表达 / 换种说法的例句”、或按词形检索查不到的同义表述时用它；要准确计数或限定词形时用 corpus_search。相似度只表示相近程度，不能当作命中计数。返回 SEMANTIC_NOT_READY（未建语义索引）或 SEMANTIC_MODEL_CHANGED（需重建）时，请用户在语料库页建语义索引，助手不建索引。`,
      parameters: Type.Object({
        scope: ScopeArg,
        text: Type.String({ minLength: 1, maxLength: 500, description: '一句话，≤ 500 字' }),
        top: positiveInt(),
      }),
      run: async (args, signal) => {
        const scope = resolveScope(args.scope);
        const result = await api.post<any>('/search/semantic', { scope, text: args.text, top: args.top ?? 50 }, signal);
        const items = listItems(result);
        const hits = items.slice(0, MAX_SEMANTIC_HITS).map((hit: any) => ({
          hit_id: hit.hit_id, sentence_index: hit.sentence_index, left: hit.left ?? '', match: hit.match ?? '', right: hit.right ?? '',
          source: hit.document_title ?? '', score: hit.score,
        }));
        const documents = new Set(items.map((hit: any) => String(hit.hit_id ?? '').split(':')[0])).size;
        return {
          data: {
            text: args.text, scope, scope_name: await scopeName(scope, signal).catch(() => ''),
            counts: { hits: items.length, sentences: items.length, documents }, hits,
          },
          summary: `语义相近 ${items.length} 句`,
        };
      },
    }),
    spec({
      name: 'methods.appendix',
      description: '生成论文方法部分的附录草稿（Markdown）：语料规模与版本、处理工具、检索式与计数、统计方法的全部参数与公式出处、标注与抽样情况、参考文献条目。用户要“写方法部分”“方法说明”“怎么引用语料 / 平台”“列出统计方法的文献”时用它。来源三选：stat_ids（统计结果的 stat_id）、searches（[{query, scope, aligned?}]）、layer_ids（标注层，含抽样层）；evidence=true 时从证据篮收集。style：gbt7714（默认）或 apa。返回 markdown 与 citations，不生成文件。',
      parameters: Type.Object({
        stat_ids: Type.Optional(Type.Array(Type.String(), { minItems: 1 })),
        searches: Type.Optional(Type.Array(Type.Object({ query: Type.String({ minLength: 1 }), scope: ScopeArg, aligned: AlignedArg }), { minItems: 1 })),
        layer_ids: Type.Optional(Type.Array(Type.String(), { minItems: 1 })),
        evidence: Type.Optional(Type.Boolean({ description: '从项目证据篮收集统计与检索' })),
        style: oneOf(['gbt7714', 'apa']),
      }),
      run: async (args, signal) => {
        if (!args.stat_ids && !args.searches && !args.layer_ids && !args.evidence) {
          throw new Error('SOURCE_REQUIRED: 需要 stat_ids、searches、layer_ids 或 evidence=true 之一');
        }
        const result = await api.post<any>(`/projects/${projectId}/method-appendix`, {
          ...(args.stat_ids ? { stat_ids: args.stat_ids } : {}),
          ...(args.searches ? {
            searches: args.searches.map(s => ({ query: s.query, scope: resolveScope(s.scope), ...alignedBody(s.aligned) })),
          } : {}),
          ...(args.layer_ids ? { layer_ids: args.layer_ids } : {}),
          ...(args.evidence !== undefined ? { evidence: args.evidence } : {}),
          style: args.style ?? 'gbt7714',
        }, signal);
        const markdown = String(result?.markdown ?? '');
        return {
          data: {
            markdown: clip(markdown, MAX_APPENDIX_CHARS), citations: result?.citations ?? [],
            note: '附录由平台按实际参数生成；原样给用户，不改动其中的数字与文献。',
          },
          summary: `方法附录：${markdown.length} 字，${(result?.citations ?? []).length} 条引用`,
        };
      },
    }),
    spec({
      name: 'sample.create',
      description: '检索结果抽样编码：从一个查询的全部命中中按 seed 等概率无放回抽 n 条，新建一个片段层（抽样层），每条命中一个待编码片段，由用户在标注页逐条编码。用户明确要求“抽样”“抽 n 条来编码 / 人工分类”时用它。label_set_id 或 label_set_name 指定片段标签集（都省略时报错并列出可用标签集）；seed 省略则随机生成并记录。命中计数未完成或超过上限时返回 SEARCH_INCOMPLETE。',
      parameters: Type.Object({
        query: Type.String({ minLength: 1 }),
        scope: ScopeArg,
        aligned: AlignedArg,
        n: Type.Integer({ minimum: 1, maximum: 500 }),
        seed: Type.Optional(Type.Integer()),
        layer_name: Type.String({ minLength: 1, description: '新抽样层名称' }),
        label_set_id: Type.Optional(Type.String()),
        label_set_name: Type.Optional(Type.String({ minLength: 1 })),
      }),
      confirm: async (args, signal) => {
        const labelSet = await spanLabelSet(args, signal);
        return {
          title: `抽样编码：新建抽样层「${args.layer_name}」`,
          lines: [
            `查询式：${args.query}`, await scopeLine(resolveScope(args.scope), signal), ...alignedLine(args.aligned),
            `抽样：${args.n} 条${args.seed !== undefined ? `，seed ${args.seed}` : ''}`, `标签集：${labelSet.name}`,
          ],
        };
      },
      run: async (args, signal) => {
        const labelSet = await spanLabelSet(args, signal);
        const result = await api.post<any>(`/projects/${projectId}/samples`, {
          scope: resolveScope(args.scope), query: args.query, ...alignedBody(args.aligned), n: args.n,
          ...(args.seed !== undefined ? { seed: args.seed } : {}),
          layer: { name: args.layer_name, label_set_id: labelSet.id },
        }, signal);
        return {
          data: {
            layer_id: result.layer_id, layer_name: args.layer_name, label_set: labelSet.name, sampled: result.sampled, total: result.total,
            note: '片段均未编码，由用户在标注页抽样模式中编码；汇总用 sample_summary。',
          },
          summary: `已抽样 ${result.sampled} / ${result.total} 条`,
          ref: { kind: 'layer', id: String(result.layer_id) },
        };
      },
    }),
    spec({
      name: 'sample.summary',
      description: '抽样层的编码汇总：总命中数、抽样数、已编码数、拒绝数，以及各标签的条数、比例（以已编码且未拒绝为分母）、95% Wilson 区间（ci_low / ci_high）和估计命中数 estimate（= 比例 × 总命中，属估计值，回答中注明“估计”）。用户问抽样编码的结果、比例或置信区间时用它。',
      parameters: Type.Object({ layer_id: Type.String() }),
      run: async (args, signal) => {
        const summary = await api.get<any>(`/layers/${seg(args.layer_id)}/sample-summary`, signal);
        return {
          data: { layer_id: args.layer_id, ...summary },
          summary: `已编码 ${summary.coded ?? 0} / 抽样 ${summary.sampled ?? 0}`,
          ref: { kind: 'layer', id: args.layer_id },
        };
      },
    }),
    spec({
      name: 'evidence.add',
      description: '把命中、统计行或一段文字钉入项目证据篮。',
      parameters: Type.Object({
        kind: Type.Union([Type.Literal('hit'), Type.Literal('stat_row'), Type.Literal('text')]),
        ref: Type.Object({
          search_query: Type.Optional(Type.String()),
          scope: ScopeArg,
          hit_id: Type.Optional(Type.String()),
          document_id: Type.Optional(Type.String()),
          start_cp: Type.Optional(Type.Integer()),
          end_cp: Type.Optional(Type.Integer()),
          stat_id: Type.Optional(Type.String()),
          row_key: Type.Optional(Type.String()),
        }),
        text: Type.String({ minLength: 1 }),
        source: Type.String({ description: '出处，如文档标题或统计名称' }),
        note: Type.Optional(Type.String()),
      }),
      confirm: async args => ({ title: '加入证据篮', lines: [clip(args.text, 120), `出处：${args.source}`] }),
      run: async (args, signal) => {
        const item = await api.post<any>(`/projects/${projectId}/evidence`, args, signal);
        return {
          data: { evidence_id: item.id, kind: item.kind, text: item.text, source: item.source, ...(item.existing ? { note: '证据篮里已有这条，未重复加入' } : {}) },
          summary: item.existing ? '证据篮里已有' : '已加入证据篮',
          ref: { kind: 'evidence', id: item.id },
        };
      },
    }),
    spec({
      name: 'evidence.list',
      description: '列出项目证据篮。',
      parameters: Type.Object({}),
      run: async (_args, signal) => {
        const page = await api.get<{ items: any[]; total: number }>(`/projects/${projectId}/evidence${query({ page_size: 200 })}`, signal);
        return {
          data: {
            total: page.total,
            items: page.items.map(e => ({ evidence_id: e.id, kind: e.kind, text: String(e.text).slice(0, 200), source: e.source, note: e.note, ref: e.ref })),
          },
          summary: `${page.total} 条证据`,
        };
      },
    }),
    spec({
      name: 'queries.save',
      description: '保存查询式到项目。',
      parameters: Type.Object({ name: Type.String({ minLength: 1 }), query: Type.String({ minLength: 1 }), scope: ScopeArg }),
      confirm: async (args, signal) => ({
        title: `保存查询「${args.name}」`, lines: [`查询式：${args.query}`, await scopeLine(resolveScope(args.scope), signal)],
      }),
      run: async (args, signal) => {
        const saved = await api.post<any>(`/projects/${projectId}/queries`, { name: args.name, query: args.query, scope: resolveScope(args.scope) }, signal);
        return { data: saved, summary: `已保存查询 ${saved.name}`, ref: { kind: 'query', id: saved.id } };
      },
    }),
    spec({
      name: 'queries.list',
      description: '列出项目已保存的查询。',
      parameters: Type.Object({}),
      run: async (_args, signal) => {
        const page = await api.get<{ items: any[]; total: number }>(`/projects/${projectId}/queries${query({ page_size: 200 })}`, signal);
        return { data: page, summary: `${page.total} 条查询` };
      },
    }),
    spec({
      name: 'export.create',
      description: '提交导出任务：target=search 导出检索结果（需 query，可选 scope）；target=stat 导出统计结果（需 stat_id）。返回 job_id。',
      parameters: Type.Object({
        target: Type.Union([Type.Literal('search'), Type.Literal('stat')]),
        format: Type.Union([Type.Literal('csv'), Type.Literal('xlsx')]),
        query: Type.Optional(Type.String()),
        scope: ScopeArg,
        stat_id: Type.Optional(Type.String()),
      }),
      confirm: async (args, signal) => {
        const format = args.format.toUpperCase();
        if (args.target === 'stat') {
          if (!args.stat_id) throw new Error('STAT_ID_REQUIRED: 导出统计结果需要 stat_id');
          const stat = await api.get<any>(`/stats/${seg(args.stat_id)}`, signal);
          return { title: `导出统计结果（${format}）`, lines: [`${METHOD_NAMES[stat.method] ?? '统计'}：${stat.row_count ?? 0} 行`, `范围：${stat.scope?.name ?? ''}`] };
        }
        if (!args.query) throw new Error('QUERY_REQUIRED: 导出检索结果需要 query');
        return { title: `导出检索结果（${format}）`, lines: [`查询式：${args.query}`, await scopeLine(resolveScope(args.scope), signal)] };
      },
      run: async (args, signal) => {
        let job: Job;
        if (args.target === 'stat') {
          if (!args.stat_id) throw new Error('STAT_ID_REQUIRED: 导出统计结果需要 stat_id');
          job = await api.post<Job>(`/stats/${args.stat_id}/export`, { format: args.format }, signal);
        } else {
          if (!args.query) throw new Error('QUERY_REQUIRED: 导出检索结果需要 query');
          job = await api.post<Job>('/search/export', {
            scope: resolveScope(args.scope), query: args.query, context: { unit: 'char', size: 40 }, sort: 'position',
            page: 1, page_size: 50, format: args.format, project_id: projectId,
          }, signal);
        }
        return { data: compactJob(job), summary: '已提交导出任务', ref: { kind: 'job', id: job.id } };
      },
    }),
    spec({
      name: 'export.tidy',
      description: '整洁数据导出（后台任务）：每篇文档一行，列为文档元数据、词数、句数，每个查询（≤ 10 个）两列：命中数与每百万词；metrics=true 时附文本指标；另附列说明（codebook），可直接用 R / pandas 读取做回归或混合模型。用户明确要求“导出数据表”“导出给 R / SPSS / pandas 分析”时用它。返回任务：文件由用户在任务页下载，不要自己生成文件内容。',
      parameters: Type.Object({
        scope: ScopeArg,
        queries: Type.Optional(Type.Array(Type.String({ minLength: 1 }), { minItems: 1, maxItems: 10, description: '每个查询两列计数' })),
        metrics: Type.Optional(Type.Boolean({ description: '附文本指标列，默认 false' })),
        format: Type.Union([Type.Literal('csv'), Type.Literal('xlsx')]),
      }),
      confirm: async (args, signal) => ({
        title: `导出整洁数据（${args.format.toUpperCase()}）`,
        lines: [
          await scopeLine(resolveScope(args.scope), signal),
          ...(args.queries ? [`查询：${args.queries.join('；')}`] : []),
          ...(args.metrics ? ['附文本指标'] : []),
        ],
      }),
      run: async (args, signal) => {
        const job = await api.post<Job>('/stats/tidy_export', {
          scope: resolveScope(args.scope), ...(args.queries ? { queries: args.queries } : {}), metrics: args.metrics ?? false, format: args.format,
        }, signal);
        return {
          data: { ...compactJob(job), note: '文件生成后由用户在任务页下载；用 JobStatus 组件告知，不复述文件内容。' },
          summary: '已提交整洁数据导出',
          ref: { kind: 'job', id: job.id },
        };
      },
    }),
    spec({
      name: 'skills.read',
      description: '读取一个研究流程文件（available_skills 中的 location，或流程名）。只能读取研究流程。',
      parameters: Type.Object({ path: Type.String({ minLength: 1, description: '流程文件的 location 或流程名' }) }),
      run: async args => {
        const skill = findSkill(args.path);
        if (!skill) {
          const names = researchSkills().skills.map(item => item.name).join('、') || '无';
          throw new Error(`SKILL_NOT_FOUND: 只能读取研究流程：${names}`);
        }
        const { title, content } = readSkill(skill);
        return { data: { name: skill.name, title, content }, summary: `研究流程：${title}` };
      },
    }),
    spec({
      name: 'jobs.get',
      description: '查询后台任务状态。',
      parameters: Type.Object({ job_id: Type.String() }),
      run: async (args, signal) => {
        const job = await api.get<Job>(`/jobs/${args.job_id}`, signal);
        return { data: compactJob(job), summary: `任务 ${job.state}`, ref: { kind: 'job', id: job.id } };
      },
    }),
    spec({
      name: 'jobs.cancel',
      description: '取消后台任务。',
      parameters: Type.Object({ job_id: Type.String() }),
      confirm: async (args, signal) => {
        const job = await api.get<any>(`/jobs/${seg(args.job_id)}`, signal);
        return { title: '取消后台任务', lines: [String(job.summary || job.kind), `状态：${job.state}`] };
      },
      run: async (args, signal) => {
        const job = await api.post<Job>(`/jobs/${args.job_id}/cancel`, {}, signal);
        return { data: compactJob(job), summary: `任务 ${job.state}`, ref: { kind: 'job', id: job.id } };
      },
    }),
    spec({
      name: 'annot.layers',
      description: `列出项目标注层（pos、dep、span、relation、alignment）与校对进度；每层附文档列表 documents（按语料顺序，最多 ${MAX_LAYER_DOCS} 个，document_ordinal 即其中的 1 起序号）。`,
      parameters: Type.Object({ corpus_id: Type.Optional(Type.String()) }),
      run: async (args, signal) => {
        const items = listItems(await api.get<any>(`/projects/${projectId}/layers${query({ corpus_id: args.corpus_id })}`, signal));
        const layersOut = await Promise.all(items.map(async layer => {
          layers.set(layer.id, layer);
          const docs = await getLayerDocs(layer.id, signal);
          return { ...compactLayer(layer), document_count: docs.length, documents: docs.slice(0, MAX_LAYER_DOCS) };
        }));
        return { data: { total: items.length, items: layersOut }, summary: `${items.length} 个标注层` };
      },
    }),
    spec({
      name: 'annot.create_layer',
      description: '为本项目语料库建立标注层并自动预标（后台任务，最多等待 90 秒）。kind=pos 词性、dep 依存；label_set_id 省略时用内置标签集；document_ids 限定文档（用户说“这篇文档”时必须传）。不能用于内置语料。只在用户明确要求建层时调用。',
      parameters: Type.Object({
        corpus_id: Type.String(),
        kind: Type.Union([Type.Literal('pos'), Type.Literal('dep')]),
        name: Type.String({ minLength: 1 }),
        label_set_id: Type.Optional(Type.String()),
        document_ids: Type.Optional(Type.Array(Type.String(), { minItems: 1 })),
      }),
      confirm: async (args, signal) => {
        const corpus = await projectCorpus(args.corpus_id, signal);
        const labelSetId = args.label_set_id ?? await defaultLabelSet(args.corpus_id, args.kind, signal);
        const sets = listItems(await api.get<any>(`/label-sets${query({ project_id: projectId, kind: args.kind })}`, signal).catch(() => []));
        const labelSet = sets.find((set: any) => set.id === labelSetId)?.name ?? '';
        const docs = corpus.stats?.documents ?? null;
        const lines = [`语料库：${corpus.name}`];
        if (args.document_ids) lines.push(`文档：${args.document_ids.length} 篇`);
        else lines.push(`文档：全部${docs !== null ? ` ${docs} 篇` : ''}${corpus.stats?.tokens ? `，约 ${corpus.stats.tokens} 词` : ''}`);
        if (labelSet) lines.push(`标签集：${labelSet}`);
        return { title: `新建${args.kind === 'pos' ? '词性' : '依存'}标注层「${args.name}」并预标`, lines };
      },
      run: async (args, signal) => {
        await projectCorpus(args.corpus_id, signal);
        const labelSetId = args.label_set_id ?? await defaultLabelSet(args.corpus_id, args.kind, signal);
        let layer = await api.post<any>(`/projects/${projectId}/layers`, {
          corpus_id: args.corpus_id, kind: args.kind, name: args.name, label_set_id: labelSetId,
          ...(args.document_ids ? { document_ids: args.document_ids } : {}),
        }, signal);
        const ref = { kind: 'layer', id: layer.id };
        if (!layer.job_id) return { data: compactLayer(layer), summary: `标注层 ${layer.name}：${layer.status}`, ref };
        const job = await waitJob(await api.get<Job>(`/jobs/${seg(layer.job_id)}`, signal), signal);
        if (job.state === 'failed' || job.state === 'cancelled') {
          throw new Error(`${job.error?.code ?? 'JOB_' + job.state.toUpperCase()}: ${job.error?.message ?? '预标任务未成功'}（layer_id ${layer.id}）`);
        }
        layer = await api.get<any>(`/layers/${seg(layer.id)}`, signal);
        layers.set(layer.id, layer);
        if (job.state !== 'succeeded') {
          return {
            data: {
              ...compactLayer(layer), job: compactJob(job),
              note: `预标等待超过 ${Math.round(ctx.jobWaitMs / 1000)} 秒仍未完成，请用户到任务页查看；不要重复建层。`,
            },
            summary: `标注层 ${layer.name} 预标中`,
            ref: { kind: 'job', id: job.id },
          };
        }
        return { data: compactLayer(layer), summary: `标注层 ${layer.name}：${layer.status}`, ref };
      },
    }),
    spec({
      name: 'annot.sentence',
      description: '读取标注层中的一句：每个 token 的系统值 system（pos/head/deprel）、该层标注 annotation 和有效值 effective（confirmed/modified 的标注优先，否则系统值）。head 为句内 token 序号，0 为根。文档用 document_id、document_title 或 document_ordinal（annot_layers 中 documents 的 1 起序号）之一指定；都省略时用该层第一个文档。',
      parameters: Type.Object({
        layer_id: Type.String(),
        document_id: Type.Optional(Type.String()),
        document_title: Type.Optional(Type.String({ minLength: 1 })),
        document_ordinal: Type.Optional(Type.Integer({ minimum: 1 })),
        sentence_index: Type.Integer({ minimum: 0 }),
      }),
      run: async (args, signal) => {
        const layer = await getLayer(args.layer_id, signal);
        const doc = await resolveDocument(args.layer_id, args, signal);
        const sentence = await api.get<any>(
          `/layers/${seg(args.layer_id)}/sentences/${seg(doc.document_id)}/${seg(args.sentence_index)}`, signal);
        const byToken = new Map<number, any>((sentence.annotations ?? []).map((a: any) => [a.token_index, a]));
        const tokens = (sentence.tokens ?? []).map((token: any) => {
          const system = { pos: token.system?.pos ?? null, head: token.system?.head ?? null, deprel: token.system?.deprel ?? null };
          const annot = byToken.get(token.index);
          const effective = { ...system };
          if (annot && EFFECTIVE.has(annot.status)) {
            if (layer.kind === 'dep') { effective.head = annot.head; effective.deprel = annot.label; } else effective.pos = annot.label;
          } else if (annot?.status === 'rejected' && layer.kind === 'pos') effective.pos = null;
          return {
            index: token.index, form: token.form, system,
            annotation: annot ? {
              label: annot.label, head: annot.head, model_label: annot.model_label, model_head: annot.model_head,
              status: annot.status, source: annot.source,
            } : null,
            effective,
          };
        });
        return {
          data: {
            layer_id: args.layer_id, layer_kind: layer.kind, document_id: sentence.document_id ?? doc.document_id,
            ...(doc.title !== null ? { document_title: doc.title } : {}), ...(doc.note ? { note: doc.note } : {}),
            sentence_index: sentence.sentence_index ?? args.sentence_index, text: sentence.text, status: sentence.status, tokens,
          },
          summary: `第 ${args.sentence_index + 1} 句，${tokens.length} 个词`,
          ref: { kind: 'layer', id: args.layer_id },
        };
      },
    }),
    spec({
      name: 'annot.diff',
      description: `标注层预标与人工结果的差异：计数与前 ${MAX_DIFF_SENTENCES} 个有改动的句子（model 为预标值，human 为人工值，dep 层写作 "关系→head"）。`,
      parameters: Type.Object({
        layer_id: Type.String(),
        document_id: Type.Optional(Type.String()),
      }),
      run: async (args, signal) => {
        const layer = await getLayer(args.layer_id, signal);
        const diff = await api.get<any>(
          `/layers/${seg(args.layer_id)}/diff${query({ document_id: args.document_id, only_changed: 'true' })}`, signal);
        const items: any[] = diff.items ?? [];
        const sentences = items.slice(0, MAX_DIFF_SENTENCES).map(sentence => {
          const forms = new Map<number, string>((sentence.tokens ?? []).map((t: any) => [t.index, t.form]));
          return {
            document_id: sentence.document_id, sentence_index: sentence.sentence_index, text: sentence.text,
            changes: (sentence.annotations ?? [])
              .filter((a: any) => a.status === 'modified' || a.status === 'rejected')
              .map((a: any) => ({
                token_index: a.token_index, form: forms.get(a.token_index) ?? '',
                model: annotValue(layer.kind, a.model_label, a.model_head),
                human: a.status === 'rejected' ? '' : annotValue(layer.kind, a.label, a.head),
                status: a.status,
              })),
          };
        });
        const counts = diff.counts ?? {};
        return {
          data: { layer_id: args.layer_id, layer_kind: layer.kind, counts, changed_sentences: items.length, sentences },
          summary: `改动 ${counts.changed ?? 0}，确认 ${counts.confirmed ?? 0}，拒绝 ${counts.rejected ?? 0}，待校 ${counts.pending ?? 0}`,
          ref: { kind: 'layer', id: args.layer_id },
        };
      },
    }),
    spec({
      name: 'annot.stats',
      description: `标注层的标签频次（前 ${MAX_LABELS} 个，按有效标注计）与校对进度。`,
      parameters: Type.Object({ layer_id: Type.String() }),
      run: async (args, signal) => {
        const stats = await api.get<any>(`/layers/${seg(args.layer_id)}/stats`, signal);
        const labels: any[] = [...(stats.labels ?? [])].sort((a, b) => b.count - a.count);
        return {
          data: {
            layer_id: args.layer_id, progress: stats.progress, label_count: labels.length,
            labels: labels.slice(0, MAX_LABELS).map(l => ({ label: l.label, count: l.count, confirmed: l.confirmed, modified: l.modified })),
          },
          summary: `${labels.length} 个标签`,
          ref: { kind: 'layer', id: args.layer_id },
        };
      },
    }),
    spec({
      name: 'annot.suggest',
      description: '对一个 token 提出标签或 head 建议，写入为 suggested 待人工确认，不改变已确认的值。只能建议，不能确认。',
      parameters: Type.Object({
        layer_id: Type.String(),
        document_id: Type.String(),
        sentence_index: Type.Integer({ minimum: 0 }),
        token_index: Type.Integer({ minimum: 0 }),
        label: Type.Optional(Type.String()),
        head: Type.Optional(Type.Integer({ minimum: 0, description: 'dep 层：句内 token 序号，0 为根' })),
        note: Type.Optional(Type.String({ description: '建议理由' })),
      }),
      confirm: async (args, signal) => {
        if (args.label === undefined && args.head === undefined) throw new Error('LABEL_OR_HEAD_REQUIRED: 需要 label 或 head');
        const layer = await getLayer(args.layer_id, signal);
        const value = [args.label, args.head !== undefined ? `head ${args.head}` : ''].filter(Boolean).join('，');
        return {
          title: '提出标注建议（待人工确认）',
          lines: [`标注层：${layer.name}`, `第 ${args.sentence_index + 1} 句第 ${args.token_index} 个词 → ${value}`, ...(args.note ? [`理由：${args.note}`] : [])],
        };
      },
      run: async (args, signal) => {
        if (args.label === undefined && args.head === undefined) throw new Error('LABEL_OR_HEAD_REQUIRED: 需要 label 或 head');
        const { layer_id: layerId, ...body } = args;
        const annot = await api.post<any>(`/layers/${seg(layerId)}/suggest`, body, signal);
        return {
          data: {
            annotation_id: annot.id, document_id: args.document_id, sentence_index: args.sentence_index,
            token_index: annot.token_index ?? args.token_index, label: annot.label, head: annot.head, status: annot.status, source: annot.source,
          },
          summary: `已建议第 ${annot.token_index ?? args.token_index} 个词：${annot.status}`,
          ref: { kind: 'layer', id: layerId },
        };
      },
    }),
    spec({
      name: 'annot.export',
      description: '提交 CoNLL-U 导出任务（有效标注：人工结果优先，否则系统值）。返回 job_id。',
      parameters: Type.Object({
        layer_id: Type.String(),
        document_ids: Type.Optional(Type.Array(Type.String())),
      }),
      confirm: async (args, signal) => ({
        title: '导出 CoNLL-U',
        lines: [`标注层：${(await getLayer(args.layer_id, signal)).name}`, `文档：${args.document_ids ? `${args.document_ids.length} 篇` : '全部'}`],
      }),
      run: async (args, signal) => {
        const job = await api.post<Job>(`/layers/${seg(args.layer_id)}/export`, {
          format: 'conllu', ...(args.document_ids ? { document_ids: args.document_ids } : {}),
        }, signal);
        return { data: compactJob(job), summary: '已提交导出任务', ref: { kind: 'job', id: job.id } };
      },
    }),
    // ---- P5 spans, relations, alignment, agreement (contracts/p5.md §三–四)
    spec({
      name: 'annot.spans',
      description: '读取片段层中一句的片段与关系。片段 start/end 为句内码点偏移（可直接用于 SpanView），start_cp/end_cp 为文档内码点偏移；关系 from/to 为 spans 数组的 0 起下标。文档用 document_id、document_title 或 document_ordinal 之一指定；都省略时用该层第一个文档。',
      parameters: Type.Object({
        layer_id: Type.String(),
        ...DocArgs,
        sentence_index: Type.Integer({ minimum: 0 }),
      }),
      run: async (args, signal) => {
        const doc = await resolveDocument(args.layer_id, args, signal);
        const sentence = await readSpanSentence(args.layer_id, doc.document_id, args.sentence_index, signal);
        return {
          data: {
            layer_id: args.layer_id, ...compactSpanSentence(sentence),
            ...(doc.title !== null ? { document_title: doc.title } : {}), ...(doc.note ? { note: doc.note } : {}),
          },
          summary: `第 ${args.sentence_index + 1} 句，${sentence.spans?.length ?? 0} 个片段，${sentence.relations?.length ?? 0} 条关系`,
          ref: { kind: 'layer', id: args.layer_id },
        };
      },
    }),
    spec({
      name: 'annot.suggest_spans',
      description: '对一句提出片段与关系建议，写入为 suggested 待人工确认。spans 的 start_cp/end_cp 为文档内码点偏移（= annot_spans 返回的句子 start_cp + 句内偏移），必须落在该句内；relations 的 from/to 为本次 spans 的 0 起下标，或已有片段的 span_id。只能建议，不能确认。',
      parameters: Type.Object({
        layer_id: Type.String(),
        ...DocArgs,
        sentence_index: Type.Integer({ minimum: 0 }),
        spans: Type.Array(Type.Object({
          start_cp: Type.Integer({ minimum: 0 }),
          end_cp: Type.Integer({ minimum: 1 }),
          label: Type.String({ minLength: 1 }),
          attrs: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
        }), { minItems: 1, maxItems: 50 }),
        relations: Type.Optional(Type.Array(Type.Object({
          from: Type.Union([Type.Integer({ minimum: 0 }), Type.String()]),
          to: Type.Union([Type.Integer({ minimum: 0 }), Type.String()]),
          label: Type.String({ minLength: 1 }),
        }), { maxItems: 50 })),
      }),
      confirm: async (args, signal) => {
        const { sentence } = await checkSpans(args, signal);
        const layer = await getLayer(args.layer_id, signal);
        const chars = Array.from(String(sentence.text ?? ''));
        const base = Number(sentence.start_cp ?? 0);
        const spans = args.spans.map(s => `${chars.slice(s.start_cp - base, s.end_cp - base).join('')}（${s.label}）`).join('、');
        return {
          title: '提出片段建议（待人工确认）',
          lines: [`标注层：${layer.name}`, `第 ${args.sentence_index + 1} 句：${clip(spans, 160)}`,
            ...(args.relations?.length ? [`关系：${args.relations.length} 条`] : [])],
        };
      },
      run: async (args, signal) => {
        const { doc, sentence, lo } = await checkSpans(args, signal);
        const result = await api.post<any>(`/layers/${seg(args.layer_id)}/spans/suggest`, {
          document_id: doc.document_id, sentence_index: args.sentence_index, spans: args.spans,
          ...(args.relations?.length ? { relations: args.relations } : {}),
        }, signal);
        const spans = listItems(result?.spans ?? result);
        const relations: any[] = result?.relations ?? [];
        const chars = Array.from(String(sentence.text ?? ''));
        return {
          data: {
            layer_id: args.layer_id, document_id: doc.document_id, sentence_index: args.sentence_index,
            ...(doc.note ? { note: doc.note } : {}),
            spans: spans.map((s: any) => ({
              span_id: s.id, start: s.start_cp - lo, end: s.end_cp - lo, start_cp: s.start_cp, end_cp: s.end_cp,
              text: s.text ?? chars.slice(s.start_cp - lo, s.end_cp - lo).join(''), label: s.label, status: s.status, source: s.source,
            })),
            relations: relations.map((r: any) => ({
              relation_id: r.id, from_span_id: r.from_span_id, to_span_id: r.to_span_id, label: r.label, status: r.status,
            })),
            ...(result?.skipped !== undefined ? { skipped: result.skipped } : {}),
          },
          summary: `已建议 ${spans.length} 个片段、${relations.length} 条关系`,
          ref: { kind: 'layer', id: args.layer_id },
        };
      },
    }),
    spec({
      name: 'align.pairs',
      description: `读取对齐层的句对与对齐（最多 ${MAX_PAIRS} 对）。tokens 为词形列表；对齐的 src_tokens/tgt_tokens 为 1 起 token 序号（句级对齐为空）。给 src_document_id 与 src_sentence_index 时从该句开始；翻页传 next_cursor。`,
      parameters: Type.Object({
        layer_id: Type.String(),
        src_document_id: Type.Optional(Type.String()),
        src_sentence_index: Type.Optional(Type.Integer({ minimum: 0 })),
        cursor: Type.Optional(Type.String()),
      }),
      run: async (args, signal) => {
        let cursor = args.cursor;
        if (!cursor && args.src_document_id && args.src_sentence_index) cursor = `${args.src_document_id}:${args.src_sentence_index - 1}`;
        const page = await api.get<any>(`/layers/${seg(args.layer_id)}/alignments${query({
          src_document_id: args.src_document_id, cursor, page_size: MAX_PAIRS,
        })}`, signal);
        const side = (s: any) => ({
          document_id: s?.document_id, sentence_index: s?.sentence_index, text: s?.text ?? '',
          tokens: (s?.tokens ?? []).map((t: any) => typeof t === 'string' ? t : String(t?.form ?? '')),
        });
        // Each pair carries the AlignmentGraph locator fields (layer_id, src_document_id, src_sentence_index).
        const pairs = listItems(page).slice(0, MAX_PAIRS).map((pair: any) => ({
          layer_id: args.layer_id, src_document_id: pair.src?.document_id, src_sentence_index: pair.src?.sentence_index,
          src: side(pair.src), tgt: side(pair.tgt),
          alignments: (pair.alignments ?? []).map((a: any) => ({
            alignment_id: a.id, level: a.level, src_tokens: a.src_tokens ?? [], tgt_tokens: a.tgt_tokens ?? [],
            score: a.score ?? null, source: a.source, status: a.status,
          })),
        }));
        return {
          data: { layer_id: args.layer_id, pairs, next_cursor: page?.next_cursor ?? null },
          summary: `${pairs.length} 个句对`,
          ref: { kind: 'layer', id: args.layer_id },
        };
      },
    }),
    spec({
      name: 'align.suggest',
      description: '对一个句对提出词级对齐建议，写入为 suggested 待人工确认。links 中 src/tgt 为 1 起 token 序号（与 align_pairs 的 tokens 对应，一对多写成多个序号）。只能建议，不能确认。',
      parameters: Type.Object({
        layer_id: Type.String(),
        src_document_id: Type.String(),
        src_sentence_index: Type.Integer({ minimum: 0 }),
        tgt_document_id: Type.String(),
        tgt_sentence_index: Type.Integer({ minimum: 0 }),
        links: Type.Array(Type.Object({
          src: Type.Array(Type.Integer({ minimum: 1 }), { minItems: 1 }),
          tgt: Type.Array(Type.Integer({ minimum: 1 }), { minItems: 1 }),
        }), { minItems: 1, maxItems: 200 }),
      }),
      confirm: async (args, signal) => ({
        title: '提出词级对齐建议（待人工确认）',
        lines: [`对齐层：${(await getLayer(args.layer_id, signal)).name}`, `源文第 ${args.src_sentence_index + 1} 句：${args.links.length} 条连线`],
      }),
      run: async (args, signal) => {
        const { layer_id: layerId, ...body } = args;
        const result = await api.post<any>(`/layers/${seg(layerId)}/alignments/suggest`, body, signal);
        const items = Array.isArray(result) || Array.isArray(result?.items) ? listItems(result) : result ? [result] : [];
        return {
          data: {
            layer_id: layerId, src_document_id: args.src_document_id, src_sentence_index: args.src_sentence_index,
            tgt_document_id: args.tgt_document_id, tgt_sentence_index: args.tgt_sentence_index,
            alignments: items.map((a: any) => ({
              alignment_id: a.id, src_tokens: a.src_tokens ?? [], tgt_tokens: a.tgt_tokens ?? [], status: a.status, source: a.source,
            })),
            ...(result?.skipped !== undefined ? { skipped: result.skipped } : {}),
          },
          summary: `已建议 ${items.length} 条对齐`,
          ref: { kind: 'layer', id: layerId },
        };
      },
    }),
    spec({
      name: 'annot.agreement',
      description: `标注层的多人一致性：各标注者进度、两两 Cohen's κ、Krippendorff's α、各标签 κ，以及前 ${MAX_DISAGREEMENTS} 条分歧。`,
      parameters: Type.Object({ layer_id: Type.String() }),
      run: async (args, signal) => {
        const [agreement, disagreements] = await Promise.all([
          api.get<any>(`/layers/${seg(args.layer_id)}/agreement`, signal),
          api.get<any>(`/layers/${seg(args.layer_id)}/disagreements`, signal),
        ]);
        const items = listItems(disagreements);
        return {
          data: {
            layer_id: args.layer_id, annotators: agreement.annotators ?? [], pairwise: agreement.pairwise ?? [],
            alpha: agreement.alpha ?? null, per_label: (agreement.per_label ?? []).slice(0, MAX_LABELS),
            disagreements: items.slice(0, MAX_DISAGREEMENTS),
            more_disagreements: Boolean(disagreements?.next_cursor) || items.length > MAX_DISAGREEMENTS,
          },
          summary: `α ${agreement.alpha ?? '无'}，${(agreement.pairwise ?? []).length} 组 κ，分歧 ${items.length}${disagreements?.next_cursor ? '+' : ''} 条`,
          ref: { kind: 'layer', id: args.layer_id },
        };
      },
    }),
    // ---- P4 knowledge base (contracts/p4.md §四–五)
    spec({
      name: 'kb.search',
      description: `知识库混合检索（文献、规范、笔记、网页）：返回最多 ${MAX_KB_ITEMS} 个片段（chunk_id、document_id、title、locator 出处文字、text ≤ ${MAX_CHUNK_CHARS} 字）和匹配的术语。回答引用这些片段时用 KbCitation。`,
      parameters: Type.Object({
        q: Type.String({ minLength: 1 }),
        kinds: Type.Optional(Type.Array(Type.Union(['literature', 'guideline', 'note', 'url'].map(value => Type.Literal(value))))),
        document_ids: Type.Optional(Type.Array(Type.String())),
        top_k: Type.Optional(Type.Integer({ minimum: 1, maximum: MAX_KB_ITEMS })),
        mode: oneOf(['hybrid', 'vector', 'keyword']),
      }),
      run: async (args, signal) => {
        const result = await api.post<any>(`/projects/${projectId}/kb/search`, {
          q: args.q, ...(args.kinds ? { kinds: args.kinds } : {}), ...(args.document_ids ? { document_ids: args.document_ids } : {}),
          top_k: Math.min(args.top_k ?? MAX_KB_ITEMS, MAX_KB_ITEMS), mode: args.mode ?? 'hybrid',
        }, signal);
        const items = (result.items ?? []).slice(0, MAX_KB_ITEMS).map((item: any) => ({
          chunk_id: item.chunk?.id, document_id: item.document?.id ?? item.chunk?.document_id, title: item.document?.title ?? '',
          kind: item.document?.kind, locator: locatorText(item.chunk?.locator), text: clip(item.chunk?.text, MAX_CHUNK_CHARS), score: item.score,
        }));
        const terms = (result.terms ?? []).map(compactTerm);
        const docIds = new Set(items.map((item: any) => item.document_id));
        return {
          data: { q: args.q, items, terms, ...(result.note ? { note: result.note } : {}) },
          summary: `${items.length} 个片段，${terms.length} 条术语`,
          // All chunks from one document → the tool card can open it.
          ...(items.length && docIds.size === 1 ? { ref: { kind: 'kb_document', id: String(items[0].document_id) } } : {}),
        };
      },
    }),
    spec({
      name: 'kb.save',
      description: '保存为研究笔记：不给 note_id 时新建笔记（title 省略取正文首行），给 note_id 时把 body（Markdown）追加到该笔记末尾。refs 为引用 [{kind: search|stat|evidence|chunk|term, ref: {...}}]，如 {kind: "chunk", ref: {chunk_id, document_id}}。',
      parameters: Type.Object({
        title: Type.Optional(Type.String({ minLength: 1 })),
        note_id: Type.Optional(Type.String()),
        body: Type.String({ minLength: 1 }),
        refs: Type.Optional(Type.Array(Type.Object({
          kind: Type.Union(['search', 'stat', 'evidence', 'chunk', 'term'].map(value => Type.Literal(value))),
          ref: Type.Record(Type.String(), Type.Unknown()),
        }))),
      }),
      confirm: async (args, signal) => {
        const firstLine = args.body.split('\n').map(line => line.replace(/^#+\s*/, '').trim()).find(Boolean) ?? '';
        if (args.note_id) {
          const current = await api.get<any>(`/kb/documents/${seg(args.note_id)}`, signal);
          if (current.kind !== 'note') throw new Error('NOT_A_NOTE: 只能追加到笔记');
          return { title: `追加到笔记「${current.title}」`, lines: [clip(firstLine, 120)] };
        }
        return { title: `新建笔记「${args.title ?? (clip(firstLine, 40) || '助手笔记')}」`, lines: [clip(args.body.replace(/\s+/g, ' '), 120)] };
      },
      run: async (args, signal) => {
        let note: any;
        if (args.note_id) {
          const current = await api.get<any>(`/kb/documents/${seg(args.note_id)}`, signal);
          if (current.kind !== 'note') throw new Error('NOT_A_NOTE: 只能追加到笔记');
          const previous = String(current.body ?? '').replace(/\s+$/, '');
          note = await api.patch<any>(`/kb/documents/${seg(args.note_id)}`, {
            body: previous ? `${previous}\n\n${args.body}` : args.body, ...(args.title ? { title: args.title } : {}),
          }, signal);
        } else {
          const firstLine = args.body.split('\n').map(line => line.replace(/^#+\s*/, '').trim()).find(Boolean) ?? '';
          note = await api.post<any>(`/projects/${projectId}/kb/documents`, {
            kind: 'note', title: args.title ?? (clip(firstLine, 40) || '助手笔记'), body: args.body,
          }, signal);
        }
        // the quote is already in body: record the ref without appending it again; a ref the note already has is not added
        let refsAdded = 0;
        for (const ref of args.refs ?? []) {
          const r = await api.post<any>(`/kb/documents/${seg(note.id)}/refs`, { ...ref, append: false }, signal);
          if (!r?.existing) refsAdded += 1;
        }
        return {
          data: { note_id: note.id, title: note.title, appended: Boolean(args.note_id), refs_added: refsAdded },
          summary: `${args.note_id ? '已追加到笔记' : '已新建笔记'} ${note.title}`,
          ref: { kind: 'note', id: note.id },
        };
      },
    }),
    spec({
      name: 'kb.extract_terms',
      description: `抽取术语候选（后台任务，最多等待 90 秒），结果为草稿，返回最新 ${MAX_DRAFT_TERMS} 条。source=corpus 从语料抽取（scope 省略用会话范围；method pos_pattern 或 model；top 候选数）；source=literature 从文献抽取（需 document_ids，方法为 model）。`,
      parameters: Type.Object({
        source: Type.Union([Type.Literal('corpus'), Type.Literal('literature')]),
        scope: ScopeArg,
        method: oneOf(['pos_pattern', 'model']),
        top: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 })),
        document_ids: Type.Optional(Type.Array(Type.String(), { minItems: 1 })),
      }),
      confirm: async (args, signal) => {
        if (args.source === 'literature') {
          if (!args.document_ids?.length) throw new Error('DOCUMENT_IDS_REQUIRED: 从文献抽取需要 document_ids（先用 kb_documents 查找）');
          return { title: '从文献抽取术语草稿', lines: [`文献：${args.document_ids.length} 篇`, '方法：模型'] };
        }
        return {
          title: '从语料抽取术语草稿',
          lines: [await scopeLine(resolveScope(args.scope), signal), `方法：${String(args.method) === 'model' ? '模型' : '词性模式'}，候选 ${args.top ?? 100} 个`],
        };
      },
      run: async (args, signal) => {
        let body: Record<string, unknown>;
        if (args.source === 'literature') {
          if (!args.document_ids?.length) throw new Error('DOCUMENT_IDS_REQUIRED: 从文献抽取需要 document_ids（先用 kb_documents 查找）');
          body = { source: 'literature', document_ids: args.document_ids, method: 'model' };
        } else {
          body = { source: 'corpus', scope: resolveScope(args.scope), method: args.method ?? 'pos_pattern', top: args.top ?? 100 };
        }
        const job = await waitJob(await api.post<Job>(`/projects/${projectId}/kb/terms/extract`, body, signal), signal);
        if (running(job)) return pendingOutput(job, '术语抽取');
        if (job.state !== 'succeeded') throw jobFailed(job, '术语抽取');
        const drafts = listItems(await api.get<any>(`/projects/${projectId}/kb/terms${query({ status: 'draft' })}`, signal))
          .sort((a, b) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? '')))
          .slice(0, MAX_DRAFT_TERMS).map(compactTerm);
        const created = Number(job.result?.created ?? 0);
        return {
          data: { job_id: job.id, created, skipped: job.result?.skipped ?? 0, terms: drafts, note: '均为草稿，需用户在术语页确认。' },
          summary: `新增草稿术语 ${created} 条`,
          ref: { kind: 'job', id: job.id },
        };
      },
    }),
    spec({
      name: 'kb.summarize',
      description: '为知识库文档生成摘要（后台任务，最多等待 90 秒），返回摘要文本（模型生成的草稿）。',
      parameters: Type.Object({ document_id: Type.String() }),
      confirm: async (args, signal) => ({
        title: '为文档生成摘要', lines: [`文档：${(await api.get<any>(`/kb/documents/${seg(args.document_id)}`, signal)).title}`],
      }),
      run: async (args, signal) => {
        const ref = { kind: 'kb_document', id: args.document_id };
        const job = await waitJob(await api.post<Job>(`/kb/documents/${seg(args.document_id)}/summarize`, {}, signal), signal);
        if (running(job)) return pendingOutput(job, '摘要', { document_id: args.document_id });
        if (job.state !== 'succeeded') throw jobFailed(job, '摘要');
        const doc = await api.get<any>(`/kb/documents/${seg(args.document_id)}`, signal);
        const summary = doc.meta?.summary ?? null;
        if (!summary) throw new Error('SUMMARY_MISSING: 任务成功但文档没有摘要');
        return {
          data: { document_id: doc.id, title: doc.title, kind: doc.kind, summary, summary_source: doc.meta?.summary_source ?? null },
          summary: `已生成摘要：${doc.title}`,
          ref,
        };
      },
    }),
    spec({
      name: 'kb.terms',
      description: `查询项目术语表（最多 ${MAX_LIST} 条）：q 匹配术语，status 为 draft 或 confirmed，language 如 zh、en。`,
      parameters: Type.Object({
        q: Type.Optional(Type.String()),
        status: oneOf(['draft', 'confirmed']),
        language: Type.Optional(Type.String()),
      }),
      run: async (args, signal) => {
        const all = listItems(await api.get<any>(`/projects/${projectId}/kb/terms${query({ q: args.q, status: args.status, language: args.language })}`, signal));
        const items = all.slice(0, MAX_LIST).map(compactTerm);
        return {
          data: { total: all.length, items },
          summary: `${all.length} 条术语`,
          ...(items.length === 1 ? { ref: { kind: 'term', id: items[0].term_id } } : {}),
        };
      },
    }),
    spec({
      name: 'kb.documents',
      description: `列出知识库文档（最多 ${MAX_LIST} 个，不含正文）：kind 为 literature、guideline、note 或 url，q 匹配标题。`,
      parameters: Type.Object({
        kind: oneOf(['literature', 'guideline', 'note', 'url']),
        q: Type.Optional(Type.String()),
      }),
      run: async (args, signal) => {
        const all = listItems(await api.get<any>(`/projects/${projectId}/kb/documents${query({ kind: args.kind, q: args.q })}`, signal));
        return {
          data: { total: all.length, items: all.slice(0, MAX_LIST).map(compactKbDocument) },
          summary: `${all.length} 个文档`,
          ...(all.length === 1 ? { ref: { kind: 'kb_document', id: all[0].id } } : {}),
        };
      },
    }),
  ];
}

/** Write tools: proposed to the user first (contract names). */
export const CONFIRM_TOOLS = new Set(
  toolSpecs({ api: null as unknown as ApiClient, projectId: '', scope: null, jobPollMs: 0, jobWaitMs: 0 })
    .filter(tool => tool.confirm).map(tool => tool.name),
);

const apiErrors = async <T>(work: () => Promise<T>): Promise<T> => {
  try {
    return await work();
  } catch (error) {
    // Keep the api error code visible to the model (e.g. QUERY_INVALID, FORBIDDEN).
    if (error instanceof ApiError) throw new Error(`${error.code}: ${error.message}`);
    throw error;
  }
};

/** Runs a tool by contract name, skipping the confirmation step: only for calls the user confirmed. */
export async function runConfirmed(ctx: ToolContext, name: string, args: unknown, signal?: AbortSignal): Promise<ToolOutput> {
  const tool = toolSpecs(ctx).find(item => item.name === name);
  if (!tool) throw new Error(`UNKNOWN_TOOL: ${name}`);
  return apiErrors(() => tool.run(args as never, signal));
}

/** Pi ToolDefinitions; `details` carries the ToolOutput for the ToolCall projection. */
export function piTools(ctx: ToolContext): ToolDefinition[] {
  return toolSpecs(ctx).map(tool => ({
    name: piName(tool.name),
    label: tool.name,
    description: tool.confirm ? `${tool.description}（写操作：调用后先向用户展示确认卡片，用户点“执行”后由平台执行。）` : tool.description,
    parameters: tool.parameters,
    async execute(_toolCallId: string, params: unknown, signal: AbortSignal | undefined) {
      if (tool.confirm) {
        const proposal = await apiErrors(() => tool.confirm!(params as never, signal));
        const output: ToolOutput = {
          data: {
            status: 'NEEDS_CONFIRMATION',
            note: '尚未执行。平台已向用户展示确认卡片，用户点“执行”后由平台执行并把结果告诉你。本轮不要再调用这个工具，也不要说已完成或已提交；用一句话说明将要做什么、请用户确认。',
            proposal,
          },
          summary: '等待确认',
          proposal,
        };
        return { content: [{ type: 'text' as const, text: JSON.stringify(output.data) }], details: output };
      }
      const output = await apiErrors(() => tool.run(params as never, signal));
      return { content: [{ type: 'text' as const, text: JSON.stringify(output.data) }], details: output };
    },
  }));
}
