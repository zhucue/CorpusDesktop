import { describe, expect, it } from "vitest";
import { headFromDrop, layoutDeps, tokenAt } from "../src/components/annot/geometry";

// 她 为 博物馆 翻译 了 展板 。 (1-based; head 0 = root), as in doc/ui-design/annotate.html.
const tokens = ["她", "为", "博物馆", "翻译", "了", "展板", "。"].map((form, i) => ({ index: i + 1, form, pos: "X" }));
const arcs = [
  { dep: 1, head: 4, label: "nsubj" },
  { dep: 2, head: 3, label: "case" },
  { dep: 3, head: 4, label: "obl" },
  { dep: 4, head: 0, label: "root" },
  { dep: 5, head: 4, label: "aux" },
  { dep: 6, head: 4, label: "obj" },
  { dep: 7, head: 4, label: "punct" },
];

describe("dependency arc layout", () => {
  const L = layoutDeps(tokens, arcs);

  it("places tokens left to right without overlap", () => {
    for (let i = 1; i < L.tokens.length; i++) {
      const a = L.tokens[i - 1];
      const b = L.tokens[i];
      expect(b.x - b.w / 2).toBeGreaterThan(a.x + a.w / 2);
    }
    expect(L.width).toBeGreaterThan(L.tokens[L.tokens.length - 1].x);
  });

  it("raises arcs that contain other arcs and keeps the root as a vertical tick", () => {
    const lvl = (dep: number) => L.arcs.find((a) => a.dep === dep)!.lvl;
    expect(lvl(2)).toBe(1); // 为 → 博物馆, innermost
    expect(lvl(1)).toBeGreaterThan(lvl(3)); // 她 → 翻译 spans 为 → 博物馆 → 翻译
    expect(lvl(1)).toBeGreaterThan(lvl(2));
    expect(L.arcs).toHaveLength(6);
    expect(L.roots).toEqual([expect.objectContaining({ dep: 4, label: "root" })]);
    const x4 = L.tokens.find((t) => t.index === 4)!.x;
    expect(L.roots[0].path).toBe(`M${Math.round(x4 * 10) / 10} ${L.top} L${Math.round(x4 * 10) / 10} ${L.y0 - 2}`);
  });

  it("starts each arc at the dependent and ends at the head", () => {
    const a = L.arcs.find((x) => x.dep === 6)!;
    const x6 = L.tokens[5].x;
    const x4 = L.tokens[3].x;
    expect(Math.abs(a.xd - x6)).toBeLessThanOrEqual(5);
    expect(Math.abs(a.xh - x4)).toBeLessThanOrEqual(5);
    expect(a.my).toBeLessThan(L.y0);
  });

  it("maps a drop position to a token", () => {
    expect(tokenAt(L, L.tokens[2].x)).toBe(3);
    expect(tokenAt(L, L.tokens[2].x + L.tokens[2].w / 2 + 3)).toBe(3); // inside half the gap
    expect(tokenAt(L, -50)).toBeNull();
    expect(tokenAt(L, L.width + 50)).toBeNull();
  });

  it("turns dragging a head end into a head change only when it changes something", () => {
    // Drag the head end of 展板 (obj → 翻译) onto 博物馆: new head 3.
    expect(headFromDrop(L, 6, 4, L.tokens[2].x)).toBe(3);
    expect(headFromDrop(L, 6, 4, L.tokens[3].x)).toBeNull(); // same head
    expect(headFromDrop(L, 6, 4, L.tokens[5].x)).toBeNull(); // onto itself
    expect(headFromDrop(L, 6, 4, L.width + 40)).toBeNull(); // outside the row
    // The root tick: 翻译 (head 0) dragged onto 她.
    expect(headFromDrop(L, 4, 0, L.tokens[0].x)).toBe(1);
  });

  it("skips arcs pointing outside the sentence", () => {
    const l2 = layoutDeps(tokens.slice(0, 2), [{ dep: 1, head: 9, label: "x" }, { dep: 2, head: 2, label: "y" }]);
    expect(l2.arcs).toHaveLength(0);
    expect(l2.roots).toHaveLength(0);
  });
});
