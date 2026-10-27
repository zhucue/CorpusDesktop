import { Fragment, useEffect, useRef, type ReactNode } from "react";
import type { EvidenceInput, HitToken } from "../../api";
import { isPunctPos, posCat } from "../../lib/pos";
import { cpLength, cpSlice } from "../annot/spans";
import { PinButton } from "../global/evidence";
import { Icon } from "../Icon";

export interface KwicRow {
  id: string;
  left: string;
  match: string;
  right: string;
  source: string;
  aligned?: { language: string; text: string }[];
  tokens?: HitToken[];
  evidence?: EvidenceInput;
}

/** Wrap occurrences of literal condition terms (from "+term") in .hit-2. */
export function markTerms(text: string, terms: string[]): ReactNode {
  const words = terms.filter((t) => t.length > 0);
  if (!words.length || !text) return text;
  const re = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "g");
  const parts = text.split(re);
  return parts.map((p, i) => (i % 2 ? <span key={i} className="hit-2">{p}</span> : p));
}

/** Literal words from ParseResult conditions ("+文化" → 文化); skips pos-only or wildcard terms. */
export function conditionTerms(conditions: { op: "+" | "-"; text: string }[] | undefined): string[] {
  return (conditions ?? [])
    .filter((c) => c.op === "+")
    .flatMap((c) => c.text.split("|"))
    .map((t) => t.replace(/^"|"$/g, "").split("/")[0].trim())
    .filter((t) => t && !/[*?$]/.test(t));
}

function PosText({ tokens, part }: { tokens: HitToken[]; part: HitToken["part"] }) {
  const list = tokens.filter((t) => t.part === part);
  return (
    <>
      {list.map((t, i) => {
        const pos = t.pos;
        if (!pos || isPunctPos(pos))
          return (
            <span key={i}>
              {t.form}
              {spaceAfter(t, list[i + 1])}
            </span>
          );
        return (
          <span key={i}>
            <span className="pw" data-c={posCat(pos)} title={`${t.form} · ${pos}`}>
              {t.form}
            </span>
            {spaceAfter(t, list[i + 1])}
          </span>
        );
      })}
    </>
  );
}

const cjk = /[　-鿿＀-￯]/;
function spaceAfter(a: HitToken, b: HitToken | undefined): string {
  if (!b) return "";
  return cjk.test(a.form.slice(-1)) || cjk.test(b.form[0] ?? "") || /^([.,;:!?)]|n't$|'\w*$)/i.test(b.form) ? "" : " "; // English clitics: could n't → couldn't
}

/** A span to highlight in a KWIC row; code points within left + match + right. */
export interface KwicMark {
  start: number;
  end: number;
  label: string;
  color?: number;
}

/** Text of one row part with span marks (offset = code point of the part's start in the row); other text keeps term marks. */
export function markSpans(text: string, offset: number, marks: KwicMark[], terms: string[]): ReactNode {
  const len = cpLength(text);
  const local = marks
    .map((m) => ({ ...m, start: Math.max(0, m.start - offset), end: Math.min(len, m.end - offset) }))
    .filter((m) => m.end > m.start)
    .sort((a, b) => a.start - b.start);
  if (!local.length) return markTerms(text, terms);
  const out: ReactNode[] = [];
  let at = 0;
  local.forEach((m, i) => {
    const start = Math.max(m.start, at);
    if (start > at) out.push(<Fragment key={`p${i}`}>{markTerms(cpSlice(text, at, start), terms)}</Fragment>);
    if (m.end > start)
      out.push(
        <mark key={`m${i}`} className="kspan" data-c={m.color} title={m.label}>
          {cpSlice(text, start, m.end)}
          <span className="kspan-lab">{m.label}</span>
        </mark>,
      );
    at = Math.max(at, m.end);
  });
  if (at < len) out.push(<Fragment key="rest">{markTerms(cpSlice(text, at), terms)}</Fragment>);
  return out;
}

export function hasPos(rows: KwicRow[]): boolean {
  return rows.some((r) => r.tokens?.some((t) => t.pos));
}

/** KWIC table: right-aligned left context, centred match, right context with aligned sentence, source, pin. */
export function KwicTable({
  rows,
  terms = [],
  posColor = false,
  selected,
  onSelect,
  compact,
  offset,
  expanded,
  onExpand,
  renderExpanded,
  expandLabel = "依存树",
  extraActions,
  marks,
  onRowVisible,
}: {
  rows: KwicRow[];
  terms?: string[];
  posColor?: boolean;
  selected?: string | null;
  onSelect?: (id: string) => void;
  compact?: boolean;
  offset?: number;
  /** Row expander (e.g. 依存树); shown only when renderExpanded is given. */
  expanded?: string | null;
  onExpand?: (id: string | null) => void;
  renderExpanded?: (row: KwicRow) => ReactNode;
  expandLabel?: string;
  /** More row buttons before the pin (e.g. 加入术语例句). */
  extraActions?: (row: KwicRow) => ReactNode;
  /** Span highlights per row (P5 片段层); ignored while POS colouring is on. */
  marks?: (row: KwicRow) => KwicMark[] | undefined;
  /** Called once a row scrolls into view (lazy loading of row data). */
  onRowVisible?: (id: string) => void;
}) {
  const body = useRef<HTMLTableSectionElement>(null);
  const visibleRef = useRef(onRowVisible);
  visibleRef.current = onRowVisible;
  const ids = rows.map((r) => r.id).join("|");
  useEffect(() => {
    const el = body.current;
    if (!el || !visibleRef.current) return;
    const trs = [...el.querySelectorAll<HTMLElement>("tr[data-row]")];
    if (typeof IntersectionObserver === "undefined") {
      trs.forEach((tr) => visibleRef.current?.(tr.dataset.row!));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      for (const e of entries)
        if (e.isIntersecting) {
          visibleRef.current?.((e.target as HTMLElement).dataset.row!);
          io.unobserve(e.target);
        }
    });
    trs.forEach((tr) => io.observe(tr));
    return () => io.disconnect();
  }, [ids, !!onRowVisible]); // eslint-disable-line react-hooks/exhaustive-deps
  const cols = (offset != null ? 1 : 0) + 5;
  const actionCount = 1 + (renderExpanded ? 1 : 0) + (extraActions ? 1 : 0);
  return (
    <table className={`tbl kwic ${posColor ? "poscolor" : ""}`}>
      <colgroup>
        {offset != null && <col style={{ width: 52 }} />}
        <col style={{ width: compact ? "34%" : "34%" }} />
        <col style={{ width: compact ? 72 : 110 }} />
        <col />
        <col style={{ width: compact ? 96 : 150 }} />
        <col style={{ width: 8 + 28 * actionCount }} />
      </colgroup>
      {!compact && (
        <thead>
          <tr>
            {offset != null && <th>#</th>}
            <th className="r">左语境</th>
            <th style={{ textAlign: "center" }}>命中</th>
            <th>右语境</th>
            <th>出处</th>
            <th />
          </tr>
        </thead>
      )}
      <tbody className="stagger" ref={body}>
        {rows.map((r, i) => {
          const pos = posColor && r.tokens?.length;
          const open = !!renderExpanded && expanded === r.id;
          const mk = !pos ? marks?.(r) : undefined;
          const lLen = mk?.length ? cpLength(r.left) : 0;
          const mLen = mk?.length ? cpLength(r.match) : 0;
          return (
            <Fragment key={r.id}>
            <tr
              key={r.id}
              data-row={r.id}
              className={selected === r.id ? "sel" : undefined}
              style={{ ["--i" as string]: i }}
              onClick={onSelect ? () => onSelect(r.id) : undefined}
              aria-selected={onSelect ? selected === r.id : undefined}
            >
              {offset != null && <td className="mono muted small">{offset + i + 1}</td>}
              <td className="lc">
                <span>{pos ? <PosText tokens={r.tokens!} part="left" /> : mk?.length ? markSpans(r.left, 0, mk, terms) : markTerms(r.left, terms)}</span>
              </td>
              <td className="kw">
                <span className="hit" data-testid="kwic-match">
                  {pos ? <PosText tokens={r.tokens!} part="match" /> : mk?.length ? markSpans(r.match, lLen, mk, []) : r.match}
                </span>
              </td>
              <td className="rc">
                <div className="rt">{pos ? <PosText tokens={r.tokens!} part="right" /> : mk?.length ? markSpans(r.right, lLen + mLen, mk, terms) : markTerms(r.right, terms)}</div>
                {r.aligned?.map((a, k) => (
                  <div className="al" key={k} title={a.text}>
                    <b>{a.language.toUpperCase()}</b> · {a.text}
                  </div>
                ))}
              </td>
              <td className="src" title={r.source}>
                {r.source}
              </td>
              <td className="row-acts">
                {renderExpanded && (
                  <button
                    className={`pin-btn exp-btn ${open ? "exp-on" : ""}`}
                    type="button"
                    aria-label={expandLabel}
                    title={expandLabel}
                    aria-expanded={open}
                    onClick={(e) => {
                      e.stopPropagation();
                      onExpand?.(open ? null : r.id);
                    }}
                  >
                    <Icon name="tree" size={14} />
                  </button>
                )}
                {extraActions?.(r)}
                {r.evidence && <PinButton input={r.evidence} />}
              </td>
            </tr>
            {open && (
              <tr className="kwic-exp">
                <td colSpan={cols}>{renderExpanded!(r)}</td>
              </tr>
            )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}
