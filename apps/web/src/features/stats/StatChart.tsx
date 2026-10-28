import { forwardRef, useCallback, useState } from "react";
import type { StatResult } from "../../api";
import { baseOption, EChart, type ChartTokens, type EChartHandle, type EChartsOption } from "../../components/results/EChart";
import { posCat } from "../../lib/pos";
import { fmtValue } from "../../lib/format";
import { distRows, num, rowLabel } from "./columns";

/** Display names of collocation measures (engine.stats.MEASURE_LABELS). */
export const MEASURE_LABELS: Record<string, string> = { logdice: "logDice", mi: "MI", t: "t 值", ll: "LL" };

/** Rough rendered width of a label: CJK characters are about one em, others about 0.6 em. */
export function textWidth(s: string, fontSize: number): number {
  let w = 0;
  for (const ch of s) w += /[⺀-￿]/.test(ch) ? fontSize : fontSize * 0.62;
  return w;
}

export function hbarOption(t: ChartTokens, labels: string[], values: number[], valueText: (i: number) => string): EChartsOption {
  // Value labels sit right of the bars: leave room for the longest one (12px mono).
  const right = 16 + Math.max(0, ...values.map((_, i) => textWidth(valueText(i), 12)));
  return {
    ...baseOption(t),
    grid: { left: 8, right, top: 4, bottom: 4, containLabel: true },
    xAxis: { type: "value", show: false, max: (v: { max: number }) => v.max },
    yAxis: {
      type: "category",
      inverse: true,
      data: labels,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: t.text2, fontSize: 13, width: 84, overflow: "truncate" },
    },
    tooltip: { ...(baseOption(t).tooltip as object), trigger: "item", formatter: (p: { dataIndex: number }) => `${labels[p.dataIndex]} · ${valueText(p.dataIndex)}` },
    series: [
      {
        type: "bar",
        data: values,
        barWidth: 18,
        itemStyle: { color: t.accent, borderRadius: 4 },
        showBackground: true,
        backgroundStyle: { color: t.lineSoft, borderRadius: 4 },
        label: { show: true, position: "right", color: t.text2, fontFamily: t.mono, fontSize: 12, formatter: (p: { dataIndex: number }) => valueText(p.dataIndex) },
        emphasis: { itemStyle: { color: t.accent, opacity: 0.85 } },
        animationDelay: (i: number) => i * 60,
      },
    ],
  };
}

function vbarOption(t: ChartTokens, labels: string[], values: (number | null)[], unit: string): EChartsOption {
  return {
    ...baseOption(t),
    grid: { left: 8, right: 8, top: 24, bottom: 4, containLabel: true },
    xAxis: { type: "category", data: labels, axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false }, axisLabel: { color: t.text3, fontFamily: t.mono, fontSize: 11 } },
    yAxis: { type: "value", show: false },
    tooltip: { ...(baseOption(t).tooltip as object), trigger: "item", formatter: (p: { dataIndex: number }) => `${labels[p.dataIndex]} · ${fmtValue(values[p.dataIndex], 1)} ${unit}` },
    series: [
      {
        type: "bar",
        data: values,
        barMaxWidth: 34,
        itemStyle: { color: t.accent, borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: "top", color: t.text2, fontFamily: t.mono, fontSize: 11, formatter: (p: { value: number }) => fmtValue(p.value, 1) },
        animationDelay: (i: number) => i * 50,
      },
    ],
  };
}

function scatterOption(t: ChartTokens, stat: StatResult): EChartsOption {
  const pts = stat.rows
    .map((r) => ({ name: rowLabel(stat, r), lr: num(r.values.log_ratio), ll: num(r.values.ll) }))
    .filter((p) => p.lr != null && p.ll != null);
  return {
    ...baseOption(t),
    grid: { left: 8, right: 16, top: 20, bottom: 8, containLabel: true },
    xAxis: { type: "value", name: "Log Ratio", nameLocation: "end", nameTextStyle: { color: t.text3, fontSize: 11 }, axisLine: { lineStyle: { color: t.line } }, splitLine: { lineStyle: { color: t.lineSoft } }, axisLabel: { color: t.text3, fontFamily: t.mono, fontSize: 10 } },
    yAxis: { type: "log", name: "LL", nameTextStyle: { color: t.text3, fontSize: 11 }, axisLine: { show: false }, splitLine: { lineStyle: { color: t.lineSoft } }, axisLabel: { color: t.text3, fontFamily: t.mono, fontSize: 10 } },
    tooltip: { ...(baseOption(t).tooltip as object), trigger: "item", formatter: (p: { dataIndex: number }) => `${pts[p.dataIndex].name} · LL ${fmtValue(pts[p.dataIndex].ll)} · LR ${fmtValue(pts[p.dataIndex].lr)}` },
    series: [
      {
        type: "scatter",
        data: pts.map((p) => [p.lr, Math.max(p.ll!, 0.01)]),
        symbolSize: 9,
        itemStyle: { color: t.accent, opacity: 0.85 },
        label: { show: true, position: "right", color: t.text2, fontSize: 11, formatter: (p: { dataIndex: number }) => (p.dataIndex < 12 ? pts[p.dataIndex].name : "") },
        animationDelay: (i: number) => 200 + i * 45,
        animationEasing: "backOut",
      },
    ],
  };
}

function networkOption(t: ChartTokens, stat: StatResult, measure: string): EChartsOption {
  const rows = stat.rows.slice(0, 12);
  const node = String((stat.params as { node?: string }).node ?? "节点");
  const vals = rows.map((r) => num(r.values[measure]) ?? 0);
  const max = Math.max(...vals, 1);
  const min = Math.min(...vals, 0);
  const posOf = (r: (typeof rows)[number]) => {
    const tag = typeof r.values.pos === "string" ? r.values.pos : null;
    return posCat(tag);
  };
  // Circles grow to hold their word (up to a cap); longer words are cut with an ellipsis, never drawn outside.
  const fit = (label: string, fontSize: number, base: number, cap: number) => {
    const size = Math.min(cap, Math.max(base, textWidth(label, fontSize) + 14));
    return { size, label: { fontSize, width: size - 8, overflow: "truncate" as const, ellipsis: "…" } };
  };
  const center = fit(node, 14, 60, 92);
  // ids, not names, identify graph nodes: a collocate can share the node's word form (the → The).
  const nodes = [
    { id: "node", name: node, x: 0, y: 0, symbolSize: center.size, fixed: true, itemStyle: { color: t.accent }, label: { ...center.label, color: "#fff", fontWeight: 700 } },
    ...rows.map((r, i) => {
      const a = -Math.PI / 2 + (i * 2 * Math.PI) / rows.length + 0.35;
      const k = (vals[i] - min) / (max - min || 1);
      const rad = 120 + (1 - k) * 80;
      const c = posOf(r) - 1;
      const freq = num(r.values.freq) ?? 1;
      const name = rowLabel(stat, r);
      const f = fit(name, 12, 34 + Math.min(26, Math.sqrt(freq)), 76);
      return {
        id: `c${i}`,
        name,
        x: Math.cos(a) * rad * 1.25,
        y: Math.sin(a) * rad * 0.85,
        symbolSize: f.size,
        itemStyle: { color: t.paletteBg[c], borderColor: t.palette[c], borderWidth: 1.5 },
        label: { ...f.label, color: t.paletteFg[c], fontWeight: 600 },
        value: vals[i],
      };
    }),
  ];
  const mLabel = MEASURE_LABELS[measure] ?? measure;
  return {
    ...baseOption(t),
    tooltip: { ...(baseOption(t).tooltip as object), formatter: (p: { dataType: string; name: string; value?: number }) => (p.dataType === "node" && p.value != null ? `${p.name} · ${mLabel} ${fmtValue(p.value)}` : p.name) },
    series: [
      {
        type: "graph",
        layout: "none",
        roam: false,
        data: nodes,
        label: { show: true },
        links: rows.map((_, i) => ({ source: "node", target: `c${i}`, lineStyle: { width: 1 + ((vals[i] - min) / (max - min || 1)) * 5, color: t.accent, opacity: 0.4 } })),
        emphasis: { focus: "adjacency", lineStyle: { opacity: 1 } },
        animationDelay: (i: number) => 450 + i * 60,
        animationEasing: "backOut",
      },
    ],
  };
}

/** Chart beside the result table, per method. Solid series colours only. */
export const StatChart = forwardRef<
  EChartHandle,
  { stat: StatResult; measure?: string; view?: "network" | "bar"; onPick?: (i: number) => void }
>(function StatChart({ stat, measure, view, onPick }, ref) {
  const build = useCallback(
    (t: ChartTokens): EChartsOption => {
      if (stat.method === "keywords") return scatterOption(t, stat);
      if (stat.method === "distribution") {
        const d = distRows(stat);
        const usePm = d.some((r) => r.perMillion != null);
        return vbarOption(t, d.map((r) => r.label), d.map((r) => (usePm ? r.perMillion : r.tokens)), usePm ? "每百万词" : "词");
      }
      if (stat.method === "collocations") {
        const m = measure ?? "logdice";
        if (view !== "bar") return networkOption(t, stat, m);
        const rows = stat.rows.slice(0, 10);
        const vals = rows.map((r) => num(r.values[m]) ?? 0);
        return hbarOption(t, rows.map((r) => rowLabel(stat, r)), vals, (i) => `${fmtValue(vals[i])} · ${fmtValue(rows[i].values.freq)}`);
      }
      const rows = stat.rows.slice(0, 10);
      const key = stat.columns.some((c) => c.key === "per_million") ? "per_million" : "freq";
      const vals = rows.map((r) => num(r.values[key]) ?? 0);
      return hbarOption(t, rows.map((r) => rowLabel(stat, r)), vals, (i) => fmtValue(vals[i], 1));
    },
    [stat, measure, view],
  );
  const onClick = useCallback(
    (p: { dataIndex: number; seriesType?: string }) => {
      if (!onPick) return;
      if (stat.method === "collocations" && view !== "bar") {
        if (p.dataIndex > 0) onPick(p.dataIndex - 1);
      } else onPick(p.dataIndex);
    },
    [onPick, stat.method, view],
  );
  const height = stat.method === "collocations" && view !== "bar" ? 340 : stat.method === "keywords" ? 320 : stat.method === "distribution" ? 220 : Math.max(120, Math.min(stat.rows.length, 10) * 30);
  return <EChart ref={ref} build={build} height={height} onClick={onClick} label={`${stat.method} 图表`} />;
});

export function useChartView() {
  return useState<"network" | "bar">("network");
}
