import { useEffect, useMemo, useRef, useState } from "react";
import { posCat } from "../../lib/pos";
import { headFromDrop, layoutDeps, tokenAt, type GraphArc, type GraphToken } from "./geometry";
import "./annot.css";

/**
 * Dependency arcs above a token row (SVG). Arcs draw in on mount (remount with a new key to replay);
 * suggested arcs are dashed. Interactive when handlers are given: click a token, click a relation label,
 * drag an arc's head end (or the root tick's top) onto another token to change the head.
 */
export function DepGraph({
  tokens,
  arcs,
  selected,
  highlight,
  onSelectToken,
  onSelectArc,
  onHeadChange,
  posColor,
  label,
}: {
  tokens: GraphToken[];
  arcs: GraphArc[];
  selected?: number | null;
  highlight?: number[];
  onSelectToken?: (index: number) => void;
  onSelectArc?: (dep: number) => void;
  onHeadChange?: (dep: number, head: number) => void;
  posColor?: boolean;
  label?: string;
}) {
  const layout = useMemo(() => layoutDeps(tokens, arcs), [tokens, arcs]);
  const svg = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<{ dep: number; head: number; from: number; fromY: number; x: number; y: number } | null>(null);
  const hl = new Set(highlight ?? []);
  const { y0, top } = layout;
  const n = layout.arcs.length;
  // Arcs draw in one after another on mount; later changes (a new head, a confirmation) redraw only that arc, at once.
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setSettled(true), 900 + n * 90);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const rootI = settled ? 0 : n;

  function point(e: React.PointerEvent): { x: number; y: number } {
    const box = svg.current!.getBoundingClientRect();
    const k = box.width ? layout.width / box.width : 1;
    return { x: (e.clientX - box.left) * k, y: (e.clientY - box.top) * k };
  }

  function startDrag(e: React.PointerEvent, dep: number, head: number, from: number, fromY: number) {
    if (!onHeadChange) return;
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    const p = point(e);
    setDrag({ dep, head, from, fromY, ...p });
  }

  const target = drag ? tokenAt(layout, drag.x) : null;

  return (
    <svg
      ref={svg}
      className={`depsvg ${onHeadChange ? "editable" : ""} ${onSelectToken ? "clickable" : ""} ${posColor ? "poscolor" : ""}`}
      width={layout.width}
      height={layout.height}
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      role="img"
      aria-label={label ?? `依存树：${tokens.map((t) => t.form).join(" ")}`}
      onPointerMove={drag ? (e) => setDrag({ ...drag, ...point(e) }) : undefined}
      onPointerUp={
        drag
          ? (e) => {
              const p = point(e);
              const head = headFromDrop(layout, drag.dep, drag.head, p.x);
              setDrag(null);
              if (head != null) onHeadChange?.(drag.dep, head);
            }
          : undefined
      }
      onPointerCancel={() => setDrag(null)}
    >
      {layout.tokens.map((t) => {
        return (
          <g
            key={`t${t.index}`}
            className={`dtk ${selected === t.index ? "sel" : ""} ${hl.has(t.index) ? "hl" : ""} ${target === t.index ? "drop" : ""}`}
            data-index={t.index}
            onClick={onSelectToken ? () => onSelectToken(t.index) : undefined}
            onMouseDown={(e) => e.preventDefault()}
          >
            <rect className="dtk-bg" x={t.x - t.w / 2} y={y0 + 2} width={t.w} height={42} rx={8}/>
            <text className="dtk-form" x={t.x} y={y0 + 22} textAnchor="middle">
              {t.form}
            </text>
            {t.pos && (
              <text className="dtk-pos" x={t.x} y={y0 + 38} textAnchor="middle" data-c={posCat(t.pos)}>
                {t.pos}
              </text>
            )}
          </g>
        );
      })}
      {[...layout.arcs]
        .sort((a, b) => b.lvl - a.lvl)
        .map((a, i) => {
          const o = settled ? 0 : n - 1 - i;
          const active = selected === a.dep;
          return (
            <g key={`a${a.dep}-${a.head}-${a.suggested ? "s" : "c"}`} className={`darc ${a.suggested ? "sugg" : ""} ${active ? "on" : ""} ${drag?.dep === a.dep ? "dragging" : ""}`} data-dep={a.dep} data-head={a.head}>
              <path className="arc draw" style={{ ["--i" as string]: o }} pathLength={a.suggested ? undefined : 1} d={a.path} />
              <polygon className="arrow" style={{ ["--i" as string]: o }} points={`${a.xd - 4},${y0 - 9} ${a.xd + 4},${y0 - 9} ${a.xd},${y0 - 1}`} />
              <g
                className={`rel ${onSelectArc ? "click" : ""}`}
                style={{ ["--i" as string]: o }}
                onClick={onSelectArc ? () => onSelectArc(a.dep) : undefined}
                onMouseDown={(e) => e.preventDefault()}
                role={onSelectArc ? "button" : undefined}
                aria-label={onSelectArc ? `${a.label}，改关系` : undefined}
              >
                <rect className="rel-bg" x={a.mx - a.lw / 2} y={a.my - 9} width={a.lw} height={14} rx={3} />
                <text x={a.mx} y={a.my + 2} textAnchor="middle">
                  {a.label}
                </text>
              </g>
              {onHeadChange && (
                <circle className="handle" cx={a.xh} cy={y0 - 3} r={5} onPointerDown={(e) => startDrag(e, a.dep, a.head, a.xd, y0 - 2)}>
                  <title>拖到另一个词以改中心词</title>
                </circle>
              )}
            </g>
          );
        })}
      {layout.roots.map((r0) => (
        <g key={`r${r0.dep}-${r0.suggested ? "s" : "c"}`} className={`darc root ${r0.suggested ? "sugg" : ""} ${selected === r0.dep ? "on" : ""}`} data-dep={r0.dep} data-head={0}>
          <path className="arc draw" style={{ ["--i" as string]: rootI }} pathLength={r0.suggested ? undefined : 1} d={r0.path} />
          <polygon className="arrow" style={{ ["--i" as string]: rootI }} points={`${r0.x - 4},${y0 - 9} ${r0.x + 4},${y0 - 9} ${r0.x},${y0 - 1}`} />
          <g
            className={`rel ${onSelectArc ? "click" : ""}`}
            style={{ ["--i" as string]: rootI }}
            onClick={onSelectArc ? () => onSelectArc(r0.dep) : undefined}
            onMouseDown={(e) => e.preventDefault()}
            role={onSelectArc ? "button" : undefined}
            aria-label={onSelectArc ? `${r0.label}，改关系` : undefined}
          >
            <rect className="rel-bg" x={r0.x + 4} y={top + 2} width={r0.label.length * 6.8 + 8} height={14} rx={3} />
            <text x={r0.x + 8} y={top + 13}>
              {r0.label}
            </text>
          </g>
          {onHeadChange && (
            <circle className="handle" cx={r0.x} cy={top} r={5} onPointerDown={(e) => startDrag(e, r0.dep, 0, r0.x, y0 - 2)}>
              <title>拖到另一个词以改中心词</title>
            </circle>
          )}
        </g>
      ))}
      {drag && (
        <path
          className="drag-line"
          d={`M${drag.from} ${drag.fromY} Q${(drag.from + drag.x) / 2} ${Math.min(drag.y, drag.fromY) - 30} ${drag.x} ${drag.y}`}
        />
      )}
    </svg>
  );
}
