import { createLibrary, defineComponent } from "@openuidev/react-lang";
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

export const COMPONENTS = [KwicTable, FreqChart, CollocationTable, KeywordTable, DistributionChart, EvidenceCard, JobStatus, Callout, DependencyTree, AnnotationDiff];

/** No root component: each ui block is a program whose entry is `root = <Component>(...)`. */
export const library = createLibrary({ components: COMPONENTS });

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
};
