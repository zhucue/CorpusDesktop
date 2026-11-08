import { setPlatformAPI } from "echarts/core";
import { describe, expect, it } from "vitest";
import { chartSvg } from "../src/components/results/EChart";

// jsdom has no canvas to measure text with: about 0.62 em per character at 11px.
setPlatformAPI({ measureText: (text: string) => ({ width: text.length * 7 }) as TextMetrics });
import { vbarOption, vbarShowValues } from "../src/features/stats/StatChart";

const bins = (n: number) => Array.from({ length: n }, (_, i) => `${(100 * i) / n}–${(100 * (i + 1)) / n}%`);
const values = (n: number) => Array.from({ length: n }, (_, i) => 60 + ((i * 37) % 70) + 0.7);
const series = (o: object) => (o as { series: { label: { show: boolean } }[] }).series[0];

describe("distribution chart value labels", () => {
  it("shows them for 10 bins and drops them for 50", () => {
    expect(vbarShowValues(values(10))).toBe(true);
    expect(vbarShowValues(values(50))).toBe(false);
    const t = { mono: "monospace" } as Parameters<typeof vbarOption>[0];
    expect(series(vbarOption(t, bins(10), values(10), "每百万词")).label.show).toBe(true);
    expect(series(vbarOption(t, bins(50), values(50), "每百万词")).label.show).toBe(false);
  });

  it("wide values need more room per bar", () => {
    expect(vbarShowValues(Array(10).fill(123456.7))).toBe(false);
  });

  it("renders no value labels and thinned axis labels at 50 bins", () => {
    const v = values(50);
    const svg = chartSvg((t) => vbarOption(t, bins(50), v, "每百万词"), 598, 220);
    const texts = Array.from(new DOMParser().parseFromString(svg, "image/svg+xml").getElementsByTagName("text")).map((e) => e.textContent);
    expect(texts.some((s) => s === "60.7" || s === "97.7")).toBe(false);
    const axis = texts.filter((s) => s?.endsWith("%"));
    expect(axis.length).toBeGreaterThan(0);
    expect(axis.length).toBeLessThan(50);
  });

  it("keeps every value label at 10 bins", () => {
    const v = values(10);
    const svg = chartSvg((t) => vbarOption(t, bins(10), v, "每百万词"), 598, 220);
    const texts = Array.from(new DOMParser().parseFromString(svg, "image/svg+xml").getElementsByTagName("text")).map((e) => e.textContent);
    for (const x of v) expect(texts).toContain(x.toFixed(1));
  });
});
