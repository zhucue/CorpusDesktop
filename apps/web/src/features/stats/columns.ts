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
