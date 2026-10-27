import type { IconName } from "../Icon";

/** Agent tools from contracts/p2.md §五, grouped as on the assistant page. */
export const AGENT_TOOLS: { group: string; tools: string[] }[] = [
  { group: "语料", tools: ["corpora.list", "corpora.get", "subcorpora.list", "subcorpora.create", "corpus.parse", "corpus.search", "corpus.context"] },
  { group: "统计", tools: ["stats.frequency", "stats.ngrams", "stats.collocations", "stats.keywords", "stats.distribution"] },
  { group: "标注", tools: ["annot.layers", "annot.create_layer", "annot.sentence", "annot.diff", "annot.stats", "annot.suggest", "annot.export"] },
  { group: "成果", tools: ["evidence.add", "evidence.list", "queries.save", "queries.list", "export.create", "jobs.get", "jobs.cancel"] },
];

export const TOOL_COUNT = AGENT_TOOLS.reduce((n, g) => n + g.tools.length, 0);

/** Chinese step title, running label and icon for the thinking chain. */
export const TOOL_VIEW: Record<string, { title: string; label: string; icon: IconName }> = {
  "corpora.list": { title: "列出语料库", label: "正在读取语料库…", icon: "db" },
  "corpora.get": { title: "读取语料库", label: "正在读取语料库…", icon: "db" },
  "subcorpora.list": { title: "列出子库", label: "正在读取子库…", icon: "filter" },
  "subcorpora.create": { title: "新建子库", label: "正在新建子库…", icon: "filter" },
  "corpus.parse": { title: "解析查询式", label: "正在解析查询式…", icon: "search" },
  "corpus.search": { title: "检索语料", label: "正在检索语料…", icon: "search" },
  "corpus.context": { title: "读取上下文", label: "正在读取上下文…", icon: "filetext" },
  "stats.frequency": { title: "计算频次", label: "正在计算频次…", icon: "chart" },
  "stats.ngrams": { title: "计算 n-gram", label: "正在计算 n-gram…", icon: "chart" },
  "stats.collocations": { title: "计算搭配", label: "正在计算搭配…", icon: "network" },
  "stats.keywords": { title: "关键词比较", label: "正在比较关键词…", icon: "scatter" },
  "stats.distribution": { title: "计算分布", label: "正在计算分布…", icon: "chart" },
  "evidence.add": { title: "加入证据篮", label: "正在保存证据…", icon: "pin" },
  "evidence.list": { title: "读取证据篮", label: "正在读取证据…", icon: "basket" },
  "queries.save": { title: "保存查询", label: "正在保存查询…", icon: "plus" },
  "queries.list": { title: "读取保存的查询", label: "正在读取查询…", icon: "search" },
  "export.create": { title: "创建导出", label: "正在创建导出…", icon: "download" },
  "jobs.get": { title: "查看任务", label: "正在查看任务…", icon: "clock" },
  "jobs.cancel": { title: "取消任务", label: "正在取消任务…", icon: "stop" },
  "annot.layers": { title: "列出标注层", label: "正在读取标注层…", icon: "layers" },
  "annot.create_layer": { title: "新建标注层", label: "正在新建标注层…", icon: "pen" },
  "annot.sentence": { title: "读取句子标注", label: "正在读取标注…", icon: "tree" },
  "annot.diff": { title: "读取预标差异", label: "正在比较预标与人工…", icon: "diff" },
  "annot.stats": { title: "标注统计", label: "正在统计标签…", icon: "chart" },
  "annot.suggest": { title: "提出标注建议", label: "正在写入建议…", icon: "spark" },
  "annot.export": { title: "导出 CoNLL-U", label: "正在创建导出…", icon: "download" },
};
