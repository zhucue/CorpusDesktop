import type { SearchScope, StatColumn, StatResult, StatRow } from "../../api";

/** Find a column by key or label pattern; the contract fixes labels but not keys. */
export function findColumn(columns: StatColumn[], keys: RegExp, labels?: RegExp): StatColumn | undefined {
  return columns.find((c) => keys.test(c.key)) ?? (labels ? columns.find((c) => labels.test(c.label)) : undefined);
}

export function num(v: unknown): number | null {
  if (typeof v === "number") return v;
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v);
  return null;
}

export function firstNumberColumn(columns: StatColumn[]): StatColumn | undefined {
  return columns.find((c) => c.type === "number");
}

export interface DistRow {
  label: string;
  hits: number | null;
  tokens: number | null;
  perMillion: number | null;
  query: string | null;
  scope: SearchScope;
}

export function distRows(stat: StatResult): DistRow[] {
  const hits = findColumn(stat.columns, /^hits$|hit/i, /命中/) ?? firstNumberColumn(stat.columns);
  const tokens = findColumn(stat.columns, /^tokens$|token|words/i, /词数/);
  const pm = findColumn(stat.columns, /per_?million|pm/i, /每百万/);
  const label = stat.columns.find((c) => c.type === "string");
  return stat.rows.map((r) => ({
    label: String((label && r.values[label.key]) ?? r.key),
    hits: num(hits ? r.values[hits.key] : null),
    tokens: num(tokens ? r.values[tokens.key] : null),
    perMillion: num(pm ? r.values[pm.key] : null),
    query: r.search_query,
    scope: r.search_scope,
  }));
}

/** Label shown for a row: the first string column, falling back to the row key. */
export function rowLabel(stat: Pick<StatResult, "columns">, row: StatRow): string {
  const c = stat.columns.find((x) => x.type === "string");
  const v = c ? row.values[c.key] : null;
  return v != null && v !== "" ? String(v) : row.key;
}

/** One-line formula shown when hovering a column header (contracts/p8.md §二、§三、§四). */
export const COLUMN_TIPS: Record<string, string> = {
  per_million: "频次 / 范围词数 × 1,000,000",
  pct: "该项命中 / 全部命中 × 100",
  range: "出现该项的部分数",
  range_pct: "range / 部分总数 × 100",
  dp: "DP = ½ Σ|vᵢ − sᵢ|，vᵢ = 部分频次 / 总频次，sᵢ = 部分词数 / 范围词数；0 为均匀，越大越集中",
  dp_norm: "DPnorm = DP / (1 − min sᵢ)",
  juilland_d: "D = 1 − CV / √(n − 1)，CV 为各部分相对频率 fᵢ / 部分词数的变异系数",
  ll: "对数似然比 G²（2×2 列联表）",
  log_ratio: "log₂(目标每百万 / 参照每百万)，0 次按 0.5 平滑",
  pct_diff: "%DIFF = (目标每百万 − 参照每百万) / 参照每百万 × 100，参照为 0 时按 0.5 平滑",
  odds_ratio: "OR = (a / (A − a)) / (b / (B − b))，a、b 为目标、参照频次，A、B 为两库词数",
  log_ratio_ci_low: "Log Ratio 95% 区间下限，SE = √(1/a + 1/b)",
  log_ratio_ci_high: "Log Ratio 95% 区间上限，SE = √(1/a + 1/b)",
  bonferroni: "按检验词型数做 Bonferroni 校正后的显著性（0.05 / 0.01 / 0.001）",
  logdice: "logDice = 14 + log₂(2O / (f节点 + f搭配))",
  mi: "MI = log₂(O / E)",
  mi3: "MI3 = log₂(O³ / E)",
  t: "t = (O − E) / √O",
  z: "z = (O − E) / √E",
  delta_p_node: "ΔP = P(搭配词 | 节点) − P(搭配词 | 非节点)",
  delta_p_coll: "ΔP = P(节点 | 搭配词) − P(节点 | 非搭配词)",
  dice: "Dice = 2a / (n + b)，a 共现句数，n 命中句数，b 目标侧含该词句数",
  // P10 text metrics (contracts/p10.md §一)
  ttr: "TTR = 词种数 / 词数（不含标点）",
  sttr: "STTR：按 STTR 窗口词数分段，各段 TTR 的均值；最后不足一段的不计；词数 < 100 为空",
  mtld: "MTLD：顺序累计 TTR 降到 0.72 记一个因子，词数 / 因子数，正反两向取均值（McCarthy & Jarvis 2010）；词数 < 100 为空",
  lexical_density: "实词数 / 词数；实词 = NOUN、PROPN、VERB、ADJ、ADV（jieba n、v、a、d）",
  mean_sentence_length: "词数 / 句数",
  mean_dependency_distance: "有依存的句子中 |head − i| 的均值，不含根；无依存为空",
  flesch_reading_ease: "206.835 − 1.015 × 词数/句数 − 84.6 × 音节数/词数（英文）",
  flesch_kincaid_grade: "0.39 × 词数/句数 + 11.8 × 音节数/词数 − 15.59（英文）",
  // P10 vocab profile and compare
  coverage: "该等级词次 / 词数 × 100",
  doc_freq_pct: "有命中的文档数 / 文档数 × 100",
  logdice_a: "logDice = 14 + log₂(2O / (f节点 + f搭配))，节点为 A",
  logdice_b: "logDice = 14 + log₂(2O / (f节点 + f搭配))，节点为 B",
  diff: "logDice A − logDice B",
};

/** Text metric keys in display order with their labels (contracts/p10.md §一). */
export const TEXT_METRICS: { key: string; label: string }[] = [
  { key: "ttr", label: "TTR" },
  { key: "sttr", label: "STTR" },
  { key: "mtld", label: "MTLD" },
  { key: "lexical_density", label: "词汇密度" },
  { key: "mean_sentence_length", label: "平均句长" },
  { key: "mean_dependency_distance", label: "平均依存距离" },
  { key: "flesch_reading_ease", label: "Flesch Reading Ease" },
  { key: "flesch_kincaid_grade", label: "Flesch-Kincaid Grade" },
];

/** Columns that can be negative; shown with a true minus sign. */
export const SIGNED_COLUMNS = new Set(["log_ratio", "log_ratio_ci_low", "log_ratio_ci_high", "pct_diff", "delta_p_node", "delta_p_coll", "z", "t", "diff", "flesch_reading_ease", "flesch_kincaid_grade"]);

/** Row value key of a collocation measure: ΔP has two columns, sorted by the node → collocate one. */
export function measureKey(m: string): string {
  return m === "delta_p" ? "delta_p_node" : m;
}
