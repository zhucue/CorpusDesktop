/**
 * Dependency arc layout (port of buildDep in doc/ui-design/app.js).
 * Token indices are 1-based as in contracts/p3.md; head 0 marks the root.
 */

export interface GraphToken {
  index: number;
  form: string;
  pos?: string | null;
}

export interface GraphArc {
  dep: number;
  head: number;
  label: string;
  suggested?: boolean;
}

export interface LaidToken extends GraphToken {
  x: number; // centre
  w: number;
}

export interface LaidArc extends GraphArc {
  lvl: number;
  xd: number; // dependent end (arrow)
  xh: number; // head end (drag handle)
  mx: number; // label centre
  my: number; // label baseline area (apex)
  lw: number; // label box width
  path: string;
}

export interface LaidRoot {
  dep: number;
  label: string;
  suggested?: boolean;
  x: number;
  path: string;
}

export interface DepLayout {
  width: number;
  height: number;
  y0: number; // token baseline: arcs end just above it
  top: number;
  tokens: LaidToken[];
  arcs: LaidArc[];
  roots: LaidRoot[];
}

export const GAP = 14;
const PAD = 8;
const UNIT = 24;
const CJK = /[⺀-鿿豈-﫿＀-￯　-〿]/;

/** Approximate rendered width at 15 px (CJK full width, Latin ~0.58 em). */
export function textWidth(s: string, px = 15): number {
  let w = 0;
  for (const ch of s) w += CJK.test(ch) ? px : px * 0.58;
  return w;
}

export function layoutDeps(tokens: GraphToken[], arcs: GraphArc[], opts: { posRow?: boolean } = {}): DepLayout {
  const laid: LaidToken[] = [];
  let x = PAD;
  for (const t of tokens) {
    const w = Math.max(44, textWidth(t.form) + 20, t.pos ? t.pos.length * 7.2 + 14 : 0);
    laid.push({ ...t, x: x + w / 2, w });
    x += w + GAP;
  }
  const width = Math.max(x - GAP + PAD, 60);
  const pos = new Map(laid.map((t) => [t.index, t]));

  const real = arcs.filter((a) => a.head !== 0 && a.head !== a.dep && pos.has(a.dep) && pos.has(a.head));
  const rootArcs = arcs.filter((a) => a.head === 0 && pos.has(a.dep));

  type Work = GraphArc & { lo: number; hi: number; xd: number; xh: number; mx: number; lw: number; lvl: number };
  const work: Work[] = real.map((a) => {
    const left = a.dep < a.head;
    const xd = pos.get(a.dep)!.x + (left ? 5 : -5);
    const xh = pos.get(a.head)!.x + (left ? -5 : 5);
    return { ...a, lo: Math.min(a.dep, a.head), hi: Math.max(a.dep, a.head), xd, xh, mx: (xd + xh) / 2, lw: a.label.length * 6.8 + 8, lvl: 1 };
  });

  stackArcs(work);
  const maxLvl = Math.max(1, ...work.map((a) => a.lvl));
  const top = 8;
  const y0 = (rootArcs.length ? 52 : 30) + maxLvl * UNIT;
  const height = y0 + (opts.posRow === false ? 30 : 46);

  const laidArcs: LaidArc[] = work.map((a) => {
    const h = 14 + a.lvl * UNIT;
    const cy = y0 - h * 1.33;
    const path = `M${r(a.xd)} ${y0 - 2} C${r(a.xd)} ${r(cy)} ${r(a.xh)} ${r(cy)} ${r(a.xh)} ${y0 - 2}`;
    return { dep: a.dep, head: a.head, label: a.label, suggested: a.suggested, lvl: a.lvl, xd: a.xd, xh: a.xh, mx: a.mx, my: y0 - h - 2, lw: a.lw, path };
  });
  const roots: LaidRoot[] = rootArcs.map((a) => {
    const rx = pos.get(a.dep)!.x;
    return { dep: a.dep, label: a.label || "root", suggested: a.suggested, x: rx, path: `M${r(rx)} ${top} L${r(rx)} ${y0 - 2}` };
  });
  return { width, height, y0, top, tokens: laid, arcs: laidArcs, roots };
}

export interface StackItem {
  lo: number;
  hi: number;
  mx: number; // label centre
  lw: number; // label width
  lvl: number;
}

/**
 * Arc levels (1 = lowest), set in place: outer arcs sit above the arcs they contain; labels on the same level
 * that would overlap move up one level. Shared by dependency arcs and span relation arcs.
 */
export function stackArcs<T extends StackItem>(items: T[]): T[] {
  const placed: T[] = [];
  for (const a of [...items].sort((p, q) => p.hi - p.lo - (q.hi - q.lo) || p.lo - q.lo)) {
    let lvl = 1;
    for (const p of placed) if (p.lo >= a.lo && p.hi <= a.hi) lvl = Math.max(lvl, p.lvl + 1);
    const clash = (l: number) => placed.some((p) => p.lvl === l && Math.abs(p.mx - a.mx) < (p.lw + a.lw) / 2 + 4);
    while (clash(lvl)) lvl++;
    a.lvl = lvl;
    placed.push(a);
  }
  return items;
}

const r = (n: number) => Math.round(n * 10) / 10;

/** Token whose slot (box plus half the gap on each side) contains x; null outside the token row. */
export function tokenAt(layout: DepLayout, x: number): number | null {
  for (const t of layout.tokens) if (x >= t.x - t.w / 2 - GAP / 2 && x <= t.x + t.w / 2 + GAP / 2) return t.index;
  return null;
}

/**
 * New head for `dep` when its arc's head end is dropped at x.
 * Returns null when nothing changes: dropped outside the tokens, on the dependent itself, or on the current head.
 */
export function headFromDrop(layout: DepLayout, dep: number, currentHead: number, x: number): number | null {
  const t = tokenAt(layout, x);
  if (t == null || t === dep || t === currentHead) return null;
  return t;
}
