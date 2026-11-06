import { Alert, Select } from "antd";
import { useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import type { CompareTestResult, StatColumn, StatResult, StatRow, TextMetricGroup } from "../../api";
import { Empty, Tip } from "../../components/common";
import { EChart, type ChartTokens, type EChartHandle } from "../../components/results/EChart";
import { fmtValue } from "../../lib/format";
import { COLUMN_TIPS, findColumn, num, rowLabel, SIGNED_COLUMNS, TEXT_METRICS } from "./columns";
import { boxplotOption, multiOption, stackedOption, type Series } from "./p10Charts";
import { rowSearchHref, statLayers } from "./StatTable";

type Ref = React.Ref<EChartHandle>;

const signed = (key: string, v: unknown) => {
  const n = num(v);
  if (n == null) return "—";
  return SIGNED_COLUMNS.has(key) && n < 0 ? `−${fmtValue(-n)}` : fmtValue(n);
};

/** p values: three decimals, small ones in scientific notation. */
export function fmtP(p: number | null | undefined): string {
  if (p == null || !Number.isFinite(p)) return "—";
  if (p === 0) return "0";
  return p < 0.001 ? p.toExponential(2) : p.toFixed(3);
}

function HeadLabel({ k, label }: { k: string; label: string }) {
  const tip = COLUMN_TIPS[k];
  return tip ? (
    <Tip title={tip}>
      <span className="col-tip">{label}</span>
    </Tip>
  ) : (
    <>{label}</>
  );
}

function ChartCard({ title, children, extra }: { title: string; children: React.ReactNode; extra?: React.ReactNode }) {
  return (
    <div className="card card-pad col gap-16 chart-card">
      <div className="row between">
        <h2>{title}</h2>
        {extra}
      </div>
      {children}
    </div>
  );
}

// ---------- 文本指标 ----------

/** text_metrics totals.groups (per metric: [{value, documents, mean, sd}]) as one entry per value; the document
 * count is that of the first metric (words: every document of the group). */
export function metricGroups(stat: StatResult): TextMetricGroup[] {
  const g = stat.totals.groups as unknown;
  if (Array.isArray(g)) return g as TextMetricGroup[];
  if (g && typeof g === "object") {
    const byValue = new Map<string, TextMetricGroup>();
    for (const [metric, list] of Object.entries(g as NonNullable<StatResult["totals"]["groups"]>)) {
      for (const e of list ?? []) {
        const cur = byValue.get(String(e.value)) ?? { value: String(e.value), documents: e.documents, mean: {}, sd: {} };
        cur.mean[metric] = e.mean;
        cur.sd[metric] = e.sd;
        byValue.set(cur.value, cur);
      }
    }
    return [...byValue.values()];
  }
  return [];
}

const metricLabel = (stat: StatResult, key: string) => stat.columns.find((c) => c.key === key)?.label ?? TEXT_METRICS.find((m) => m.key === key)?.label ?? key;

function notesOf(stat: StatResult): string[] {
  const n = stat.totals.notes;
  return Array.isArray(n) ? n : n ? [n] : [];
}

/** The row value that names a document's group: `group`, or the group_by field itself. */
function groupKey(stat: StatResult): string | null {
  const field = (stat.params as { group_by?: string | null }).group_by;
  if (!field) return null;
  if (stat.columns.some((c) => c.key === "group") || stat.rows.some((r) => "group" in r.values)) return "group";
  return field;
}

function TextMetricsView({ stat, table, chartRef }: { stat: StatResult; table: React.ReactNode; chartRef: Ref }) {
  const groups = metricGroups(stat);
  const field = (stat.params as { group_by?: string | null }).group_by ?? null;
  const metricCols = stat.columns.filter((c) => c.type === "number" && TEXT_METRICS.some((m) => m.key === c.key));
  const [metric, setMetric] = useState(metricCols[0]?.key ?? "");
  const gk = groupKey(stat);
  const boxes = useMemo(() => {
    const by = new Map<string, number[]>();
    for (const g of groups) by.set(String(g.value), []);
    for (const r of stat.rows) {
      const v = num(r.values[metric]);
      const name = gk ? String(r.values[gk] ?? "（无）") : "全部";
      if (!by.has(name)) by.set(name, []);
      if (v != null) by.get(name)!.push(v);
    }
    return [...by.entries()].map(([name, values]) => ({ name, values }));
  }, [stat, metric, gk, groups]);
  const build = useCallback((t: ChartTokens) => boxplotOption(t, boxes, metricLabel(stat, metric)), [boxes, metric, stat]);
  const metricsInGroups = metricCols.filter((c) => groups.some((g) => g.mean && c.key in g.mean));
  const notes = notesOf(stat);

  return (
    <div className="col gap-20">
      {table}
      {notes.length > 0 && <Alert type="info" showIcon message={notes.join("；")} />}
      <div className="res">
        {groups.length > 0 ? (
          <div className="card">
            <div className="card-head">
              <h2>分组汇总 · {field}</h2>
            </div>
            <div className="stat-scroll">
              <table className="tbl mid stat-tbl" aria-label="分组汇总">
                <thead>
                  <tr>
                    <th>{field}</th>
                    <th className="r">文档数</th>
                    {metricsInGroups.map((c) => (
                      <th key={c.key} className="r">
                        <HeadLabel k={c.key} label={c.label} />
                        <span className="muted"> · 均值 ± SD</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {groups.map((g) => (
                    <tr key={g.value}>
                      <td style={{ fontWeight: 500 }}>{g.value}</td>
                      <td className="r num">{fmtValue(g.documents)}</td>
                      {metricsInGroups.map((c) => (
                        <td key={c.key} className="r num">
                          {g.mean?.[c.key] == null ? "—" : `${signed(c.key, g.mean[c.key])} ± ${g.sd?.[c.key] == null ? "—" : fmtValue(g.sd[c.key])}`}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div />
        )}
        {metricCols.length > 0 && (
          <ChartCard
            title={`箱线图 · ${metricLabel(stat, metric)}`}
            extra={<Select size="small" value={metric} onChange={setMetric} style={{ width: 170 }} aria-label="图表指标" options={metricCols.map((c) => ({ value: c.key, label: c.label }))} />}
          >
            <EChart ref={chartRef} build={build} height={260} label="文本指标箱线图" />
          </ChartCard>
        )}
      </div>
    </div>
  );
}

// ---------- 词汇等级 ----------

const OFF_LIST = "表外";
const isOffList = (c: { key: string; label: string }) => c.label === OFF_LIST || c.key === "off_list";
const LEVEL_COLUMN = /^(level_\d+|off_list)$/;
const stripPct = (label: string) => label.replace(/\s*%$/, "");

/** Long shape (by=corpus): one row per level. Wide shape (by=document / field): one row per part, a column per level. */
function vocabSeries(stat: StatResult): { categories: string[]; series: (Series & { off: boolean })[] } {
  const levelCol = stat.columns.find((c) => c.key === "level");
  if (levelCol) {
    const cov = findColumn(stat.columns, /coverage|pct/i, /覆盖率|%/);
    return {
      categories: [stat.scope.name],
      series: stat.rows.map((r) => {
        const name = String(r.values.level ?? r.key);
        return { name, values: [num(cov ? r.values[cov.key] : null)], off: isOffList({ key: r.key, label: name }) };
      }),
    };
  }
  const cols = stat.columns.filter((c) => c.type === "number" && LEVEL_COLUMN.test(c.key));
  const rows = stat.rows.slice(0, 60);
  return {
    categories: rows.map((r) => rowLabel(stat, r)),
    series: cols.map((c) => ({ name: stripPct(c.label), values: rows.map((r) => num(r.values[c.key])), off: isOffList({ key: c.key, label: stripPct(c.label) }) })),
  };
}

/** by=corpus: the most frequent off-list words (totals.off_list), each back to its examples. */
function OffListCard({ stat, projectId }: { stat: StatResult; projectId: string }) {
  const navigate = useNavigate();
  const words = stat.totals.off_list ?? [];
  if (!words.length) return null;
  const scope = stat.rows[0]?.search_scope ?? { corpus_id: stat.scope.corpus_id };
  return (
    <div className="card" aria-label="表外词">
      <div className="card-head">
        <h2>表外词 · 前 {words.length}</h2>
      </div>
      <div className="stat-scroll" style={{ maxHeight: 320 }}>
        <table className="tbl mid stat-tbl">
          <thead>
            <tr>
              <th>词</th>
              <th className="r">词次</th>
            </tr>
          </thead>
          <tbody>
            {words.map((w) => (
              <tr key={w.item}>
                <td style={{ fontWeight: 500 }}>{w.item}</td>
                <td className="r num">
                  {w.search_query ? (
                    <button className="numlink" type="button" onClick={() => navigate(rowSearchHref(projectId, w.search_query!, scope))}>
                      {fmtValue(w.freq)}
                    </button>
                  ) : (
                    fmtValue(w.freq)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function VocabView({ stat, projectId, table, chartRef }: { stat: StatResult; projectId: string; table: React.ReactNode; chartRef: Ref }) {
  const { categories, series } = useMemo(() => vocabSeries(stat), [stat]);
  const build = useCallback(
    (t: ChartTokens) => {
      let k = 0;
      const colors = series.map((s) => (s.off ? t.text3 : t.palette[k++ % 8]));
      return stackedOption(t, categories, series, colors);
    },
    [categories, series],
  );
  return (
    <div className="res">
      <div className="col gap-20">
        {table}
        <OffListCard stat={stat} projectId={projectId} />
      </div>
      <ChartCard title="等级覆盖率 · 词次 %">
        <EChart ref={chartRef} build={build} height={Math.max(120, categories.length * 28 + 48)} label="词汇等级堆叠柱图" />
      </ChartCard>
    </div>
  );
}

// ---------- 对比 ----------

function pmColumns(stat: StatResult): StatColumn[] {
  const nums = stat.columns.filter((c) => c.type === "number");
  const pm = nums.filter((c) => c.unit === "每百万词" || /per_?million|_pm$|^pm_/i.test(c.key) || /每百万/.test(c.label));
  return pm.length ? pm : nums;
}

function TestCard({ stat }: { stat: StatResult }) {
  const t = stat.totals;
  const test = t.test as CompareTestResult | null | undefined;
  const ll = num(t.comparison?.ll);
  const lr = num(t.comparison?.log_ratio);
  if (!test && ll == null && lr == null) return null;
  const cell = (label: string, v: string) => (
    <div className="col" style={{ gap: 2 }}>
      <span className="small muted">{label}</span>
      <span className="num" style={{ fontSize: 16, fontWeight: 600 }}>
        {v}
      </span>
    </div>
  );
  return (
    <div className="card card-pad col gap-12" aria-label="检验结果">
      {(ll != null || lr != null) && (
        <div className="row gap-20" style={{ flexWrap: "wrap" }}>
          <h3 style={{ minWidth: 120 }}>两项差异</h3>
          {ll != null && cell("LL", `${fmtValue(ll)}${t.comparison?.significance ? ` ${t.comparison.significance}` : ""}`)}
          {lr != null && cell("Log Ratio", signed("log_ratio", lr))}
        </div>
      )}
      {test?.method === "mann_whitney" && (
        <div className="row gap-20" style={{ flexWrap: "wrap" }}>
          <h3 style={{ minWidth: 120 }}>Mann-Whitney U</h3>
          {cell("U", fmtValue(test.u))}
          {cell("z", signed("z", test.z))}
          {cell("p", fmtP(test.p))}
          {cell("r", signed("z", test.r))}
          {cell("n", `${test.n1} / ${test.n2} 篇`)}
        </div>
      )}
      {test?.method === "spearman" && (
        <div className="col gap-12">
          <h3>Spearman · {test.field}</h3>
          <table className="tbl mid" aria-label="Spearman">
            <thead>
              <tr>
                <th>项</th>
                <th className="r">ρ</th>
                <th className="r">p</th>
                <th className="r">n（篇）</th>
              </tr>
            </thead>
            <tbody>
              {test.items.map((it) => (
                <tr key={it.label}>
                  <td style={{ fontWeight: 500 }}>{it.label}</td>
                  <td className="r num">{signed("z", it.rho)}</td>
                  <td className="r num">{fmtP(it.p)}</td>
                  <td className="r num">{fmtValue(it.n)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CompareView({ stat, table, chartRef }: { stat: StatResult; table: React.ReactNode; chartRef: Ref }) {
  const by = (stat.params as { by?: string | null }).by;
  const { categories, series, kind } = useMemo(() => {
    const cats = stat.rows.map((r) => rowLabel(stat, r));
    if (!by) {
      const pm = findColumn(stat.columns, /per_?million/i, /每百万/);
      return { categories: cats, series: [{ name: "每百万词", values: stat.rows.map((r) => num(pm ? r.values[pm.key] : null)) }], kind: "bar" as const };
    }
    const cols = pmColumns(stat);
    // a numeric field (年份) reads as a line; its value column is typed number
    const numeric = stat.columns[0]?.type === "number";
    return {
      categories: cats,
      series: cols.map((c) => ({ name: c.label.replace(/\s*每百万词$/, ""), values: stat.rows.map((r) => num(r.values[c.key])) })),
      kind: numeric ? ("line" as const) : ("bar" as const),
    };
  }, [stat, by]);
  const build = useCallback((t: ChartTokens) => multiOption(t, categories, series, kind, "每百万词"), [categories, series, kind]);
  return (
    <div className="col gap-20">
      <TestCard stat={stat} />
      <div className="res">
        {table}
        <ChartCard title={by ? `每百万词 · 按 ${by}` : "每百万词"}>
          <EChart ref={chartRef} build={build} height={280} label="对比图" />
        </ChartCard>
      </div>
    </div>
  );
}

// ---------- 词汇画像 / 近义词对比 ----------

/** Relation columns in totals.relations order ({key, label}); rows grouped by values.relation (the key). */
function relationsOf(stat: StatResult): { name: string; rows: StatRow[] }[] {
  const by = new Map<string, { name: string; rows: StatRow[] }>();
  for (const r of stat.totals.relations ?? []) by.set(r.key, { name: r.label, rows: [] });
  for (const r of stat.rows) {
    const key = String(r.values.relation ?? "");
    if (!by.has(key)) by.set(key, { name: String(r.values.relation_label ?? key), rows: [] });
    by.get(key)!.rows.push(r);
  }
  return [...by.values()];
}

function collocateOf(stat: StatResult, r: StatRow): string {
  const c = findColumn(stat.columns, /^(collocate|item|lemma|word)$/);
  if (c && r.values[c.key] != null) return String(r.values[c.key]);
  const s = stat.columns.find((x) => x.type === "string" && x.key !== "relation");
  return s && r.values[s.key] != null ? String(r.values[s.key]) : r.key;
}

function useGo(stat: StatResult, projectId: string) {
  const navigate = useNavigate();
  return (r: StatRow, q: string | null | undefined = r.search_query) => q && navigate(rowSearchHref(projectId, q, r.search_scope, r.search_layers ?? statLayers(stat)));
}

/** The collocate, a link to its examples when the relation has an equivalent query (sketch diff B: search_query_b). */
function Collocate({ stat, row, go, query = row.search_query }: { stat: StatResult; row: StatRow; go: (r: StatRow, q?: string | null) => void; query?: string | null }) {
  const text = collocateOf(stat, row);
  return query ? (
    <button className="numlink" type="button" onClick={() => go(row, query)} title="回到例句">
      {text}
    </button>
  ) : (
    <span>{text}</span>
  );
}

function SketchView({ stat, projectId, head }: { stat: StatResult; projectId: string; head: React.ReactNode }) {
  const go = useGo(stat, projectId);
  const rels = relationsOf(stat);
  return (
    <div className="col gap-20">
      <div className="card">{head}</div>
      {stat.rows.length === 0 ? (
        <div className="card">
          <Empty icon="columns" text="当前参数下无搭配" />
        </div>
      ) : (
        <div className="sketch-grid">
          {rels.map((rel) => (
            <section className="card sketch-col" key={rel.name} aria-label={rel.name}>
              <div className="card-head">
                <h3>{rel.name}</h3>
                <span className="res-meta num">{rel.rows.length}</span>
              </div>
              {rel.rows.length === 0 ? (
                <div className="sketch-none muted">无</div>
              ) : (
                <table className="tbl mid stat-tbl">
                  <thead>
                    <tr>
                      <th>搭配词</th>
                      <th className="r">共现频次</th>
                      <th className="r">
                        <HeadLabel k="logdice" label="logDice" />
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rel.rows.map((r, i) => (
                      <tr key={r.key + i}>
                        <td>
                          <Collocate stat={stat} row={r} go={go} />
                        </td>
                        <td className="r num">{fmtValue(r.values.freq)}</td>
                        <td className="r num">{fmtValue(r.values.logdice)}</td>
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
  );
}

type Side = "a" | "common" | "b";

/** Side of a sketch-diff row: the API's `side`, else exclusive collocates by zero frequency. */
export function sideOf(r: StatRow): Side {
  const s = String(r.values.group ?? r.values.side ?? "").toLowerCase();
  if (s === "a") return "a";
  if (s === "b") return "b";
  if (s === "common" || s === "both") return "common";
  const fa = num(r.values.freq_a) ?? 0;
  const fb = num(r.values.freq_b) ?? 0;
  if (fa > 0 && fb === 0) return "a";
  if (fb > 0 && fa === 0) return "b";
  return "common";
}

function SketchDiffView({ stat, projectId, head }: { stat: StatResult; projectId: string; head: React.ReactNode }) {
  const go = useGo(stat, projectId);
  const p = stat.params as { lemma_a?: string; lemma_b?: string };
  const a = p.lemma_a ?? "A";
  const b = p.lemma_b ?? "B";
  const rels = relationsOf(stat);
  const diff = (r: StatRow) => num(r.values.diff) ?? 0;
  const list = (rows: StatRow[], side: Side) => {
    const sorted = [...rows].sort((x, y) => (side === "b" ? diff(x) - diff(y) : diff(y) - diff(x)));
    if (!sorted.length) return <div className="sketch-none muted">无</div>;
    return (
      <table className="tbl mid stat-tbl">
        <thead>
          <tr>
            <th>搭配词</th>
            {side !== "b" && <th className="r">{a}</th>}
            {side !== "a" && <th className="r">{b}</th>}
            <th className="r">
              <HeadLabel k="diff" label="diff" />
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={r.key + i}>
              <td>
                <Collocate stat={stat} row={r} go={go} query={side === "b" ? (r.search_query_b ?? r.search_query) : r.search_query} />
              </td>
              {side !== "b" && <td className="r num">{fmtValue(r.values.freq_a)}</td>}
              {side !== "a" && <td className="r num">{fmtValue(r.values.freq_b)}</td>}
              <td className="r num">{signed("diff", r.values.diff)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  };
  return (
    <div className="col gap-20">
      <div className="card">{head}</div>
      {stat.rows.length === 0 ? (
        <div className="card">
          <Empty icon="diff" text="当前参数下无搭配" />
        </div>
      ) : (
        rels.map((rel) => (
          <section className="card" key={rel.name} aria-label={rel.name}>
            <div className="card-head">
              <h3>{rel.name}</h3>
            </div>
            <div className="diff-cols">
              {(
                [
                  ["a", `偏 ${a}`],
                  ["common", "共同"],
                  ["b", `偏 ${b}`],
                ] as [Side, string][]
              ).map(([side, title]) => (
                <div key={side} className="diff-col" aria-label={title}>
                  <h4>{title}</h4>
                  {list(
                    rel.rows.filter((r) => sideOf(r) === side),
                    side,
                  )}
                </div>
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

/** Result body of a P10 method; `head` is the card header (title, meta, export), `table` the generic result table card. */
export function P10Result({ stat, projectId, head, table, chartRef }: { stat: StatResult; projectId: string; head: React.ReactNode; table: React.ReactNode; chartRef: Ref }) {
  if (stat.method === "word_sketch") return <SketchView stat={stat} projectId={projectId} head={head} />;
  if (stat.method === "sketch_diff") return <SketchDiffView stat={stat} projectId={projectId} head={head} />;
  if (stat.rows.length === 0) return <>{table}</>;
  if (stat.method === "text_metrics") return <TextMetricsView stat={stat} table={table} chartRef={chartRef} />;
  if (stat.method === "vocab_profile") return <VocabView stat={stat} projectId={projectId} table={table} chartRef={chartRef} />;
  if (stat.method === "compare") return <CompareView stat={stat} table={table} chartRef={chartRef} />;
  return <>{table}</>;
}
