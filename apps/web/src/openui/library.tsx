import { createLibrary, defineComponent } from "@openuidev/react-lang";
import { Fragment, type ReactNode } from "react";
import { z } from "zod/v4";
import {
  CalloutView,
  CollocationTableCard,
  DistributionChartCard,
  EvidenceCardView,
  FreqChartCard,
  JobStatusCard,
  KeywordTableCard,
  KwicTableCard,
} from "../components/results/cards";
import { AnnotationDiffCard, DependencyTreeCard } from "../components/results/annotCards";
import { AlignmentGraphCard, SpanViewCard } from "../components/results/annot2Cards";
import { KbCitationCard, TermCardView } from "../components/results/kbCards";

// Names, prop order and schemas mirror services/agent/src/components.ts (positional OpenUI Lang args).
export const KwicTable = defineComponent({
  name: "KwicTable",
  description: "检索命中的 KWIC 列表。",
  props: z.object({
    search_id: z.string(),
    query: z.string(),
    scope_name: z.string(),
    counts: z.object({ hits: z.number(), sentences: z.number(), documents: z.number() }),
    rows: z.array(
      z.object({ hit_id: z.string(), left: z.string(), match: z.string(), right: z.string(), source: z.string(), aligned: z.string().optional() }),
    ),
    total: z.number(),
  }),
  component: ({ props }) => <KwicTableCard {...props} />,
});

export const FreqChart = defineComponent({
  name: "FreqChart",
  description: "频次或 n-gram 结果的柱状图。",
  props: z.object({
    stat_id: z.string(),
    title: z.string(),
    unit: z.string(),
    rows: z.array(z.object({ label: z.string(), value: z.number(), per_million: z.number().optional() })),
    top: z.number(),
  }),
  component: ({ props }) => <FreqChartCard {...props} />,
});

export const CollocationTable = defineComponent({
  name: "CollocationTable",
  description: "搭配词表。",
  props: z.object({
    stat_id: z.string(),
    node: z.string(),
    window: z.number(),
    measure: z.string(),
    rows: z.array(z.object({ collocate: z.string(), freq: z.number(), score: z.number() })),
  }),
  component: ({ props }) => <CollocationTableCard {...props} />,
});

export const KeywordTable = defineComponent({
  name: "KeywordTable",
  description: "关键词表。",
  props: z.object({
    stat_id: z.string(),
    target: z.string(),
    reference: z.string(),
    measure: z.string(),
    rows: z.array(z.object({ word: z.string(), target_freq: z.number(), reference_freq: z.number(), score: z.number() })),
  }),
  component: ({ props }) => <KeywordTableCard {...props} />,
});

export const DistributionChart = defineComponent({
  name: "DistributionChart",
  description: "命中在元数据字段或文本位置上的分布。",
  props: z.object({
    stat_id: z.string(),
    field: z.string(),
    rows: z.array(z.object({ bin: z.string(), hits: z.number(), per_million: z.number() })),
  }),
  component: ({ props }) => <DistributionChartCard {...props} />,
});

export const EvidenceCard = defineComponent({
  name: "EvidenceCard",
  description: "已钉入证据篮的一条证据。",
  props: z.object({ evidence_id: z.string(), text: z.string(), source: z.string() }),
  component: ({ props }) => <EvidenceCardView {...props} />,
});

export const JobStatus = defineComponent({
  name: "JobStatus",
  description: "后台任务状态。",
  props: z.object({
    job_id: z.string(),
    kind: z.string(),
    state: z.string(),
    progress: z.object({ done: z.number(), total: z.number().nullable(), message: z.string() }),
  }),
  component: ({ props }) => <JobStatusCard {...props} />,
});

export const Callout = defineComponent({
  name: "Callout",
  description: "简短提示。",
  props: z.object({ tone: z.enum(["info", "warning"]), text: z.string() }),
  component: ({ props }) => <CalloutView {...props} />,
});

export const DependencyTree = defineComponent({
  name: "DependencyTree",
  description: "一句的依存结构弧线图。",
  props: z.object({
    document_id: z.string(),
    sentence_index: z.number(),
    tokens: z.array(z.object({ index: z.number(), form: z.string(), pos: z.string() })),
    arcs: z.array(z.object({ head: z.number(), dep: z.number(), label: z.string() })),
    highlight: z.array(z.number()).optional(),
  }),
  component: ({ props }) => <DependencyTreeCard {...props} />,
});

export const AnnotationDiff = defineComponent({
  name: "AnnotationDiff",
  description: "一句的预标与人工结果对比。",
  props: z.object({
    layer_id: z.string(),
    document_id: z.string(),
    sentence_index: z.number(),
    tokens: z.array(
      z.object({ form: z.string(), model: z.string(), human: z.string(), status: z.enum(["suggested", "confirmed", "modified", "rejected"]) }),
    ),
  }),
  component: ({ props }) => <AnnotationDiffCard {...props} />,
});

export const TermCard = defineComponent({
  name: "TermCard",
  description: "一条术语的词条。",
  props: z.object({
    term_id: z.string(),
    term: z.string(),
    translations: z.array(z.object({ language: z.string(), text: z.string() })),
    definition: z.string(),
    domain: z.string(),
    examples: z.array(z.object({ text: z.string(), source: z.string() })),
    status: z.enum(["draft", "confirmed"]),
  }),
  component: ({ props }) => <TermCardView {...props} />,
});

export const KbCitation = defineComponent({
  name: "KbCitation",
  description: "回答所依据的知识库片段。",
  props: z.object({
    items: z.array(z.object({ chunk_id: z.string(), document_id: z.string(), title: z.string(), locator: z.string(), text: z.string() })),
  }),
  component: ({ props }) => <KbCitationCard {...props} />,
});

export const SpanView = defineComponent({
  name: "SpanView",
  description: "一句中的片段标注与关系；start、end 为句内码点，relations 的 from、to 为 spans 的 0 起下标。",
  props: z.object({
    document_id: z.string(),
    sentence_index: z.number(),
    text: z.string(),
    spans: z.array(z.object({ start: z.number(), end: z.number(), label: z.string() })),
    relations: z.array(z.object({ from: z.number(), to: z.number(), label: z.string() })),
  }),
  component: ({ props }) => <SpanViewCard {...props} />,
});

export const AlignmentGraph = defineComponent({
  name: "AlignmentGraph",
  description: "一个句对的词级对齐连线图；links 的 src、tgt 为 1 起 token 序号；layer_id、src_document_id、src_sentence_index 用于在标注页打开该句对。",
  props: z.object({
    src_tokens: z.array(z.string()),
    tgt_tokens: z.array(z.string()),
    links: z.array(
      z.object({ src: z.array(z.number()), tgt: z.array(z.number()), status: z.enum(["suggested", "confirmed", "modified", "rejected"]).optional() }),
    ),
    layer_id: z.string().optional(),
    src_document_id: z.string().optional(),
    src_sentence_index: z.number().optional(),
  }),
  component: ({ props }) => <AlignmentGraphCard {...props} />,
});

export const COMPONENTS = [
  KwicTable,
  FreqChart,
  CollocationTable,
  KeywordTable,
  DistributionChart,
  EvidenceCard,
  JobStatus,
  Callout,
  DependencyTree,
  AnnotationDiff,
  TermCard,
  KbCitation,
  SpanView,
  AlignmentGraph,
];

/** No root component: each ui block is a program whose entry is `root = <Component>(...)`. */
export const library = createLibrary({ components: COMPONENTS });

const KNOWN = new Set([...COMPONENTS.map((c) => c.name), "Query", "Mutation"]);
const FALLBACK_PROPS = z.object(Object.fromEntries(Array.from({ length: 8 }, (_, i) => [`a${i}`, z.any().optional()])));

/** Children of an unknown component: registered components render, text shows as text, other values are skipped. */
function fallbackValue(value: unknown, renderNode: (v: unknown) => ReactNode, depth = 0): ReactNode {
  if (value === null || value === undefined || depth > 4) return null;
  if (typeof value === "string") return value.trim() ? <p className="ui-fallback-text">{value}</p> : null;
  if (typeof value === "number" || typeof value === "boolean") return null;
  if (Array.isArray(value)) return value.map((v, i) => <Fragment key={i}>{fallbackValue(v, renderNode, depth + 1)}</Fragment>);
  if ((value as { type?: unknown }).type === "element") return renderNode(value);
  return Object.values(value as object).map((v, i) => <Fragment key={i}>{fallbackValue(v, renderNode, depth + 1)}</Fragment>);
}

const warned = new Set<string>();
const libraries = new Map<string, typeof library>();

/**
 * Library for one program. A component outside the catalog (the model sometimes writes layout wrappers such as
 * `Stack([...])`) becomes a plain container that renders its children instead of being dropped; logged once per name.
 */
export function libraryFor(lang: string): typeof library {
  const unknown = [...new Set([...lang.matchAll(/(?<![\w@$.])([A-Z][A-Za-z0-9_]*)\s*\(/g)].map((m) => m[1]))].filter((n) => !KNOWN.has(n)).sort();
  if (!unknown.length) return library;
  const key = unknown.join(",");
  let lib = libraries.get(key);
  if (!lib) {
    for (const name of unknown) {
      if (warned.has(name)) continue;
      warned.add(name);
      console.warn(`[openui] unknown component "${name}" rendered as a plain container`);
    }
    const fallbacks = unknown.map((name) =>
      defineComponent({
        name,
        description: "未注册组件的降级显示",
        props: FALLBACK_PROPS,
        component: ({ props, renderNode }) => <div className="ui-fallback">{fallbackValue(Object.values(props), renderNode)}</div>,
      }),
    );
    lib = createLibrary({ components: [...COMPONENTS, ...fallbacks] });
    libraries.set(key, lib);
  }
  return lib;
}

/** Direct renderers for the JSON fallback `{component, props}`. */
export const RENDERERS: Record<string, React.FC<never>> = {
  KwicTable: KwicTableCard,
  FreqChart: FreqChartCard,
  CollocationTable: CollocationTableCard,
  KeywordTable: KeywordTableCard,
  DistributionChart: DistributionChartCard,
  EvidenceCard: EvidenceCardView,
  JobStatus: JobStatusCard,
  Callout: CalloutView,
  DependencyTree: DependencyTreeCard,
  AnnotationDiff: AnnotationDiffCard,
  TermCard: TermCardView,
  KbCitation: KbCitationCard,
  SpanView: SpanViewCard,
  AlignmentGraph: AlignmentGraphCard,
};
