/**
 * Pi customTools (contracts/p2.md §五 工具). Each tool is a thin call to the api
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
const MAX_STAT_ROWS = 50;
const MAX_HITS = 20;

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

  async function runStat(path: string, body: Record<string, unknown>, signal?: AbortSignal): Promise<ToolOutput> {
    const job = await waitJob(await api.post<Job>(path, body, signal), signal);
    if (job.state === 'queued' || job.state === 'running') {
      return {
        data: {
          job_id: job.id, kind: job.kind, state: job.state, progress: job.progress,
          note: `等待超过 ${Math.round(ctx.jobWaitMs / 1000)} 秒仍未完成，请用户到任务页查看；不要重复提交。`,
        },
        summary: `任务 ${job.id} 仍在运行`,
        ref: { kind: 'job', id: job.id },
      };
    }
    if (job.state !== 'succeeded') {
      throw new Error(`${job.error?.code ?? 'JOB_' + job.state.toUpperCase()}: ${job.error?.message ?? '统计任务未成功'}`);
    }
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
