/**
 * Pi customTools (contracts/p2.md §五 工具, p3.md §五 annot.*, p4.md §五 kb.*, p5.md §四 annot.spans / align.*). Each tool is a thin call to the api
 * with the run's agent token; the api decides permissions. Results stay compact.
 */
import { setTimeout as sleep } from 'node:timers/promises';
import type { ToolDefinition } from '@earendil-works/pi-coding-agent';
import { Type, type Static, type TSchema } from 'typebox';
import { ApiError, query, type ApiClient, type Job } from './api.ts';
import type { Scope } from './types.ts';

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
}

interface Spec<T extends TSchema = TSchema> {
  name: string;
  description: string;
  parameters: T;
  run: (args: Static<T>, signal: AbortSignal | undefined) => Promise<ToolOutput>;
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

/** Pi tool names must match [A-Za-z0-9_-]; the contract name keeps the dot. */
export const piName = (name: string) => name.replace('.', '_');

const compactJob = (job: Job) => ({
  job_id: job.id, kind: job.kind, state: job.state, progress: job.progress, result: job.result, error: job.error,
});

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
      const corpus = await api.get<any>(`/corpora/${seg(corpusId)}`, signal);
      wanted = String(corpus.language ?? '').startsWith('zh') ? 'jieba' : 'upos';
    }
    const builtin = items.filter(set => set.project_id === null);
    const found = builtin.find(set => set.name === wanted) ?? builtin[0];
    if (!found) throw new Error(`LABEL_SET_REQUIRED: 没有可用的 ${kind} 标签集，请传入 label_set_id`);
    return found.id;
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

  /** A job still running after the wait: hand back job_id instead of failing. */
  const pendingOutput = (job: Job, what: string, extra: Record<string, unknown> = {}): ToolOutput => ({
    data: {
      ...extra, job_id: job.id, kind: job.kind, state: job.state, progress: job.progress,
      note: `${what}等待超过 ${Math.round(ctx.jobWaitMs / 1000)} 秒仍未完成，请用户到任务页查看；不要重复提交。`,
    },
    summary: `任务 ${job.id} 仍在运行`,
    ref: { kind: 'job', id: job.id },
  });
  const jobFailed = (job: Job, what: string) =>
    new Error(`${job.error?.code ?? 'JOB_' + job.state.toUpperCase()}: ${job.error?.message ?? what + '任务未成功'}`);
  const running = (job: Job) => job.state === 'queued' || job.state === 'running';

  /** Diff-view value of one token: pos → label; dep → "label→head". */
  const annotValue = (kind: string, label: unknown, head: unknown) =>
    label === null || label === undefined ? '' : kind === 'dep' ? `${label}→${head ?? ''}` : String(label);

  async function runStat(path: string, body: Record<string, unknown>, signal?: AbortSignal): Promise<ToolOutput> {
    const job = await waitJob(await api.post<Job>(path, body, signal), signal);
    if (running(job)) return pendingOutput(job, '');
    if (job.state !== 'succeeded') throw jobFailed(job, '统计');
    const statId = String(job.result?.stat_id ?? '');
    if (!statId) throw new Error('STAT_RESULT_MISSING: 任务成功但没有 stat_id');
    const stat = await api.get<any>(`/stats/${statId}`, signal);
    return {
      data: {
        stat_id: statId, method: stat.method, scope: stat.scope, index_version: stat.index_version,
        columns: stat.columns, row_count: stat.row_count, totals: stat.totals,
        rows: (stat.rows ?? []).slice(0, MAX_STAT_ROWS).map((row: any) => ({ key: row.key, values: row.values })),
      },
      summary: `${stat.method ?? '统计'}：${stat.row_count ?? 0} 行`,
      ref: { kind: 'stat', id: statId },
    };
  }

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
        return { data: { ...corpus, metadata_fields: fields }, summary: `${corpus.name}（${corpus.status}）`, ref: { kind: 'corpus', id: corpus.id } };
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
      run: async (args, signal) => {
        const sub = await api.post<any>(`/projects/${projectId}/subcorpora`, args, signal);
        return { data: sub, summary: `子库 ${sub.name}：${sub.stats?.documents ?? 0} 篇`, ref: { kind: 'subcorpus', id: sub.id } };
      },
    }),
    spec({
      name: 'corpus.parse',
      description: '检查查询式语法，返回解析结果或错误位置。',
      parameters: Type.Object({ query: Type.String({ minLength: 1 }) }),
      run: async (args, signal) => {
        const result = await api.post<any>('/search/parse', { query: args.query }, signal);
        return { data: result, summary: result.ok ? '语法正确' : `语法错误：${result.error?.message ?? ''}` };
      },
    }),
    spec({
      name: 'corpus.search',
      description: `按查询式检索，返回命中、句、文档三项计数、前 ${MAX_HITS} 条命中（含 hit_id）和 search_id。`,
      parameters: Type.Object({
        query: Type.String({ minLength: 1 }),
        scope: ScopeArg,
        sort: oneOf(['position', 'left', 'right', 'random']),
      }),
      run: async (args, signal) => {
        const scope = resolveScope(args.scope);
        const result = await api.post<any>('/search', {
          scope, query: args.query, context: { unit: 'char', size: 40 }, sort: args.sort ?? 'position', page: 1, page_size: MAX_HITS,
        }, signal);
        const counts = result.counts;
        return {
          data: {
            search_id: result.search_id, query: args.query, scope, scope_name: await scopeName(scope, signal), counts,
            hits: (result.items ?? []).slice(0, MAX_HITS).map((hit: any) => ({
              hit_id: hit.hit_id, sentence_index: hit.sentence_index, left: hit.left, match: hit.match, right: hit.right,
              source: hit.document_title,
              ...(hit.aligned?.length ? { aligned: hit.aligned.map((a: any) => a.text).join(' / ') } : {}),
            })),
          },
          summary: `命中 ${counts.hits}，句 ${counts.sentences}，文档 ${counts.documents}${counts.complete === false ? '（计数未完成）' : ''}`,
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
      name: 'stats.frequency',
      description: '词频统计（后台任务，最多等待 90 秒），返回 stat_id 与前 50 行。',
      parameters: Type.Object({
        scope: ScopeArg,
        unit: oneOf(['word', 'lemma', 'pos']),
        pos: Type.Optional(Type.String({ description: '只统计该词性，如 n、v' })),
        top: positiveInt(),
        min_freq: positiveInt(),
      }),
      run: (args, signal) => runStat('/stats/frequency', {
        scope: resolveScope(args.scope), unit: args.unit ?? 'word', pos: args.pos, top: args.top ?? 200, min_freq: args.min_freq ?? 1,
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
      description: '搭配统计（后台任务）：node 为节点查询式，返回 stat_id 与前 50 行（含 MI、logDice、t、LL）。',
      parameters: Type.Object({
        scope: ScopeArg,
        node: Type.String({ minLength: 1 }),
        window: Type.Optional(Type.Integer({ minimum: 1, maximum: 10 })),
        unit: oneOf(['word', 'lemma']),
        pos: Type.Optional(Type.String({ description: '只保留该词性的搭配词' })),
        measures: Type.Optional(Type.Array(Type.Union(['mi', 'logdice', 't', 'll'].map(value => Type.Literal(value))))),
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
      description: '关键词统计（后台任务）：target 相对 reference，返回 stat_id 与前 50 行。',
      parameters: Type.Object({
        target: ScopeArg,
        reference: scopeObject(),
        unit: oneOf(['word', 'lemma']),
        measure: oneOf(['ll', 'log_ratio']),
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
        }, signal);
      },
    }),
    spec({
      name: 'stats.distribution',
      description: '命中在元数据字段（如 year）或文本位置（field="position"）上的分布（后台任务），返回 stat_id 与各区间。',
      parameters: Type.Object({
        scope: ScopeArg,
        query: Type.Optional(Type.String()),
        field: Type.String({ minLength: 1 }),
        bins: Type.Optional(Type.Integer({ minimum: 2, maximum: 50 })),
      }),
      run: (args, signal) => runStat('/stats/distribution', {
        scope: resolveScope(args.scope), query: args.query, field: args.field, bins: args.bins,
      }, signal),
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
      run: async (args, signal) => {
        const item = await api.post<any>(`/projects/${projectId}/evidence`, args, signal);
        return {
          data: { evidence_id: item.id, kind: item.kind, text: item.text, source: item.source },
          summary: '已加入证据篮',
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
        return { data: compactJob(job), summary: `导出任务 ${job.id}`, ref: { kind: 'job', id: job.id } };
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
      description: '为语料库建立标注层并自动预标（后台任务，最多等待 90 秒）。kind=pos 词性、dep 依存；label_set_id 省略时用内置标签集。删除层即可撤销。',
      parameters: Type.Object({
        corpus_id: Type.String(),
        kind: Type.Union([Type.Literal('pos'), Type.Literal('dep')]),
        name: Type.String({ minLength: 1 }),
        label_set_id: Type.Optional(Type.String()),
        document_ids: Type.Optional(Type.Array(Type.String())),
      }),
      run: async (args, signal) => {
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
            summary: `标注层 ${layer.name} 预标中（任务 ${job.id}）`,
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
          summary: `第 ${args.sentence_index} 句，${tokens.length} 个 token`,
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
      run: async (args, signal) => {
        if (args.label === undefined && args.head === undefined) throw new Error('LABEL_OR_HEAD_REQUIRED: 需要 label 或 head');
        const { layer_id: layerId, ...body } = args;
        const annot = await api.post<any>(`/layers/${seg(layerId)}/suggest`, body, signal);
        return {
          data: {
            annotation_id: annot.id, document_id: args.document_id, sentence_index: args.sentence_index,
            token_index: annot.token_index ?? args.token_index, label: annot.label, head: annot.head, status: annot.status, source: annot.source,
          },
          summary: `已建议 token ${annot.token_index ?? args.token_index}：${annot.status}`,
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
      run: async (args, signal) => {
        const job = await api.post<Job>(`/layers/${seg(args.layer_id)}/export`, {
          format: 'conllu', ...(args.document_ids ? { document_ids: args.document_ids } : {}),
        }, signal);
        return { data: compactJob(job), summary: `导出任务 ${job.id}`, ref: { kind: 'job', id: job.id } };
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
      run: async (args, signal) => {
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
        for (const ref of args.refs ?? []) await api.post(`/kb/documents/${seg(note.id)}/refs`, ref, signal);
        return {
          data: { note_id: note.id, title: note.title, appended: Boolean(args.note_id), refs_added: args.refs?.length ?? 0 },
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

/** Pi ToolDefinitions; `details` carries the ToolOutput for the ToolCall projection. */
export function piTools(ctx: ToolContext): ToolDefinition[] {
  return toolSpecs(ctx).map(tool => ({
    name: piName(tool.name),
    label: tool.name,
    description: tool.description,
    parameters: tool.parameters,
    async execute(_toolCallId: string, params: unknown, signal: AbortSignal | undefined) {
      let output: ToolOutput;
      try {
        output = await tool.run(params as never, signal);
      } catch (error) {
        // Keep the api error code visible to the model (e.g. QUERY_INVALID, FORBIDDEN).
        if (error instanceof ApiError) throw new Error(`${error.code}: ${error.message}`);
        throw error;
      }
      return { content: [{ type: 'text' as const, text: JSON.stringify(output.data) }], details: output };
    },
  }));
}
