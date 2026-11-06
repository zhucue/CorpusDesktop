import { BoxplotChart, LineChart } from "echarts/charts";
import { LegendComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { baseOption, type ChartTokens, type EChartsOption } from "../../components/results/EChart";
import { fmtValue } from "../../lib/format";

// EChart registers bar / scatter / graph; the P10 views add box plots, lines and legends.
echarts.use([BoxplotChart, LineChart, LegendComponent]);

export interface Series {
  name: string;
  values: (number | null)[];
}

/** Five-number summary for a box: min, Q1, median, Q3, max (linear interpolation, as numpy's default). */
export function fiveNumber(values: number[]): [number, number, number, number, number] | null {
  const v = values.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  const q = (p: number) => {
    const i = (v.length - 1) * p;
    const lo = Math.floor(i);
    const hi = Math.ceil(i);
    return v[lo] + (v[hi] - v[lo]) * (i - lo);
  };
  return [v[0], q(0.25), q(0.5), q(0.75), v[v.length - 1]];
}

const axisLabel = (t: ChartTokens) => ({ color: t.text3, fontFamily: t.mono, fontSize: 11 });
const tooltip = (t: ChartTokens, extra: object) => ({ ...(baseOption(t).tooltip as object), ...extra });
const legend = (t: ChartTokens, show: boolean) =>
  show ? { legend: { top: 0, left: 0, icon: "roundRect", itemWidth: 10, itemHeight: 10, textStyle: { color: t.text2, fontSize: 12 } } } : {};

/** One box per group of per-document values. */
export function boxplotOption(t: ChartTokens, groups: { name: string; values: number[] }[], metric: string): EChartsOption {
  const boxes = groups.map((g) => fiveNumber(g.values));
  return {
    ...baseOption(t),
    grid: { left: 8, right: 16, top: 16, bottom: 4, containLabel: true },
    xAxis: { type: "category", data: groups.map((g) => g.name), axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false }, axisLabel: { ...axisLabel(t), width: 90, overflow: "truncate" } },
    yAxis: { type: "value", scale: true, axisLine: { show: false }, splitLine: { lineStyle: { color: t.lineSoft } }, axisLabel: axisLabel(t) },
    tooltip: tooltip(t, {
      trigger: "item",
      formatter: (p: { dataIndex: number }) => {
        const b = boxes[p.dataIndex];
        const g = groups[p.dataIndex];
        if (!b) return `${g.name} · 无数据`;
        const f = (x: number) => fmtValue(x);
        return `${g.name} · ${metric}<br/>${g.values.length} 篇<br/>最小 ${f(b[0])} · Q1 ${f(b[1])}<br/>中位 ${f(b[2])}<br/>Q3 ${f(b[3])} · 最大 ${f(b[4])}`;
      },
    }),
    series: [
      {
        type: "boxplot",
        data: boxes.map((b) => b ?? []),
        boxWidth: [12, 40],
        itemStyle: { color: t.accentTint, borderColor: t.accent, borderWidth: 1.5 },
      },
    ],
  };
}

/** Stacked bars (one series per level), horizontal: one bar per category. Values are percentages. */
export function stackedOption(t: ChartTokens, categories: string[], series: Series[], colors: string[]): EChartsOption {
  return {
    ...baseOption(t),
    ...legend(t, series.length > 1),
    grid: { left: 8, right: 16, top: series.length > 1 ? 36 : 8, bottom: 4, containLabel: true },
    xAxis: { type: "value", max: (v: { max: number }) => Math.max(100, Math.ceil(v.max)), axisLine: { show: false }, splitLine: { lineStyle: { color: t.lineSoft } }, axisLabel: { ...axisLabel(t), formatter: "{value}%" } },
    yAxis: { type: "category", inverse: true, data: categories, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: t.text2, fontSize: 12, width: 110, overflow: "truncate" } },
    tooltip: tooltip(t, {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (ps: { seriesName: string; value: number | null; marker: string; name: string }[]) =>
        [ps[0]?.name ?? "", ...ps.filter((p) => p.value != null).map((p) => `${p.marker}${p.seriesName} ${fmtValue(p.value, 1)}%`)].join("<br/>"),
    }),
    series: series.map((s, i) => ({
      type: "bar",
      name: s.name,
      stack: "total",
      data: s.values,
      barMaxWidth: 22,
      itemStyle: { color: colors[i % colors.length], borderColor: t.surface, borderWidth: 1 },
      emphasis: { focus: "series" },
      animationDelay: (j: number) => j * 40,
    })),
  };
}

/** Several series over shared categories: lines (ordered numeric field) or grouped bars. */
export function multiOption(t: ChartTokens, categories: string[], series: Series[], kind: "line" | "bar", unit: string): EChartsOption {
  return {
    ...baseOption(t),
    ...legend(t, series.length > 1),
    grid: { left: 8, right: 16, top: series.length > 1 ? 36 : 16, bottom: 4, containLabel: true },
    xAxis: { type: "category", data: categories, boundaryGap: kind === "bar", axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false }, axisLabel: { ...axisLabel(t), width: 90, overflow: "truncate" } },
    yAxis: { type: "value", name: unit, nameTextStyle: { color: t.text3, fontSize: 11 }, axisLine: { show: false }, splitLine: { lineStyle: { color: t.lineSoft } }, axisLabel: axisLabel(t) },
    tooltip: tooltip(t, {
      trigger: "axis",
      axisPointer: kind === "line" ? { type: "line", lineStyle: { color: t.line } } : { type: "shadow" },
      formatter: (ps: { seriesName: string; value: number | null; marker: string; name: string }[]) =>
        [ps[0]?.name ?? "", ...ps.map((p) => `${p.marker}${p.seriesName} ${p.value == null ? "—" : fmtValue(p.value, 1)}`)].join("<br/>"),
    }),
    series: series.map((s, i) =>
      kind === "line"
        ? { type: "line", name: s.name, data: s.values, connectNulls: false, symbol: "circle", symbolSize: 8, lineStyle: { width: 2, color: t.palette[i % 8] }, itemStyle: { color: t.palette[i % 8], borderColor: t.surface, borderWidth: 2 } }
        : { type: "bar", name: s.name, data: s.values, barMaxWidth: 26, barGap: "10%", itemStyle: { color: t.palette[i % 8], borderRadius: [4, 4, 0, 0] }, animationDelay: (j: number) => j * 40 },
    ),
  };
}
