import { Fragment, useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { AnnotStatus } from "../../api";
import { stackArcs } from "./geometry";
import { boundaryToCp, cpLength, cpSlice, normalizeSelection, rangeToCp, segmentText, spanLevels } from "./spans";
import "./annot.css";

/** A run of text in the flow; `cp` is the code point of its first character (document or sentence based). */
export interface FlowPiece {
  key: string;
  cp: number;
  text: string;
  /** Context sentences around the current one. */
  dim?: boolean;
}

export interface FlowSpan {
  id: string;
  start: number;
  end: number;
  label: string;
  status: AnnotStatus;
  /** Colour index 1–8. */
  color: number;
  hasAttrs?: boolean;
}

export interface FlowRelation {
  id: string;
  from: string;
  to: string;
  label: string;
  status: AnnotStatus;
}

interface ArcView {
  id: string;
  path: string;
  mx: number;
  my: number;
  lw: number;
  x2: number;
  y2: number;
  label: string;
  status: AnnotStatus;
}

const LEVEL = 18;
const NO_RELATIONS: FlowRelation[] = [];
const lw = (label: string) => [...label].reduce((w, ch) => w + (/[⺀-￿]/.test(ch) ? 11 : 6.8), 0) + 10;

/** Full flow text with gaps between pieces filled by spaces, so string positions equal flow code points − base. */
function flowString(pieces: FlowPiece[]): { base: number; text: string } {
  if (!pieces.length) return { base: 0, text: "" };
  const base = pieces[0].cp;
  let text = "";
  let at = base;
  for (const p of pieces) {
    if (p.cp > at) text += " ".repeat(p.cp - at);
    text += p.text;
    at = p.cp + cpLength(p.text);
  }
  return { base, text };
}

/** Code point under a screen point (caret position), or null. */
function cpAtPoint(root: Element, x: number, y: number): number | null {
  const d = root.ownerDocument as Document & {
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
  };
  const pos = d.caretPositionFromPoint?.(x, y);
  if (pos) return boundaryToCp(root, pos.offsetNode, pos.offset);
  const r = d.caretRangeFromPoint?.(x, y);
  return r ? boundaryToCp(root, r.startContainer, r.startOffset) : null;
}

/**
 * Text flow with span underlines (stacked when nested or overlapping), a label tag after each span and relation
 * arcs above the text. Interactive when handlers are given: select text to create, click a span or tag to select,
 * click an arc label to select a relation, drag the selected span's end handles to move its boundaries.
 */
export function SpanText({
  pieces,
  spans,
  relations = NO_RELATIONS,
  selected,
  selectedRelation,
  relFrom,
  pending,
  onSelectText,
  onSelectSpan,
  onSelectRelation,
  onBoundary,
  className,
  label,
}: {
  pieces: FlowPiece[];
  spans: FlowSpan[];
  relations?: FlowRelation[];
  selected?: string | null;
  selectedRelation?: string | null;
  relFrom?: string | null;
  pending?: { start: number; end: number } | null;
  onSelectText?: (r: { start: number; end: number }) => void;
  onSelectSpan?: (id: string | null, e: React.MouseEvent) => void;
  onSelectRelation?: (id: string) => void;
  onBoundary?: (id: string, start: number, end: number) => void;
  className?: string;
  label?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const flow = useRef<HTMLDivElement>(null);
  const [arcs, setArcs] = useState<{ list: ArcView[]; top: number }>({ list: [], top: 0 });
  const [handles, setHandles] = useState<{ sx: number; sy: number; ex: number; ey: number; h: number } | null>(null);
  const [drag, setDrag] = useState<{ edge: "start" | "end"; cp: number } | null>(null);
  // The click that ends a drag-selection must not clear the new selection.
  const justSelected = useRef(false);

  const all = useMemo(() => (pending ? [...spans, { id: "__pending", start: pending.start, end: pending.end, label: "", status: "suggested" as AnnotStatus, color: 0 }] : spans), [spans, pending]);
  const levels = useMemo(() => spanLevels(all), [all]);
  const byId = useMemo(() => new Map(all.map((s) => [s.id, s])), [all]);
  const sel = selected ? byId.get(selected) : undefined;
  // While dragging a handle, the selected span shows its new extent.
  const shown = useMemo(() => {
    if (!drag || !sel) return all;
    const start = drag.edge === "start" ? Math.min(drag.cp, sel.end - 1) : sel.start;
    const end = drag.edge === "end" ? Math.max(drag.cp, sel.start + 1) : sel.end;
    return all.map((s) => (s.id === sel.id ? { ...s, start, end } : s));
  }, [all, drag, sel]);
  const shownById = useMemo(() => new Map(shown.map((s) => [s.id, s])), [shown]);

  /* ---------- measure: relation arcs and handles follow the rendered text ---------- */
  const measure = useCallback(() => {
    const root = box.current;
    if (!root) return;
    const r0 = root.getBoundingClientRect();
    const firstLine = (id: string) => {
      const rects = [...root.querySelectorAll(`[data-sid="${id.replace(/"/g, '\\"')}"]`)].flatMap((el) => {
        const rs = [...el.getClientRects()];
        return rs.length ? rs : [el.getBoundingClientRect()];
      });
      if (!rects.length) return null;
      const top = Math.min(...rects.map((r) => r.top));
      const line = rects.filter((r) => r.top - top < 4);
      const left = Math.min(...line.map((r) => r.left));
      const right = Math.max(...line.map((r) => r.right));
      return { x: (left + right) / 2 - r0.left, y: top - r0.top, rects };
    };
    const work = relations
      .filter((r) => r.status !== "rejected" || r.id === selectedRelation)
      .map((r) => {
        const a = firstLine(r.from);
        const b = firstLine(r.to);
        if (!a || !b) return null;
        return { r, a, b, lo: Math.min(a.x, b.x), hi: Math.max(a.x, b.x), mx: (a.x + b.x) / 2, lw: lw(r.label), lvl: 1 };
      })
      .filter((x): x is NonNullable<typeof x> => !!x);
    stackArcs(work);
    const maxLvl = Math.max(0, ...work.map((w) => w.lvl));
    const list = work.map((w) => {
      const y = Math.min(w.a.y, w.b.y) - 3;
      const h = 10 + w.lvl * LEVEL;
      const cy = y - h * 1.33;
      const y1 = w.a.y - 3;
      const y2 = w.b.y - 3;
      return {
        id: w.r.id,
        path: `M${w.a.x} ${y1} C${w.a.x} ${cy} ${w.b.x} ${cy} ${w.b.x} ${y2}`,
        mx: w.mx,
        my: y - h,
        lw: w.lw,
        x2: w.b.x,
        y2,
        label: w.r.label,
        status: w.r.status,
      };
    });
    setArcs((prev) => (JSON.stringify(prev) === JSON.stringify({ list, top: maxLvl }) ? prev : { list, top: maxLvl }));
    if (selected && onBoundary) {
      const m = firstLine(selected);
      if (m) {
        const first = m.rects[0];
        const last = m.rects[m.rects.length - 1];
        const next = { sx: first.left - r0.left, sy: first.top - r0.top, ex: last.right - r0.left, ey: last.top - r0.top, h: first.height };
        setHandles((p) => (JSON.stringify(p) === JSON.stringify(next) ? p : next));
      } else setHandles(null);
    } else setHandles(null);
  }, [relations, selected, selectedRelation, onBoundary]);

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

  /** Spans are not focusable: drop focus left on an outside button so Enter and label keys reach the editor, not that button. */
  function releaseFocus() {
    const a = box.current?.ownerDocument.activeElement;
    if (a instanceof HTMLElement && a !== a.ownerDocument.body && !box.current?.contains(a)) a.blur();
  }

  /* ---------- text selection ---------- */
  function onMouseUp() {
    if (!onSelectText || drag) return;
    releaseFocus();
    const root = flow.current;
    const s = root?.ownerDocument.getSelection();
    if (!root || !s || !s.rangeCount || s.isCollapsed) return;
    const r = rangeToCp(root, s.getRangeAt(0));
    if (!r) return;
    const f = flowString(pieces);
    const n = normalizeSelection(f.text, r.start - f.base, r.end - f.base);
    s.removeAllRanges();
    if (n) {
      justSelected.current = true;
      setTimeout(() => (justSelected.current = false), 0);
      onSelectText({ start: n.start + f.base, end: n.end + f.base });
    }
  }

  function clickSpan(e: React.MouseEvent) {
    if (!onSelectSpan || justSelected.current) return;
    const s = flow.current?.ownerDocument.getSelection();
    if (s && !s.isCollapsed) return; // a drag-selection, not a click
    const t = (e.target as Element).closest("[data-sid]") as HTMLElement | null;
    const id = t?.dataset.sid;
    releaseFocus();
    onSelectSpan(id && id !== "__pending" ? id : null, e);
  }

  /* ---------- boundary handles ---------- */
  function startDrag(e: React.PointerEvent, edge: "start" | "end") {
    if (!sel) return;
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    setDrag({ edge, cp: edge === "start" ? sel.start : sel.end });
  }
  function moveDrag(e: React.PointerEvent) {
    if (!drag || !flow.current) return;
    const cp = cpAtPoint(flow.current, e.clientX, e.clientY);
    if (cp != null && cp !== drag.cp) setDrag({ ...drag, cp });
  }
  function endDrag() {
    if (!drag || !sel) return;
    const s = shownById.get(sel.id)!;
    setDrag(null);
    if (s.start !== sel.start || s.end !== sel.end) onBoundary?.(sel.id, s.start, s.end);
  }

  /* ---------- render ---------- */
  const endsAt = useMemo(() => {
    const m = new Map<number, FlowSpan[]>();
    for (const s of shown) if (s.id !== "__pending") m.set(s.end, [...(m.get(s.end) ?? []), s as FlowSpan]);
    return m;
  }, [shown]);

  const tag = (s: FlowSpan) => (
    <span
      key={`t${s.id}`}
      className={`stag ${s.status} ${s.id === selected ? "on" : ""} ${s.id === relFrom ? "from" : ""}`}
      data-c={s.color}
      data-tag={s.id}
      contentEditable={false}
      onMouseDown={(e) => onSelectSpan && e.preventDefault()}
      onClick={onSelectSpan ? (e) => (e.stopPropagation(), releaseFocus(), onSelectSpan(s.id, e)) : undefined}
      role={onSelectSpan ? "button" : undefined}
      aria-label={onSelectSpan ? `${s.label}，选择片段` : undefined}
    >
      {s.label}
      {s.hasAttrs && <i className="stag-dot" />}
    </span>
  );

  return (
    <div
      ref={box}
      className={`spanbox ${onSelectText ? "editable" : ""} ${className ?? ""}`}
      style={{ paddingTop: 14 + arcs.top * LEVEL + (arcs.top ? 12 : 0) }}
      onPointerMove={drag ? moveDrag : undefined}
      onPointerUp={drag ? endDrag : undefined}
      onPointerCancel={() => setDrag(null)}
    >
      <div ref={flow} className="span-flow" role="document" aria-label={label} onMouseUp={onMouseUp} onClick={onSelectSpan ? clickSpan : undefined}>
        {pieces.map((p, pi) => {
          const len = cpLength(p.text);
          const local = shown
            .filter((s) => s.end > p.cp && s.start < p.cp + len)
            .map((s) => ({ ...s, start: Math.max(s.start, p.cp) - p.cp, end: Math.min(s.end, p.cp + len) - p.cp }));
          const segs = segmentText(len, local, levels);
          const prevEnd = pi > 0 ? pieces[pi - 1].cp + cpLength(pieces[pi - 1].text) : p.cp;
          return (
            <Fragment key={p.key}>
              {pi > 0 && <span className="sgap">{p.cp > prevEnd ? " " : ""}</span>}
              <span className={`spiece ${p.dim ? "dim" : ""}`}>
                {segs.map((g) => {
                  let node: React.ReactNode = <span data-cp={p.cp + g.start}>{cpSlice(p.text, g.start, g.end)}</span>;
                  for (const id of [...g.ids].reverse()) {
                    const s = shownById.get(id)!;
                    const lvl = levels.get(id) ?? 0;
                    node = (
                      <span
                        className={`smk ${s.status} ${id === "__pending" ? "pend" : ""} ${id === selected ? "on" : ""} ${id === relFrom ? "from" : ""}`}
                        data-sid={id}
                        data-c={s.color || undefined}
                        style={{ ["--lv" as string]: lvl }}
                      >
                        {node}
                      </span>
                    );
                  }
                  const ends = endsAt.get(p.cp + g.end) ?? [];
                  return (
                    <Fragment key={g.start}>
                      {node}
                      {ends.map(tag)}
                    </Fragment>
                  );
                })}
              </span>
            </Fragment>
          );
        })}
      </div>
      {arcs.list.length > 0 && (
        <svg className="rel-svg" aria-hidden={!onSelectRelation}>
          {arcs.list.map((a, i) => (
            <g key={a.id} className={`rarc ${a.status} ${a.id === selectedRelation ? "on" : ""}`} data-rel={a.id}>
              <path className="draw" style={{ ["--i" as string]: i }} pathLength={a.status === "suggested" || a.status === "rejected" ? undefined : 1} d={a.path} />
              <polygon points={`${a.x2 - 4},${a.y2 - 7} ${a.x2 + 4},${a.y2 - 7} ${a.x2},${a.y2}`} />
              <g
                className={`rlab ${onSelectRelation ? "click" : ""}`}
                onClick={onSelectRelation ? () => onSelectRelation(a.id) : undefined}
                onMouseDown={(e) => e.preventDefault()}
                role={onSelectRelation ? "button" : undefined}
                aria-label={onSelectRelation ? `${a.label}，选择关系` : undefined}
              >
                <rect x={a.mx - a.lw / 2} y={a.my - 9} width={a.lw} height={16} rx={4} />
                <text x={a.mx} y={a.my + 3} textAnchor="middle">
                  {a.label}
                </text>
              </g>
            </g>
          ))}
        </svg>
      )}
      {handles && sel && (
        <>
          <span className="shandle" style={{ left: handles.sx - 3, top: handles.sy, height: handles.h }} onPointerDown={(e) => startDrag(e, "start")} title="拖动改起点" />
          <span className="shandle" style={{ left: handles.ex - 3, top: handles.ey, height: handles.h }} onPointerDown={(e) => startDrag(e, "end")} title="拖动改终点" />
        </>
      )}
    </div>
  );
}
