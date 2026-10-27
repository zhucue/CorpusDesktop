import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { AnnotStatus } from "../../api";
import "./annot.css";

/** One alignment group: every src token links to every tgt token (indices 1-based). */
export interface AlignLink {
  key: string;
  src: number[];
  tgt: number[];
  status?: AnnotStatus;
}

interface Line {
  id: string;
  a: number;
  b: number;
  d: string;
  status: AnnotStatus;
}

export type PickSide = { side: "src" | "tgt"; index: number } | null;

/** Token pairs of the groups that are not rejected. */
export function linkPairs(links: AlignLink[]): { a: number; b: number; status: AnnotStatus; key: string }[] {
  const out: { a: number; b: number; status: AnnotStatus; key: string }[] = [];
  for (const l of links) {
    if (l.status === "rejected") continue;
    for (const a of l.src) for (const b of l.tgt) out.push({ a, b, status: l.status ?? "confirmed", key: l.key });
  }
  return out;
}

/**
 * Two token columns (source right-aligned, target left-aligned) joined by curves; suggested links dashed.
 * Hovering a token highlights its links and the tokens on the other side (doc/ui-design 双语对照).
 * With onToggle, clicking a token on one side then a token on the other side adds or removes that pair.
 */
export function AlignGraph({
  src,
  tgt,
  links,
  onToggle,
  srcLabel,
  tgtLabel,
}: {
  src: string[];
  tgt: string[];
  links: AlignLink[];
  onToggle?: (srcIndex: number, tgtIndex: number) => void;
  srcLabel?: string;
  tgtLabel?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [hover, setHover] = useState<PickSide>(null);
  const [pick, setPick] = useState<PickSide>(null);
  const pairs = linkPairs(links);

  const measure = useCallback(() => {
    const root = box.current;
    if (!root) return;
    const r0 = root.getBoundingClientRect();
    const next: Line[] = [];
    for (const p of pairs) {
      const a = root.querySelector(`[data-a="${p.a}"]`);
      const b = root.querySelector(`[data-b="${p.b}"]`);
      if (!a || !b) continue;
      const ra = a.getBoundingClientRect();
      const rb = b.getBoundingClientRect();
      const x1 = ra.right - r0.left + 4;
      const y1 = ra.top + ra.height / 2 - r0.top;
      const x2 = rb.left - r0.left - 4;
      const y2 = rb.top + rb.height / 2 - r0.top;
      const mx = (x1 + x2) / 2;
      next.push({ id: `${p.a}-${p.b}`, a: p.a, b: p.b, d: `M${r(x1)} ${r(y1)} C${r(mx)} ${r(y1)} ${r(mx)} ${r(y2)} ${r(x2)} ${r(y2)}`, status: p.status });
    }
    setLines((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(pairs)]);

  useLayoutEffect(() => {
    measure();
  });
  useLayoutEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(el);
    return () => ro.disconnect();
  }, [measure]);

  const lit = new Set<string>();
  const litA = new Set<number>();
  const litB = new Set<number>();
  if (hover) {
    for (const l of lines)
      if ((hover.side === "src" && l.a === hover.index) || (hover.side === "tgt" && l.b === hover.index)) {
        lit.add(l.id);
        litA.add(l.a);
        litB.add(l.b);
      }
    (hover.side === "src" ? litA : litB).add(hover.index);
  }

  function click(side: "src" | "tgt", index: number) {
    if (!onToggle) return;
    if (pick && pick.side !== side) {
      const a = side === "src" ? index : pick.index;
      const b = side === "tgt" ? index : pick.index;
      setPick(null);
      onToggle(a, b);
    } else setPick(pick?.side === side && pick.index === index ? null : { side, index });
  }

  const col = (side: "src" | "tgt", toks: string[]) => (
    <div className={`al-row ${side === "tgt" ? "en" : ""}`} aria-label={side === "src" ? (srcLabel ?? "原文") : (tgtLabel ?? "译文")} role="group">
      {toks.map((t, i) => {
        const n = i + 1;
        const on = (side === "src" ? litA : litB).has(n);
        const picked = pick?.side === side && pick.index === n;
        const attr = side === "src" ? { "data-a": n } : { "data-b": n };
        const cls = `${on ? "hl" : ""} ${picked ? "pick" : ""}`;
        return onToggle ? (
          <button
            key={n}
            type="button"
            className={cls}
            {...attr}
            aria-pressed={picked}
            onMouseEnter={() => setHover({ side, index: n })}
            onMouseLeave={() => setHover(null)}
            onClick={() => click(side, n)}
          >
            {t}
          </button>
        ) : (
          <span key={n} className={cls} {...attr} onMouseEnter={() => setHover({ side, index: n })} onMouseLeave={() => setHover(null)}>
            {t}
          </span>
        );
      })}
    </div>
  );

  return (
    <div ref={box} className={`algraph v ${hover ? "hovering" : ""} ${onToggle ? "editable" : ""}`} data-testid="algraph">
      {col("src", src)}
      {col("tgt", tgt)}
      <svg className="align-svg" aria-hidden>
        {lines.map((l, i) => (
          <path
            key={l.id}
            className={`align-line draw ${l.status === "suggested" ? "sugg" : "strong"} ${lit.has(l.id) ? "hl" : ""}`}
            style={{ ["--i" as string]: i }}
            pathLength={1}
            d={l.d}
            data-la={l.a}
            data-lb={l.b}
          />
        ))}
      </svg>
    </div>
  );
}

const r = (n: number) => Math.round(n * 10) / 10;
