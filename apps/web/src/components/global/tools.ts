import type { IconName } from "../Icon";

/** Agent tools (contracts/p2–p5, same names as services/agent/src/tools.ts), grouped by capability as on the assistant page. */
export const AGENT_TOOLS: { group: string; tools: string[] }[] = [
  { group: "语料与检索", tools: ["corpora.list", "corpora.get", "corpora.documents", "subcorpora.list", "subcorpora.create", "corpus.parse", "corpus.search", "corpus.context"] },
  { group: "统计", tools: ["stats.frequency", "stats.ngrams", "stats.collocations", "stats.keywords", "stats.distribution"] },
  { group: "词性与依存标注", tools: ["annot.layers", "annot.create_layer", "annot.sentence", "annot.diff", "annot.stats", "annot.suggest", "annot.export"] },
  { group: "片段与对齐", tools: ["annot.spans", "annot.suggest_spans", "align.pairs", "align.suggest", "annot.agreement"] },
  { group: "知识库", tools: ["kb.search", "kb.terms", "kb.documents", "kb.save", "kb.extract_terms", "kb.summarize"] },
  { group: "证据与导出", tools: ["evidence.add", "evidence.list", "queries.save", "queries.list", "export.create"] },
  { group: "任务", tools: ["jobs.get", "jobs.cancel"] },
];

/** Write tools: the assistant proposes them and runs them only after 执行 on the confirm card. */
export const CONFIRM_TOOLS = new Set([
  "subcorpora.create", "evidence.add", "queries.save", "export.create", "jobs.cancel", "annot.create_layer", "annot.suggest",
  "annot.export", "annot.suggest_spans", "align.suggest", "kb.save", "kb.extract_terms", "kb.summarize",
]);

export const TOOL_COUNT = AGENT_TOOLS.reduce((n, g) => n + g.tools.length, 0);

/** Chinese step title, running label and family icon (corpus / stats kind / annotation / knowledge base / results) for the thinking chain. */
export const TOOL_VIEW: Record<string, { title: string; label: string; icon: IconName }> = {
  "corpora.list": { title: "列出语料库", label: "正在读取语料库…", icon: "library" },
  "corpora.get": { title: "读取语料库", label: "正在读取语料库…", icon: "library" },
  "corpora.documents": { title: "列出语料文档", label: "正在读取文档列表…", icon: "filetext" },
  "subcorpora.list": { title: "列出子库", label: "正在读取子库…", icon: "filter" },
  "subcorpora.create": { title: "新建子库", label: "正在新建子库…", icon: "filter" },
  "corpus.parse": { title: "解析查询式", label: "正在解析查询式…", icon: "brackets" },
  "corpus.search": { title: "检索语料", label: "正在检索语料…", icon: "textsearch" },
  "corpus.context": { title: "读取上下文", label: "正在读取上下文…", icon: "textquote" },
  "stats.frequency": { title: "计算频次", label: "正在计算频次…", icon: "chartbar" },
  "stats.ngrams": { title: "计算 n-gram", label: "正在计算 n-gram…", icon: "listordered" },
  "stats.collocations": { title: "计算搭配", label: "正在计算搭配…", icon: "chartnetwork" },
  "stats.keywords": { title: "关键词比较", label: "正在比较关键词…", icon: "chartscatter" },
  "stats.distribution": { title: "计算分布", label: "正在计算分布…", icon: "barchart" },
  "evidence.add": { title: "加入证据篮", label: "正在保存证据…", icon: "pin" },
  "evidence.list": { title: "读取证据篮", label: "正在读取证据…", icon: "basket" },
  "queries.save": { title: "保存查询", label: "正在保存查询…", icon: "bookmark" },
  "queries.list": { title: "读取保存的查询", label: "正在读取查询…", icon: "bookmark" },
  "export.create": { title: "创建导出", label: "正在创建导出…", icon: "filedown" },
  "jobs.get": { title: "查看任务", label: "正在查看任务…", icon: "listchecks" },
  "jobs.cancel": { title: "取消任务", label: "正在取消任务…", icon: "ban" },
  "annot.layers": { title: "列出标注层", label: "正在读取标注层…", icon: "layers" },
  "annot.create_layer": { title: "新建标注层", label: "正在新建标注层…", icon: "tags" },
  "annot.sentence": { title: "读取句子标注", label: "正在读取标注…", icon: "listtree" },
  "annot.diff": { title: "读取预标差异", label: "正在比较预标与人工…", icon: "compare" },
  "annot.stats": { title: "标注统计", label: "正在统计标签…", icon: "chartpie" },
  "annot.suggest": { title: "提出标注建议", label: "正在写入建议…", icon: "wand" },
  "annot.export": { title: "导出 CoNLL-U", label: "正在创建导出…", icon: "filedown" },
  "annot.spans": { title: "读取片段与关系", label: "正在读取片段…", icon: "squaredashed" },
  "annot.suggest_spans": { title: "提出片段建议", label: "正在写入片段建议…", icon: "wand" },
  "align.pairs": { title: "读取句对与对齐", label: "正在读取对齐…", icon: "languages" },
  "align.suggest": { title: "提出对齐建议", label: "正在写入对齐建议…", icon: "wand" },
  "annot.agreement": { title: "读取一致性", label: "正在计算一致性…", icon: "users" },
  "kb.search": { title: "检索知识库", label: "正在检索知识库…", icon: "bookopen" },
  "kb.save": { title: "保存笔记", label: "正在保存笔记…", icon: "notebookpen" },
  "kb.extract_terms": { title: "抽取术语", label: "正在抽取术语…", icon: "booka" },
  "kb.summarize": { title: "生成摘要", label: "正在生成摘要…", icon: "sparkles" },
  "kb.terms": { title: "查术语", label: "正在查术语…", icon: "booka" },
  "kb.documents": { title: "列出知识库文档", label: "正在读取知识库文档…", icon: "bookopentext" },
};
