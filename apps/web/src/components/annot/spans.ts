/**
 * Span geometry and code-point helpers (contracts/p5.md: span offsets are Unicode code points).
 * DOM text offsets are UTF-16 units; everything sent to the API is code points.
 */

/** Number of code points in s. */
export function cpLength(s: string): number {
  let n = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff && i + 1 < s.length) {
      const d = s.charCodeAt(i + 1);
      if (d >= 0xdc00 && d <= 0xdfff) i++;
    }
    n++;
  }
  return n;
}

/** UTF-16 offset → code-point offset. An offset inside a surrogate pair counts the whole pair. */
export function utf16ToCp(s: string, offset: number): number {
  return cpLength(s.slice(0, Math.max(0, Math.min(offset, s.length))));
}

/** Code-point offset → UTF-16 offset. */
export function cpToUtf16(s: string, cp: number): number {
  let i = 0;
  let n = 0;
  while (i < s.length && n < cp) {
    const c = s.charCodeAt(i);
    i += c >= 0xd800 && c <= 0xdbff && i + 1 < s.length ? 2 : 1;
    n++;
  }
  return i;
}

/** Substring by code points. */
export function cpSlice(s: string, a: number, b?: number): string {
  return s.slice(cpToUtf16(s, a), b == null ? undefined : cpToUtf16(s, b));
}

/** Grapheme boundaries in code points (0 and cpLength included). */
export function graphemeBounds(s: string): number[] {
  const out = [0];
  const Seg = (Intl as unknown as { Segmenter?: new (l?: string, o?: { granularity: string }) => { segment(t: string): Iterable<{ segment: string }> } }).Segmenter;
  if (Seg) {
    let cp = 0;
    for (const g of new Seg(undefined, { granularity: "grapheme" }).segment(s)) {
      cp += cpLength(g.segment);
      out.push(cp);
    }
    return out;
  }
  // Fallback: a combining mark (U+0300–036F, U+20D0–20FF, U+FE20–FE2F, variation selectors) joins the previous character.
  let cp = 0;
  for (const ch of s) {
    cp++;
    if (/[̀-ͯ⃐-⃿︠-︯︀-️‍]/.test(ch) && out.length > 1) out[out.length - 1] = cp;
    else out.push(cp);
  }
  return out;
}

/**
 * Normalise a selection in `text` (code points, either order): widen to grapheme boundaries so a base letter
 * keeps its combining marks, then drop surrounding whitespace. Null when nothing but whitespace is left.
 */
export function normalizeSelection(text: string, a: number, b: number): { start: number; end: number } | null {
  let start = Math.min(a, b);
  let end = Math.max(a, b);
  const bounds = graphemeBounds(text);
  start = [...bounds].reverse().find((x) => x <= start) ?? 0;
  end = bounds.find((x) => x >= end) ?? bounds[bounds.length - 1];
  const chars = [...text];
  while (start < end && /\s/.test(chars[start] ?? "")) start++;
  while (end > start && /\s/.test(chars[end - 1] ?? "")) end--;
  return end > start ? { start, end } : null;
}

/* ---------- span layout ---------- */

export interface SpanLike {
  id: string;
  start: number; // relative code points
  end: number;
}

/** Underline level per span: nested and overlapping spans stack (outer / later spans lower). */
export function spanLevels<T extends SpanLike>(spans: T[]): Map<string, number> {
  const sorted = [...spans].sort((p, q) => p.start - q.start || q.end - q.start - (p.end - p.start));
  const placed: { s: T; lvl: number }[] = [];
  const out = new Map<string, number>();
  // Inner spans first get the lowest level, so sort by length when assigning.
  for (const s of [...sorted].sort((p, q) => p.end - p.start - (q.end - q.start) || p.start - q.start)) {
    let lvl = 0;
    while (placed.some((p) => p.lvl === lvl && p.s.start < s.end && s.start < p.s.end)) lvl++;
    placed.push({ s, lvl });
    out.set(s.id, lvl);
  }
  return out;
}

export interface Segment {
  start: number;
  end: number;
  /** Covering span ids, outermost (highest level) first. */
  ids: string[];
}

/** Split [0, length) at every span boundary; each piece lists the spans covering it. */
export function segmentText<T extends SpanLike>(length: number, spans: T[], levels: Map<string, number>): Segment[] {
  const cuts = new Set([0, length]);
  for (const s of spans) {
    cuts.add(Math.max(0, Math.min(length, s.start)));
    cuts.add(Math.max(0, Math.min(length, s.end)));
  }
  const xs = [...cuts].sort((a, b) => a - b);
  const out: Segment[] = [];
  for (let i = 0; i < xs.length - 1; i++) {
    const a = xs[i];
    const b = xs[i + 1];
    if (b <= a) continue;
    const ids = spans
      .filter((s) => s.start <= a && s.end >= b)
      .sort((p, q) => (levels.get(q.id) ?? 0) - (levels.get(p.id) ?? 0))
      .map((s) => s.id);
    out.push({ start: a, end: b, ids });
  }
  return out;
}

/** Colour index 1–8 for a label: its position in the label set, else a stable hash. */
export function labelColor(label: string, order: string[]): number {
  const i = order.indexOf(label);
  if (i >= 0) return (i % 8) + 1;
  let h = 0;
  for (const ch of label) h = (h * 31 + (ch.codePointAt(0) ?? 0)) >>> 0;
  return (h % 8) + 1;
}

/* ---------- DOM selection → code points ---------- */

/** Text holders carry `data-cp` (relative code-point start of their only text node). */
const HOLDER = "[data-cp]";

function holderOf(node: Node): HTMLElement | null {
  const el = node.nodeType === Node.TEXT_NODE ? node.parentElement : (node as Element);
  const h = el?.closest?.(HOLDER) as HTMLElement | null;
  return h && h.firstChild?.nodeType === Node.TEXT_NODE ? h : null;
}

/**
 * One selection boundary → code point within `root`'s flow. Boundaries inside a holder's text count code points;
 * boundaries elsewhere (label tags, gaps between sentences) snap to the next holder's start, or the flow end.
 */
export function boundaryToCp(root: Element, node: Node, offset: number): number | null {
  if (!root.contains(node)) return null;
  const h = holderOf(node);
  if (h && node.nodeType === Node.TEXT_NODE && h.firstChild === node) return Number(h.dataset.cp) + utf16ToCp((node as Text).data, offset);
  const holders = [...root.querySelectorAll<HTMLElement>(HOLDER)];
  if (!holders.length) return null;
  const doc = root.ownerDocument;
  const point = doc.createRange();
  point.setStart(node, offset);
  for (const x of holders) {
    const r = doc.createRange();
    r.setStart(x, 0);
    if (point.compareBoundaryPoints(Range.START_TO_START, r) <= 0) return Number(x.dataset.cp);
  }
  const last = holders[holders.length - 1];
  return Number(last.dataset.cp) + cpLength(last.textContent ?? "");
}

/** A DOM range inside the flow → [start, end) in flow code points; null when collapsed or outside. */
export function rangeToCp(root: Element, range: Range): { start: number; end: number } | null {
  if (range.collapsed) return null;
  const a = boundaryToCp(root, range.startContainer, range.startOffset);
  const b = boundaryToCp(root, range.endContainer, range.endOffset);
  if (a == null || b == null || a === b) return null;
  return { start: Math.min(a, b), end: Math.max(a, b) };
}
