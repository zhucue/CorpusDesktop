import { useContext } from "react";
import { Link, useNavigate } from "react-router";
import type { SearchScope } from "../api";
import { Empty } from "../components/common";
import { Card, ResultContext } from "../components/results/cards";
import { Icon } from "../components/Icon";
import { fmt, fmtValue } from "../lib/format";

type Aligned = { op: "+" | "-"; query: string };

/**
 * Search page link of a stat row (contracts/p8.md §一、§四): q, scope (the row's search_scope, else the session scope)
 * and, for translation rows, `aligned` as JSON {op, query} — same convention as the `layers` parameter.
 */
export function rowSearchUrl(projectId: string, query: string, scope: SearchScope | null, aligned?: Aligned): string {
  const p = new URLSearchParams({ q: query });
  if (scope) p.set("scope", JSON.stringify(scope));
  if (aligned) p.set("aligned", JSON.stringify({ op: aligned.op, query: aligned.query }));
  return `/p/${projectId}/search?${p.toString()}`;
}

function StatFoot({ statId }: { statId: string }) {
  const { projectId } = useContext(ResultContext);
  return (
    <Link className="btn xs" to={`/p/${projectId}/stats?stat=${encodeURIComponent(statId)}`}>
      <Icon name="external" size={14} />
      在统计中打开
    </Link>
  );
}

const BY_LABELS: Record<string, string> = { word: "词形", lemma: "词元", pos: "词性", left1: "左一词", right1: "右一词" };
const byLabel = (by: string) => BY_LABELS[by] ?? (by.startsWith("meta:") ? by.slice(5) : by);

/* ---------- BreakdownTable ---------- */
export interface BreakdownTableProps {
  stat_id: string;
  query: string;
  by: string;
  rows: { item: string; hits: number; pct: number; per_million: number; search_query?: string | null; search_scope?: Record<string, unknown> }[];
}

export function BreakdownTableCard(p: BreakdownTableProps) {
  const { projectId, scope } = useContext(ResultContext);
  const navigate = useNavigate();
  const rows = p.rows ?? [];
  return (
    <Card component="BreakdownTable" icon="listordered" title="命中分解" meta={`${p.query} · 按${byLabel(p.by)}`} right={`${fmt(rows.length)} 项`} foot={<StatFoot statId={p.stat_id} />}>
      <div className="ou-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
        {rows.length === 0 ? (
          <Empty icon="barchart" text="无结果" />
        ) : (
          <table className="tbl mid">
            <thead>
              <tr>
                <th>{byLabel(p.by)}</th>
                <th className="r">命中</th>
                <th className="r">占比 %</th>
                <th className="r">每百万词</th>
                <th />
              </tr>
            </thead>
            <tbody className="stagger">
              {rows.map((r, i) => (
                <tr key={i} style={{ ["--i" as string]: i }}>
                  <td style={{ fontWeight: 500 }}>{r.item}</td>
                  <td className="r num">{fmt(r.hits)}</td>
                  <td className="r num">{fmtValue(r.pct, 1)}</td>
                  <td className="r num">{fmtValue(r.per_million, 1)}</td>
                  <td className="r">
                    <button
                      className="back"
                      type="button"
                      disabled={!r.search_query}
                      onClick={() => r.search_query && navigate(rowSearchUrl(projectId, r.search_query, (r.search_scope as SearchScope | undefined) ?? scope))}
                    >
                      例句
                      <Icon name="right" size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}

/* ---------- TranslationTable ---------- */
export interface TranslationTableProps {
  stat_id: string;
  query: string;
  measure: string;
  rows: {
    item: string;
    cooc: number;
    pct: number;
    score: number;
    search_query?: string | null;
    search_aligned?: Aligned;
    search_scope?: Record<string, unknown>;
  }[];
}

/** A translation row opens the search page with its search_query plus search_aligned; a row without both has no 例句 link. */
export function TranslationTableCard(p: TranslationTableProps) {
  const { projectId, scope } = useContext(ResultContext);
  const navigate = useNavigate();
  const rows = p.rows ?? [];
  const measure = p.measure === "ll" ? "LL" : "Dice";
  const open = (r: TranslationTableProps["rows"][number]) => {
    if (r.search_query && r.search_aligned?.query) navigate(rowSearchUrl(projectId, r.search_query, (r.search_scope as SearchScope | undefined) ?? scope, r.search_aligned));
  };
  return (
    <Card component="TranslationTable" icon="languages" title="译法" meta={p.query} right={`${fmt(rows.length)} 项`} foot={<StatFoot statId={p.stat_id} />}>
      <div className="ou-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
        {rows.length === 0 ? (
          <Empty icon="barchart" text="无结果" />
        ) : (
          <table className="tbl mid">
            <thead>
              <tr>
                <th>译文词</th>
                <th className="r">共现句</th>
                <th className="r">占命中句 %</th>
                <th className="r">{measure}</th>
                <th />
              </tr>
            </thead>
            <tbody className="stagger">
              {rows.map((r, i) => (
                <tr key={i} style={{ ["--i" as string]: i }}>
                  <td style={{ fontWeight: 500 }}>{r.item}</td>
                  <td className="r num">{fmt(r.cooc)}</td>
                  <td className="r num">{fmtValue(r.pct, 1)}</td>
                  <td className="r num" style={{ color: "var(--accent)", fontWeight: 600 }}>
                    {fmtValue(r.score)}
                  </td>
                  <td className="r">
                    <button className="back" type="button" disabled={!r.search_query || !r.search_aligned?.query} onClick={() => open(r)}>
                      例句
                      <Icon name="right" size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}
