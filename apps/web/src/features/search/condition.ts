/** Query with the 结果内筛选 term as a same-sentence condition: `+term` (含) or `-term` (不含). */
export function withCondition(query: string, op: "+" | "-", term: string): string {
  return `${query.trim()} ${op}${term.trim()}`;
}
