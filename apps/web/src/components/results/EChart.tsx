import { BarChart, GraphChart, ScatterChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { reducedMotion } from "../../theme/motion";
import { useTheme } from "../../theme/theme";

echarts.use([BarChart, ScatterChart, GraphChart, GridComponent, TooltipComponent, SVGRenderer]);

export type EChartsOption = echarts.EChartsCoreOption;

type Read = (name: string) => string;

function rootVars(): Read {
  const css = getComputedStyle(document.documentElement);
  return (n) => css.getPropertyValue(n).trim();
}

/** Light-theme token values: the plain `:root` rule of tokens.css (dark mode overrides it on [data-theme="dark"]). */
export function lightVars(): Read {
  for (const sheet of Array.from(document.styleSheets)) {
    let rules: CSSRuleList;
    try {
      rules = sheet.cssRules;
    } catch {
      continue; // cross-origin sheet
    }
    for (const r of Array.from(rules)) {
      const style = (r as CSSStyleRule).style;
      if ((r as CSSStyleRule).selectorText === ":root" && style?.getPropertyValue("--surface")) return (n) => style.getPropertyValue(n).trim();
    }
  }
  return () => "";
}

/** Font lists go into SVG `style="…"` attributes: double quotes inside would end the attribute. */
const attrSafe = (s: string) => s.replace(/"/g, "'");

/** Resolved design tokens for chart options (charts cannot read CSS variables). */
export function chartTokens(read: Read = rootVars()) {
  const v = (n: string, fallback: string) => read(n) || fallback;
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
    font: attrSafe(v("--font", "Inter, sans-serif")),
    mono: attrSafe(v("--mono", "monospace")),
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

/**
 * Standalone SVG document of a chart for papers: always the light theme on a white background, whatever the page
 * theme, no animation. Rendered server-side style (ssr) so the string is the whole, well-formed document.
 */
export function chartSvg(build: (t: ChartTokens) => EChartsOption, width: number, height: number): string {
  const t = { ...chartTokens(lightVars()), surface: "#FFFFFF" };
  const c = echarts.init(null, undefined, { renderer: "svg", ssr: true, width, height });
  try {
    c.setOption({ ...build(t), animation: false, backgroundColor: "#FFFFFF" });
    const svg = c.renderToSVGString();
    return `<?xml version="1.0" encoding="UTF-8"?>\n${svg.includes("xmlns=") ? svg : svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"')}`;
  } finally {
    c.dispose();
  }
}

/** PNG (2x) of chartSvg on white. */
export async function chartPng(svg: string, width: number, height: number): Promise<string> {
  const img = new Image();
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  await img.decode();
  const canvas = document.createElement("canvas");
  canvas.width = width * 2;
  canvas.height = height * 2;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#FFFFFF";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/png");
}

export interface EChartHandle {
  svg: () => string | null;
  png: () => Promise<string | null>;
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
      if (!c.isDisposed()) c.off("click", h);
    };
  }, [onClick]);

  useImperativeHandle(ref, () => {
    const size = () => {
      const c = chart.current;
      return c ? { w: c.getWidth(), h: c.getHeight() } : null;
    };
    return {
      svg: () => {
        const s = size();
        return s ? chartSvg(build, s.w, s.h) : null;
      },
      png: async () => {
        const s = size();
        return s ? chartPng(chartSvg(build, s.w, s.h), s.w, s.h) : null;
      },
    };
  }, [build]);

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

/** Save text (e.g. an SVG document) as a file. */
export function downloadText(text: string, type: string, filename: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  download(url, filename);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
