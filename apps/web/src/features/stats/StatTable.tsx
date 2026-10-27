import { useNavigate } from "react-router";
import type { EvidenceInput, SearchRequest, SearchScope, StatColumn, StatResult, StatRow } from "../../api";
import { PinButton } from "../../components/global/evidence";
import { Icon } from "../../components/Icon";
import { fmtValue } from "../../lib/format";
import { num, rowLabel } from "./columns";

export const methodLabels: Record<StatResult["method"], string> = {
  frequency: "频次",
  ngrams: "n-gram",
  collocations: "搭配",
  keywords: "关键词",
  distribution: "分布",
};

/** URL of the search page for a stat row ("回到例句"). */
export function rowSearchHref(projectId: string, query: string, scope: SearchScope, layers?: SearchRequest["layers"]): string {
  const p = new URLSearchParams({ q: query, scope: JSON.stringify(scope) });
  // rows counted on annotation layers ({pos=}, {dep=}, [标签]) must search the same layers
  if (layers && Object.keys(layers).length) p.set("layers", JSON.stringify(layers));
  return `/p/${projectId}/search?${p.toString()}`;
}

/** The stat's annotation layers (params.layers), without empty entries. */
export function statLayers(stat: StatResult): SearchRequest["layers"] | undefined {
  const l = (stat.params as { layers?: Record<string, string | null> } | null)?.layers;
  if (!l) return undefined;
  const out: Record<string, string> = {};
  for (const k of ["pos", "dep", "span"] as const) if (l[k]) out[k] = l[k]!;
  return Object.keys(out).length ? out : undefined;
}

/** Column whose number links to the examples (frequency-like). */
function linkColumn(stat: StatResult): string | undefined {
  const keys = ["freq", "target_freq", "hits"];
  return stat.columns.find((c) => keys.includes(c.key))?.key ?? stat.columns.find((c) => c.type === "number")?.key;
}

export function rowEvidence(stat: StatResult, row: StatRow): EvidenceInput {
  const lk = linkColumn(stat);
  const v = lk ? row.values[lk] : null;
  return {
    kind: "stat_row",
    ref: { stat_id: stat.id, row_key: row.key, search_query: row.search_query ?? undefined, scope: row.search_scope },
    text: `${rowLabel(stat, row)}${v != null ? ` · ${fmtValue(v)}` : ""}`,
    source: `${methodLabels[stat.method]} · ${stat.scope.name}`,
  };
}

function Cell({ col, value }: { col: StatColumn; value: unknown }) {
  if (value == null || value === "") return <span className="muted">—</span>;
  if (col.type === "number") {
    const n = num(value);
    if (col.key === "log_ratio" && n != null) return <>{(n < 0 ? "−" : "") + fmtValue(Math.abs(n))}</>;
    return <>{fmtValue(n ?? value)}</>;
  }
  return <>{String(value)}</>;
}

/** Result table: numbers right-aligned in mono; the frequency number and "回到例句" open the search page. */
export function StatTable({
  stat,
  projectId,
  highlight,
  selected,
  cellBar,
}: {
  stat: StatResult;
  projectId: string;
  highlight?: string;
  selected?: number | null;
  cellBar?: string;
}) {
  const navigate = useNavigate();
  const link = linkColumn(stat);
  const barMax = cellBar ? Math.max(...stat.rows.map((r) => num(r.values[cellBar]) ?? 0), 1) : 1;
  const go = (q: string | null | undefined, row: StatRow) => q && navigate(rowSearchHref(projectId, q, row.search_scope, statLayers(stat)));
  const coll = stat.method === "collocations";

  return (
    <table className="tbl mid stat-tbl">
      <thead>
        <tr>
          <th style={{ width: 44 }}>#</th>
          {stat.columns.map((c) => (
            <th key={c.key} className={c.type === "number" ? "r" : undefined}>
              {c.label}
              {c.unit ? <span className="muted"> · {c.unit}</span> : null}
            </th>
          ))}
          <th style={{ width: coll ? 150 : 96 }} />
        </tr>
      </thead>
      <tbody className="stagger">
        {stat.rows.map((row, i) => (
          <tr key={row.key + i} style={{ ["--i" as string]: i }} className={selected === i ? "sel" : undefined}>
            <td className="mono muted small">{i + 1}</td>
            {stat.columns.map((c) => {
              const v = row.values[c.key];
              const isNum = c.type === "number";
              return (
                <td
                  key={c.key}
                  className={isNum ? "r num" : undefined}
                  style={c.key === highlight ? { color: "var(--accent)", fontWeight: 600 } : c.type === "string" && c === stat.columns[0] ? { fontWeight: 500 } : undefined}
                >
                  {c.key === link && row.search_query && v != null ? (
                    <button className="numlink" type="button" onClick={() => go(row.search_query, row)}>
                      <Cell col={c} value={v} />
                    </button>
                  ) : (
                    <Cell col={c} value={v} />
                  )}
                  {c.key === cellBar && (
                    <span className="cell-bar" style={{ ["--i" as string]: i }}>
                      <i style={{ ["--v" as string]: `${(((num(v) ?? 0) / barMax) * 100).toFixed(0)}%` }} />
                    </span>
                  )}
                </td>
              );
            })}
            <td className="r">
              <span className="row" style={{ justifyContent: "flex-end", gap: 6 }}>
                {coll ? (
                  <>
                    <button className="back" type="button" disabled={!row.search_query} onClick={() => go(row.search_query, row)} title="节点词在左、搭配词在右">
                      右侧
                      <Icon name="right" size={14} />
                    </button>
                    <button className="back" type="button" disabled={!row.search_query_reverse} onClick={() => go(row.search_query_reverse, row)} title="搭配词在左、节点词在右">
                      左侧
                      <Icon name="right" size={14} />
                    </button>
                  </>
                ) : (
                  <button className="back" type="button" disabled={!row.search_query} onClick={() => go(row.search_query, row)}>
                    回到例句
                    <Icon name="right" size={14} />
                  </button>
                )}
                <PinButton input={rowEvidence(stat, row)} />
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
