/**
 * Help page content (contracts/p11.md §三 1), kept with the code. Sources: README 查询语法,
 * doc/platform-redesign.md 语料导入 / 统计 / 权限. Metric formulas and references are not copied here:
 * GET /help/metrics serves them from engine/methods.py (the method appendix table); this file only groups
 * the metric keys by method.
 */

export interface HelpSection {
  id: string;
  title: string;
}

export const SECTIONS: HelpSection[] = [
  { id: "query", title: "查询语法" },
  { id: "import", title: "导入格式" },
  { id: "metrics", title: "统计指标" },
  { id: "roles", title: "角色与权限" },
  { id: "privacy", title: "数据与隐私" },
  { id: "errors", title: "常见错误" },
];

export interface QueryRow {
  /** Example queries; each can be copied or opened on the search page. */
  examples: string[];
  meaning: string;
  /** What the corpus needs for the example to match (layer, POS). */
  needs?: string;
}

export const QUERY_ROWS: QueryRow[] = [
  { examples: ["语言", "language"], meaning: "字串。中文、日文按字符匹配，可跨分词边界；其他语言按整词，不区分大小写" },
  { examples: ["语言/n", "/v"], meaning: "词 + 词性。UPOS 或 jieba 短标签，按语料的词性体系解析；/v 为任意动词" },
  { examples: ["语言 研究"], meaning: "相邻" },
  { examples: ["研究 $3 方法", "研究 $2-5 方法"], meaning: "词距：中间最多 3 个词；$2-5 为 2 到 5 个" },
  { examples: ["语言|语法"], meaning: "或（同一个词位）" },
  { examples: ["研究 +语言", "研究 -语言"], meaning: "同句含 / 不含。以主查询为锚计数" },
  { examples: ['"The"'], meaning: "精确词形，区分大小写" },
  { examples: ["the *", "语?"], meaning: "* 任意词；? 任意一个字符" },
  {
    examples: ["{dep=nsubj}", "学生{dep=nsubj}", "{pos=VERB,dep=root}", "{lemma=go}"],
    meaning: "依存、词性、词元属性。可单独作一个词位，或接在词后",
    needs: "需要依存或词元：CoNLL-U、Stanza 导入的语料，或标注层",
  },
  { examples: ["[偏误:时态]", "go[时态]"], meaning: "片段标签", needs: "需要片段标注层" },
];

export const QUERY_NOTES = [
  "布尔只支持“主查询 + 同句条件”，不支持括号嵌套",
  "三项计数（命中 / 句 / 文档）分开返回；总数未算完时显示“计算中”",
  "平行语料可加译文条件：只看对齐句含或不含某个查询的命中",
];

export interface FormatRow {
  format: string;
  unit: string;
  rule: string;
}

export const FORMAT_ROWS: FormatRow[] = [
  { format: "TXT", unit: "1 篇", rule: "编码自动识别：UTF-8（含或不含 BOM）、UTF-16、GB18030 / GBK；空行去掉" },
  { format: "DOCX", unit: "1 篇", rule: "正文段落与表格单元格；文本框、脚注、页眉页脚、图片不读" },
  { format: "PDF", unit: "1 篇", rule: "读文字层，元数据加页数与作者；扫描件（无文字层）不支持" },
  { format: "CSV / TSV", unit: "每行 1 篇", rule: "按列映射取正文、标题、语言与元数据；正文为空的行跳过" },
  { format: "XLSX", unit: "每行 1 篇", rule: "列映射同 CSV，可选工作表（默认第一个）；表头为第一个非空行" },
  { format: "JSONL", unit: "每行 1 篇", rule: "字段映射同 CSV；嵌套对象展开为点号键（meta.year），数组存为 JSON 文本" },
  { format: "CoNLL-U", unit: "1 篇，或每个 # newdoc 1 篇", rule: "保留词形、词元、UPOS、依存；自带分词，任何语言均可" },
  { format: "TMX", unit: "每种语言 1 篇", rule: "句对对齐，语言取 xml:lang；行内格式标签去掉" },
  { format: "Tatoeba", unit: "每种语言 1 篇", rule: "sentences / links TSV（可为 .bz2）一起上传，识别为平行语料" },
];

export const MAPPING_ROWS: [string, string][] = [
  ["正文列", "必选，1–2 列（两列以空行连接）；默认取 text / content / body / sentence / abstract / 正文 / 内容 / 句子，没有时取平均最长的列"],
  ["标题列", "默认 title / headline / 标题；没有时用“文件名 #行号”"],
  ["语言列", "默认 language / lang / 语言；没有时用上传时选的语言"],
  ["元数据列", "默认其余全部列；日期、年份作普通元数据"],
  ["预览", "CSV / TSV / JSONL 读前 256 KB；XLSX 读整个文件，不超过 50 MB"],
];

export const IMPORT_LIMITS: [string, string][] = [
  ["语言", "自动分词与标注：zh、en、ja、fr、de、es、ru；“自动”按每篇内容识别"],
  ["去重", "同一语料中正文相同（忽略空白差异）的文档跳过，导入结果列出来源"],
  ["单次上传", "不超过 500 MB"],
  ["解压后", "DOCX、XLSX、.bz2 解压后不超过 500 MB；PDF 不超过 5000 页"],
  ["知识库", "PDF / DOCX / MD / TXT 每个不超过 50 MB，一次最多 20 个；网页只能是公网地址，不超过 10 MB"],
];

export interface MetricGroup {
  title: string;
  keys: string[];
}

/** Metric keys of GET /help/metrics (engine/methods.py METRICS), grouped by statistics method. */
export const METRIC_GROUPS: MetricGroup[] = [
  { title: "频次与离散度", keys: ["per_million", "range", "dp", "dp_norm", "juilland_d"] },
  { title: "搭配", keys: ["mi", "mi3", "t", "z", "logdice", "delta_p", "ll"] },
  { title: "关键词", keys: ["ll", "log_ratio", "log_ratio_ci", "pct_diff", "odds_ratio", "significance", "bonferroni"] },
  { title: "译法（平行语料）", keys: ["dice", "ll"] },
  {
    title: "文本指标",
    keys: ["ttr", "sttr", "mtld", "lexical_density", "mean_sentence_length", "mean_dependency_distance", "flesch_reading_ease", "flesch_kincaid_grade"],
  },
  { title: "词汇等级", keys: ["coverage", "ngsl"] },
  { title: "多项对比", keys: ["mann_whitney", "spearman"] },
  { title: "词汇画像与近义词对比", keys: ["word_sketch", "logdice", "logdice_diff"] },
];

export const METRIC_NOTES = [
  "N 为范围词数，含标点；“排除标点和数字”只影响列出的项，不改 N",
  "每个结果保存参数与索引版本；点数字回到对应检索",
];

export const ROLE_ROWS: [string, string][] = [
  ["负责人", "项目全部权限；管理成员、改名、删除与恢复项目"],
  ["编辑者", "上传语料、建子库、建标注层、编辑知识库、上传词表、建语义索引"],
  ["标注者", "标注校对、检索、统计"],
  ["查看者", "检索、统计、查看标注与知识库"],
  ["平台管理员", "管理账号与内置语料；看全部项目的名称、负责人、占用空间、任务、用量与审计，不读取项目内容"],
];

export const PRIVACY_ROWS: [string, string][] = [
  ["存放", "本机 PostgreSQL 与 Docker 数据卷"],
  ["发送到外部模型", "助手对话、LLM 片段与关系预标、对齐候选（选用模型时）、文献摘要、术语抽取"],
  ["删除", "删除的项目 7 天内可由负责人或管理员恢复，之后清除；导出文件保留 30 天"],
];

export interface ErrorRow {
  code: string;
  meaning: string;
  fix: string;
}

export const ERROR_ROWS: ErrorRow[] = [
  { code: "QUERY_INVALID", meaning: "查询式无法解析", fix: "按解析行提示的位置修改" },
  { code: "INVALID_LAYER", meaning: "查询要用的标注层不存在（{dep=}、{lemma=}、[标签]）", fix: "先在标注页建对应的层，或换语料" },
  { code: "CORPUS_NOT_READY", meaning: "语料库还在导入或建索引", fix: "等任务完成后再检索" },
  { code: "SEARCH_EXPIRED", meaning: "结果集已过期", fix: "重新检索" },
  { code: "TOO_MANY_HITS", meaning: "命中超过上限", fix: "加条件或缩小范围" },
  { code: "TIMEOUT", meaning: "检索或统计超时", fix: "缩小范围或加条件" },
  { code: "PARSE_ERROR", meaning: "文件解析失败（编码、缺列、无文字层、解压后过大）", fix: "按错误中的文件名与原因修改后重试" },
  { code: "LANGUAGE_UNSUPPORTED", meaning: "语言不在自动标注范围内", fix: "指定语言，或用 CoNLL-U 导入" },
  { code: "TOO_LARGE", meaning: "上传超过 500 MB", fix: "分批上传" },
  { code: "NO_DEPENDENCIES", meaning: "词汇画像没有依存标注", fix: "先建依存层" },
  { code: "LLM_QUOTA_EXCEEDED", meaning: "本月模型用量已达上限", fix: "联系管理员" },
  { code: "MODEL_RATE_LIMITED", meaning: "模型服务限流（已自动重试 2 次）", fix: "稍后重新生成" },
  { code: "RATE_LIMITED", meaning: "请求过于频繁", fix: "稍后再试" },
  { code: "EXPORT_EXPIRED", meaning: "导出文件已超过保留期", fix: "重新导出" },
];
