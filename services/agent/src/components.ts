/**
 * OpenUI component catalog (contracts/p2.md §五, p3.md §五, p4.md §五, p5.md §四). Single source for the
 * system-prompt catalog; the web app registers renderers under the same names
 * and prop order. No renderer here: `component` is null on the server.
 */
import { createLibrary, defineComponent } from '@openuidev/lang-core';
import { z } from 'zod';


export const KwicTable = defineComponent({
  name: 'KwicTable',
  description: '检索命中的 KWIC 列表。corpus_search 之后使用；rows 取工具返回的 hits，保留 hit_id。search_semantic 之后也用它：search_id 写 ""，query 为输入句，counts 取工具结果，rows 每条带 score（相似度），mode 写 "semantic"。',
  props: z.object({
    search_id: z.string(),
    query: z.string(),
    scope_name: z.string(),
    counts: z.object({ hits: z.number(), sentences: z.number(), documents: z.number() }),
    rows: z.array(z.object({
      hit_id: z.string(), left: z.string(), match: z.string(), right: z.string(), source: z.string(),
      aligned: z.string().optional(), score: z.number().optional(),
    })),
    total: z.number(),
    mode: z.enum(['query', 'semantic']).optional(),
  }),
  component: null,
});

export const FreqChart = defineComponent({
  name: 'FreqChart',
  description: '频次或 n-gram 结果的柱状图。stats_frequency / stats_ngrams 之后使用；只放前若干行。',
  props: z.object({
    stat_id: z.string(),
    title: z.string(),
    unit: z.string(),
    rows: z.array(z.object({ label: z.string(), value: z.number(), per_million: z.number().optional() })),
    top: z.number(),
  }),
  component: null,
});

export const CollocationTable = defineComponent({
  name: 'CollocationTable',
  description: '搭配词表。stats_collocations 之后使用；measure 为排序所用指标（mi、logdice、t、ll、mi3、delta_p_node、delta_p_coll、z），score 为该指标值。',
  props: z.object({
    stat_id: z.string(),
    node: z.string(),
    window: z.number(),
    measure: z.string(),
    rows: z.array(z.object({ collocate: z.string(), freq: z.number(), score: z.number() })),
  }),
  component: null,
});

export const KeywordTable = defineComponent({
  name: 'KeywordTable',
  description: '关键词表。stats_keywords 之后使用；measure 为排序所用指标（ll、log_ratio、pct_diff、odds_ratio），score 为该指标值。',
  props: z.object({
    stat_id: z.string(),
    target: z.string(),
    reference: z.string(),
    measure: z.string(),
    rows: z.array(z.object({ word: z.string(), target_freq: z.number(), reference_freq: z.number(), score: z.number() })),
  }),
  component: null,
});

export const BreakdownTable = defineComponent({
  name: 'BreakdownTable',
  description: '命中频次分解表。stats_breakdown 之后使用：by 原样复制工具参数；rows 每行 item（项）、hits（命中数）、pct（占比 %）、per_million（每百万词）取自 values 同名键；search_query 与 search_scope 从该行复制（没有就省略），用于打开例句。',
  props: z.object({
    stat_id: z.string(),
    query: z.string(),
    by: z.string(),
    rows: z.array(z.object({
      item: z.string(), hits: z.number(), pct: z.number(), per_million: z.number(),
      search_query: z.string().nullable().optional(), search_scope: z.record(z.string(), z.unknown()).optional(),
    })),
  }),
  component: null,
});

export const TranslationTable = defineComponent({
  name: 'TranslationTable',
  description: '平行语料译法表。stats_translations 之后使用：query 为源语言查询式；measure 为排序指标（dice 或 ll），score 为该指标值；rows 每行 item、cooc（共现句数）、pct（占命中句 %）取自 values 同名键，score 取 values 中 measure 对应的值（dice 或 ll）；search_query、search_aligned、search_scope 从该行原样复制（没有就省略），点击行打开含该译法的例句。',
  props: z.object({
    stat_id: z.string(),
    query: z.string(),
    measure: z.string(),
    rows: z.array(z.object({
      item: z.string(), cooc: z.number(), pct: z.number(), score: z.number(),
      search_query: z.string().nullable().optional(),
      search_aligned: z.object({ op: z.enum(['+', '-']), query: z.string() }).optional(),
      search_scope: z.record(z.string(), z.unknown()).optional(),
    })),
  }),
  component: null,
});

export const DistributionChart = defineComponent({
  name: 'DistributionChart',
  description: '命中在元数据字段或文本位置上的分布。stats_distribution 之后使用。',
  props: z.object({
    stat_id: z.string(),
    field: z.string(),
    rows: z.array(z.object({ bin: z.string(), hits: z.number(), per_million: z.number() })),
  }),
  component: null,
});

export const EvidenceCard = defineComponent({
  name: 'EvidenceCard',
  description: '已钉入证据篮的一条证据。evidence_add 成功后使用。',
  props: z.object({ evidence_id: z.string(), text: z.string(), source: z.string() }),
  component: null,
});

export const JobStatus = defineComponent({
  name: 'JobStatus',
  description: '后台任务状态。统计等待超时或导出任务提交后使用，让用户到任务页查看。',
  props: z.object({
    job_id: z.string(),
    kind: z.string(),
    state: z.string(),
    progress: z.object({ done: z.number(), total: z.number().nullable(), message: z.string() }),
  }),
  component: null,
});

export const Callout = defineComponent({
  name: 'Callout',
  description: '简短提示：范围限制、结果不完整、需要用户确认等。',
  props: z.object({ tone: z.enum(['info', 'warning']), text: z.string() }),
  component: null,
});

export const DependencyTree = defineComponent({
  name: 'DependencyTree',
  description: '一句的依存结构弧线图。用户问某句的依存结构或句法分析时，在 corpus_sentence 或 annot_sentence 之后使用：tokens 取 index、form、pos（annot_sentence 取 effective.pos）；arcs 每个 token 一条，dep 为该 token 的 index，head 与 label 取 head、deprel（annot_sentence 取 effective.head、effective.deprel；head 0 为根）；highlight 为要突出的 token index。',
  props: z.object({
    document_id: z.string(),
    sentence_index: z.number(),
    tokens: z.array(z.object({ index: z.number(), form: z.string(), pos: z.string() })),
    arcs: z.array(z.object({ head: z.number(), dep: z.number(), label: z.string() })),
    highlight: z.array(z.number()).optional(),
  }),
  component: null,
});

export const AnnotationDiff = defineComponent({
  name: 'AnnotationDiff',
  description: '一句中校对者对预标的改动。annot_diff 之后使用：tokens 取该句的 changes，model 为预标值，human 为人工值，status 为 modified 或 rejected 等。',
  props: z.object({
    layer_id: z.string(),
    document_id: z.string(),
    sentence_index: z.number(),
    tokens: z.array(z.object({
      form: z.string(), model: z.string(), human: z.string(),
      status: z.enum(['suggested', 'confirmed', 'modified', 'rejected']),
    })),
  }),
  component: null,
});

export const TermCard = defineComponent({
  name: 'TermCard',
  description: '一条术语的词条。用户问某个术语或术语建议时使用，数据取自 kb_terms、kb_search 的 terms 或 kb_extract_terms；status 原样复制（draft 为草稿，confirmed 为已确认），自己提出的术语建议只能写 draft；examples 最多 3 条。',
  props: z.object({
    term_id: z.string(),
    term: z.string(),
    translations: z.array(z.object({ language: z.string(), text: z.string() })),
    definition: z.string(),
    domain: z.string(),
    examples: z.array(z.object({ text: z.string(), source: z.string() })),
    status: z.enum(['draft', 'confirmed']),
  }),
  component: null,
});

export const KbCitation = defineComponent({
  name: 'KbCitation',
  description: '回答所依据的知识库片段。kb_search 之后、回答引用了文献、规范或笔记内容时使用：items 只放实际引用的片段，chunk_id、document_id、title、locator、text 从 kb_search 结果复制。',
  props: z.object({
    items: z.array(z.object({
      chunk_id: z.string(), document_id: z.string(), title: z.string(), locator: z.string(), text: z.string(),
    })),
  }),
  component: null,
});

export const SpanView = defineComponent({
  name: 'SpanView',
  description: '一句中的片段标注与关系（如翻译策略、偏误）。用户要求标出或查看某句的片段时，在 annot_spans 或 annot_suggest_spans 之后使用：text 为该句文本，spans 的 start、end 为句内码点偏移（取工具返回的 start、end），label 为标签；relations 的 from、to 为 spans 数组的 0 起下标。',
  props: z.object({
    document_id: z.string(),
    sentence_index: z.number(),
    text: z.string(),
    spans: z.array(z.object({ start: z.number(), end: z.number(), label: z.string() })),
    relations: z.array(z.object({ from: z.number(), to: z.number(), label: z.string() })),
  }),
  component: null,
});

export const AlignmentGraph = defineComponent({
  name: 'AlignmentGraph',
  description: '一个句对的词级对齐连线图。align_pairs 或 align_suggest 之后使用：src_tokens、tgt_tokens 取句对两侧的 tokens；links 每条对齐一项，src、tgt 为 1 起 token 序号（取 src_tokens、tgt_tokens 字段），status 原样复制；layer_id、src_document_id、src_sentence_index 取工具结果中该句对的同名字段（原值，不换算），用于在标注页打开这一句对。',
  props: z.object({
    src_tokens: z.array(z.string()),
    tgt_tokens: z.array(z.string()),
    links: z.array(z.object({
      src: z.array(z.number()), tgt: z.array(z.number()),
      status: z.enum(['suggested', 'confirmed', 'modified', 'rejected']).optional(),
    })),
    layer_id: z.string().optional(),
    src_document_id: z.string().optional(),
    src_sentence_index: z.number().optional(),
  }),
  component: null,
});

const SketchLayers = z.object({ dep: z.string().optional() }).optional();
const sketchRow = {
  collocate: z.string(), search_query: z.string().nullable().optional(),
};

export const WordSketch = defineComponent({
  name: 'WordSketch',
  description: 'Word Sketch 分栏卡。stats_word_sketch 之后使用：relations 从工具结果的 relations 原样复制（每栏 relation 为栏名，rows 每行 collocate、freq、logdice、search_query），可只放用户关心的栏；点击行回到例句；pos 为节点词性（没有就省略）；layers 从工具结果的 search_layers 复制（没有就省略）。',
  props: z.object({
    stat_id: z.string(),
    lemma: z.string(),
    relations: z.array(z.object({
      relation: z.string(),
      rows: z.array(z.object({ ...sketchRow, freq: z.number(), logdice: z.number() })),
    })),
    pos: z.string().optional(),
    layers: SketchLayers,
  }),
  component: null,
});

const diffRow = z.object({
  ...sketchRow, relation: z.string(), freq_a: z.number(), freq_b: z.number(), diff: z.number(),
});

export const SketchDiff = defineComponent({
  name: 'SketchDiff',
  description: '近义词对比三列卡（偏 A / 共同 / 偏 B）。stats_sketch_diff 之后使用：a、common、b 分别从工具结果 sides 的 a、common、b 原样复制（每行 relation、collocate、freq_a、freq_b、diff、search_query）；点击行回到例句；layers 从工具结果的 search_layers 复制（没有就省略）。',
  props: z.object({
    stat_id: z.string(),
    lemma_a: z.string(),
    lemma_b: z.string(),
    a: z.array(diffRow),
    common: z.array(diffRow),
    b: z.array(diffRow),
    layers: SketchLayers,
  }),
  component: null,
});

export const CompareChart = defineComponent({
  name: 'CompareChart',
  description: '多项对比的多系列折线图或分组柱图。stats_compare 带 by 时使用：categories 为各行的字段值（按行顺序），series 每项一个系列，name 为该项 label，values 为各行该项的每百万词（与 categories 一一对应）；chart 为 line（有序字段如年份）或 bar（体裁等类别）；unit 写“每百万词”。',
  props: z.object({
    stat_id: z.string(),
    title: z.string(),
    unit: z.string(),
    categories: z.array(z.string()),
    series: z.array(z.object({ name: z.string(), values: z.array(z.number().nullable()) })),
    chart: z.enum(['line', 'bar']),
  }),
  component: null,
});

export const COMPONENTS = [
  KwicTable, FreqChart, CollocationTable, KeywordTable, DistributionChart, EvidenceCard, JobStatus, Callout,
  DependencyTree, AnnotationDiff, TermCard, KbCitation, SpanView, AlignmentGraph, BreakdownTable, TranslationTable,
  WordSketch, SketchDiff, CompareChart,
];
export const COMPONENT_NAMES = COMPONENTS.map(component => component.name);

export const library = createLibrary({ components: COMPONENTS });

/** Catalog + OpenUI Lang rules, generated by the official lang-core prompt builder (inline mode). */
export function componentCatalog(): string {
  return library.prompt({ inlineMode: true, toolCalls: false, bindings: false, builtinFunctions: false });
}

