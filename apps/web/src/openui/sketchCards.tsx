import { useCallback, useContext } from "react";
import { useNavigate } from "react-router";
import type { SearchScope, StatResult, StatRow } from "../api";
import { Empty } from "../components/common";
import { Card, ResultContext } from "../components/results/cards";
import { EChart, baseOption, type ChartTokens, type EChartsOption } from "../components/results/EChart";
import { num } from "../features/stats/columns";
import { sideOf } from "../features/stats/P10Results";
import { statLayers } from "../features/stats/StatTable";
import { useStatResult } from "../features/stats/useStatJob";
import { fmt, fmtValue } from "../lib/format";
import { rowSearchUrl, StatFoot } from "./statCards";
import "./sketch.css";

type Layers = { dep?: string };
type Link = { search_query?: string | null; search_scope?: Record<string, unknown> };

/** Opens a row's example sentences (its search_query, in its search_scope or the session scope); rows without a query do nothing. */
function useOpenRow(layers?: Layers) {
  const { projectId, scope } = useContext(ResultContext);
  const navigate = useNavigate();
  return (r: Link) => {
    if (r.search_query) navigate(rowSearchUrl(projectId, r.search_query, (r.search_scope as SearchScope | undefined) ?? scope, undefined, layers));
  };
}

function rowProps(r: Link, open: (r: Link) => void) {
  if (!r.search_query) return {};
  return {
    className: "go",
    role: "button",
    tabIndex: 0,
    title: "打开例句",
    onClick: () => open(r),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open(r);
      }
    },
  };
}

/* ---------- WordSketch ---------- */
export interface WordSketchProps {
  stat_id: string;
  lemma: string;
  relations: { relation: string; rows: ({ collocate: string; freq: number; logdice: number } & Link)[] }[];
  pos?: string;
  layers?: Layers;
}

/** One column per dependency relation: collocate, co-occurrence count, logDice; a row opens its examples. */
export function WordSketchCard(p: WordSketchProps) {
  const open = useOpenRow(p.layers);
  const relations = (p.relations ?? []).filter((r) => r.rows?.length);
  return (
    <Card
      component="WordSketch"
      icon="columns"
      title="Word Sketch"
      meta={p.pos ? `${p.lemma} · ${p.pos}` : p.lemma}
      right={`${fmt(relations.length)} 栏`}
      foot={<StatFoot statId={p.stat_id} />}
    >
      <div className="ou-body">
        {relations.length === 0 ? (
          <Empty icon="barchart" text="无结果" />
        ) : (
          <div className="sk-cols">
            {relations.map((rel) => (
              <section className="sk-col" key={rel.relation}>
                <div className="sk-col-h">
                  <span>{rel.relation}</span>
                  <span className="muted">频次 · logDice</span>
                </div>
                <table>
                  <tbody>
                    {rel.rows.map((r, i) => (
                      <tr key={i} {...rowProps(r, open)}>
                        <td className="w">{r.collocate}</td>
                        <td className="r">{fmt(r.freq)}</td>
                        <td className="r">{fmtValue(r.logdice)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

/* ---------- SketchDiff ---------- */
type DiffRow = { relation: string; collocate: string; freq_a: number; freq_b: number; diff: number } & Link;
export interface SketchDiffProps {
  stat_id: string;
  lemma_a: string;
  lemma_b: string;
  a: DiffRow[];
  common: DiffRow[];
  b: DiffRow[];
  layers?: Layers;
  /** Row counts of each side in the full result (tool side_totals); the props may hold fewer. */
  side_totals?: { a: number; common: number; b: number };
}

type Sides = { a: DiffRow[]; common: DiffRow[]; b: DiffRow[] };

/** Every row of a stored sketch_diff result by side, most distinctive first (as on the stats page); B's rows open B's search. */
export function diffSides(stat: StatResult): Sides {
  const sides: Record<"a" | "common" | "b", StatRow[]> = { a: [], common: [], b: [] };
  for (const r of stat.rows) sides[sideOf(r)].push(r);
  const diff = (r: StatRow) => num(r.values.diff) ?? 0;
  const row = (r: StatRow, b: boolean): DiffRow => ({
    relation: String(r.values.relation_label ?? r.values.relation ?? ""),
    collocate: String(r.values.collocate ?? r.values.item ?? r.key),
    freq_a: num(r.values.freq_a) ?? 0,
    freq_b: num(r.values.freq_b) ?? 0,
    diff: diff(r),
    search_query: b ? (r.search_query_b ?? r.search_query) : r.search_query,
    ...(r.search_scope ? { search_scope: r.search_scope as Record<string, unknown> } : {}),
  });
  return {
    a: [...sides.a].sort((x, y) => diff(y) - diff(x)).map((r) => row(r, false)),
    common: [...sides.common].sort((x, y) => diff(y) - diff(x)).map((r) => row(r, false)),
    b: [...sides.b].sort((x, y) => diff(x) - diff(y)).map((r) => row(r, true)),
  };
}

/**
 * Three columns — collocates favouring A, shared, favouring B — with both counts and the logDice difference.
 * The rows come from the stored result (stat_id), all of them; the props the model wrote are only the fallback
 * while it loads or when it is gone.
 */
export function SketchDiffCard(p: SketchDiffProps) {
  const stat = useStatResult(p.stat_id || null);
  const stored = stat.data?.method === "sketch_diff" ? stat.data : null;
  const sides: Sides = stored ? diffSides(stored) : { a: p.a ?? [], common: p.common ?? [], b: p.b ?? [] };
  const layers = stored ? ((stored.rows.find((r) => r.search_layers)?.search_layers ?? statLayers(stored)) as Layers | undefined) : p.layers;
  const open = useOpenRow(layers);
  const columns: [string, DiffRow[]][] = [
    [`偏 ${p.lemma_a}`, sides.a],
    ["共同", sides.common],
    [`偏 ${p.lemma_b}`, sides.b],
  ];
  const total = columns.reduce((n, [, rows]) => n + rows.length, 0);
  // the model's rows stand in for a result that is gone or still loading: say when they are only part of it
  const t = p.side_totals;
  const all = !stored && t ? (Number(t.a) || 0) + (Number(t.common) || 0) + (Number(t.b) || 0) : 0;
  return (
    <Card
      component="SketchDiff"
      icon="arrowleftright"
      title="近义词对比"
      meta={`${p.lemma_a} / ${p.lemma_b}`}
      right={total < all ? `显示 ${fmt(total)} / 共 ${fmt(all)}` : `${fmt(total)} 项`}
      foot={<StatFoot statId={p.stat_id} />}
    >
      <div className="ou-body">
        {total === 0 ? (
          <Empty icon="barchart" text="无结果" />
        ) : (
          <div className="sk-cols three">
            {columns.map(([title, rows]) => (
              <section className="sk-col" key={title}>
                <div className="sk-col-h">
                  <span>{title}</span>
                  <span className="muted">
                    {p.lemma_a} · {p.lemma_b} · 差
                  </span>
                </div>
                {rows.length === 0 ? (
                  <div className="none">无</div>
                ) : (
                  <table>
                    <tbody>
                      {rows.map((r, i) => (
                        <tr key={i} {...rowProps(r, open)}>
                          <td className="w">
                            {r.collocate}
                            {r.relation && <span className="rel">{r.relation}</span>}
                          </td>
                          <td className="r">{fmt(r.freq_a)}</td>
                          <td className="r">{fmt(r.freq_b)}</td>
                          <td className="r">{fmtValue(r.diff)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

/* ---------- CompareChart ---------- */
export interface CompareChartProps {
  stat_id: string;
  title: string;
  unit: string;
  categories: string[];
  series: { name: string; values: (number | null)[] }[];
  chart: "line" | "bar";
}

/** Several compare items over one metadata field: one series per item, lines for ordered fields, grouped bars otherwise. */
export function CompareChartCard(p: CompareChartProps) {
  const categories = p.categories ?? [];
  const series = (p.series ?? []).filter((s) => Array.isArray(s.values));
  const line = p.chart === "line";
  const key = JSON.stringify([categories, series, line]);
  const build = useCallback(
    (t: ChartTokens): EChartsOption => ({
      ...baseOption(t),
      color: t.palette,
      grid: { left: 48, right: 16, top: 12, bottom: 28 },
      tooltip: { ...(baseOption(t).tooltip as object), trigger: "axis" },
      xAxis: {
        type: "category",
        data: categories,
        axisLine: { lineStyle: { color: t.line } },
        axisTick: { show: false },
        axisLabel: { color: t.text3, fontSize: 11, hideOverlap: true },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: t.lineSoft } },
        axisLabel: { color: t.text3, fontSize: 11 },
      },
      series: series.map((s) =>
        line
          ? { name: s.name, type: "line", data: s.values, symbolSize: 6, connectNulls: false }
          : { name: s.name, type: "bar", data: s.values, barMaxWidth: 18 },
      ),
    }),
    [key], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const empty = !categories.length || !series.length;
  return (
    <Card component="CompareChart" icon={line ? "chartline" : "chartbar"} title={p.title || "对比"} meta={p.unit} right={`${fmt(series.length)} 项`} foot={<StatFoot statId={p.stat_id} />}>
      <div className="ou-body">
        {empty ? (
          <Empty icon="barchart" text="无结果" />
        ) : (
          <>
            <div className="cmp-legend">
              {series.map((s, i) => (
                <span key={s.name}>
                  <i style={{ ["--pc" as string]: `var(--c${(i % 8) + 1})` }} />
                  {s.name}
                </span>
              ))}
            </div>
            <EChart build={build} height={220} label={`${p.title || "对比"}：${series.map((s) => s.name).join("、")}`} />
          </>
        )}
      </div>
    </Card>
  );
}
