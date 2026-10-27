import { BarChart, GraphChart, ScatterChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { reducedMotion } from "../../theme/motion";
import { useTheme } from "../../theme/theme";

echarts.use([BarChart, ScatterChart, GraphChart, GridComponent, TooltipComponent, SVGRenderer]);

export type EChartsOption = echarts.EChartsCoreOption;

/** Resolved design tokens for chart options (charts cannot read CSS variables). */
export function chartTokens() {
  const css = getComputedStyle(document.documentElement);
  const v = (n: string, fallback: string) => css.getPropertyValue(n).trim() || fallback;
  return {
    accent: v("--accent", "#1570EF"),
    accentTint: v("--accent-tint", "#EFF8FF"),
    error: v("--error-solid", "#F04438"),
    text: v("--text", "#1A1D24"),
    text2: v("--text-2", "#475467"),
    text3: v("--text-3", "#6B7280"),
    line: v("--line", "#E6E8EE"),
    lineSoft: v("--line-soft", "#F0F1F4"),
    surface: v("--surface", "#FFFFFF"),
    tooltip: v("--toast-bg", "#1A1D24"),
    tooltipText: v("--toast-text", "#FFFFFF"),
    font: v("--font", "Inter, sans-serif"),
    mono: v("--mono", "monospace"),
    palette: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--c${i}`, "#5B8DEF")),
    paletteBg: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--c${i}-bg`, "#EAF1FD")),
    paletteFg: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--c${i}-fg`, "#1E4F9A")),
  };
}
export type ChartTokens = ReturnType<typeof chartTokens>;

export function baseOption(t: ChartTokens): EChartsOption {
  const reduced = reducedMotion();
  return {
    animation: !reduced,
    animationDuration: 700,
    animationEasing: "cubicOut",
    animationDelay: (i: number) => i * 60,
    textStyle: { fontFamily: t.font, color: t.text2 },
    tooltip: {
      backgroundColor: t.tooltip,
      borderWidth: 0,
      textStyle: { color: t.tooltipText, fontSize: 12, fontFamily: t.font },
      extraCssText: "border-radius:6px;box-shadow:none;",
    },
  };
}

export interface EChartHandle {
  svgDataUrl: () => string | null;
  pngDataUrl: () => Promise<string | null>;
}

/** Minimal ECharts host: SVG renderer, resizes with its box, rebuilds on theme change. */
export const EChart = forwardRef<
  EChartHandle,
  { build: (t: ChartTokens) => EChartsOption; height: number; onClick?: (p: { dataIndex: number; seriesType?: string }) => void; label?: string }
>(function EChart({ build, height, onClick, label }, ref) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const { mode } = useTheme();

  useEffect(() => {
    if (!el.current) return;
    const c = echarts.init(el.current, undefined, { renderer: "svg" });
    chart.current = c;
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => c.resize()) : null;
    ro?.observe(el.current);
    return () => {
      ro?.disconnect();
      c.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(build(chartTokens()), true);
  }, [build, mode]);

  useEffect(() => {
    const c = chart.current;
    if (!c || !onClick) return;
    const h = (p: unknown) => onClick(p as { dataIndex: number; seriesType?: string });
    c.on("click", h);
    return () => {
      c.off("click", h);
    };
  }, [onClick]);

  useImperativeHandle(ref, () => ({
    svgDataUrl: () => chart.current?.getDataURL({ type: "svg" }) ?? null,
    pngDataUrl: async () => {
      const c = chart.current;
      if (!c) return null;
      const svg = c.getDataURL({ type: "svg" });
      const w = c.getWidth();
      const h = c.getHeight();
      const img = new Image();
      img.src = svg;
      await img.decode();
      const canvas = document.createElement("canvas");
      canvas.width = w * 2;
      canvas.height = h * 2;
      const ctx = canvas.getContext("2d")!;
      ctx.fillStyle = chartTokens().surface;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL("image/png");
    },
  }));

  return <div ref={el} style={{ width: "100%", height }} role="img" aria-label={label} />;
});

export function download(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}
