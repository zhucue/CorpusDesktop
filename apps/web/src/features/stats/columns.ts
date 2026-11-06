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
};

/** Columns that can be negative; shown with a true minus sign. */
export const SIGNED_COLUMNS = new Set(["log_ratio", "log_ratio_ci_low", "log_ratio_ci_high", "pct_diff", "delta_p_node", "delta_p_coll", "z", "t"]);

/** Row value key of a collocation measure: ΔP has two columns, sorted by the node → collocate one. */
export function measureKey(m: string): string {
  return m === "delta_p" ? "delta_p_node" : m;
}
