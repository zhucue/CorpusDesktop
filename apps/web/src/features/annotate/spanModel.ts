import type { Alignment, AlignmentPatch, AnnotStatus, LabelDef, PairToken, Relation, SentenceSpans, Span, SpanPatch } from "../../api";
import type { DiffToken } from "../../components/annot/DiffRows";
import type { FlowRelation, FlowSpan } from "../../components/annot/SpanText";
import { labelColor } from "../../components/annot/spans";
import { labelForKey, type KeyLike } from "./model";

export const isSuggested = (x: { status: AnnotStatus }) => x.status === "suggested";
export const isHumanSource = (source: string) => source === "human" || source.startsWith("human");

/** A sentence is done when nothing in it is still a suggestion. */
export function spanSentenceDone(s: SentenceSpans): boolean {
  return !s.spans.some(isSuggested) && !s.relations.some(isSuggested);
}

export function sortSpans(spans: Span[]): Span[] {
  return [...spans].sort((a, b) => a.start_cp - b.start_cp || b.end_cp - a.end_cp);
}

export function flowSpans(spans: Span[], labelOrder: string[]): FlowSpan[] {
  return spans.map((s) => ({
    id: s.id,
    start: s.start_cp,
    end: s.end_cp,
    label: s.label,
    status: s.status,
    color: labelColor(s.label, labelOrder),
    hasAttrs: !!s.attrs && Object.keys(s.attrs).length > 0,
  }));
}

export function flowRelations(relations: Relation[]): FlowRelation[] {
  return relations.map((r) => ({ id: r.id, from: r.from_span_id, to: r.to_span_id, label: r.label, status: r.status }));
}

/**
 * Span diff as P3 diff tokens: model label above, human value below; human-made spans have no model value.
 * `show` limits the span rows (a span crossing sentences is listed once); relations still name every span.
 */
export function spanDiffTokens(s: SentenceSpans, show: (x: Span) => boolean = () => true): DiffToken[] {
  const text = new Map(s.spans.map((x) => [x.id, x.text]));
  return [
    ...sortSpans(s.spans.filter(show)).map((x) => ({
      form: x.text,
      // reviewing rewrites source to human:…; model_label keeps the pre-annotation (null for human-made spans)
      model: x.model_label ?? (isHumanSource(x.source) ? "" : x.label),
      human: x.status === "suggested" ? "" : x.label,
      status: x.status,
    })),
    ...s.relations.map((r) => ({
      form: `${text.get(r.from_span_id) ?? "?"} → ${text.get(r.to_span_id) ?? "?"}`,
      model: r.model_label ?? (isHumanSource(r.source) ? "" : r.label),
      human: r.status === "suggested" ? "" : r.label,
      status: r.status,
    })),
  ];
}

/** Diff rows per sentence in list order; a span that crosses sentences appears only in the first one. */
export function spanDiffBlocks(sentences: SentenceSpans[], keep: (x: { annotator_id: string | null }) => boolean): { s: SentenceSpans; toks: DiffToken[] }[] {
  const seen = new Set<string>();
  return sentences
    .map((s) => {
      const mine = { ...s, spans: s.spans.filter(keep), relations: s.relations.filter(keep) };
      const toks = spanDiffTokens(mine, (x) => (seen.has(x.id) ? false : (seen.add(x.id), true)));
      return { s, toks };
    })
    .filter((b) => b.toks.length > 0);
}

/** Optimistic span state after an action. */
export function patchedSpan(s: Span, body: { action: "confirm" | "modify" | "reject"; label?: string; start_cp?: number; end_cp?: number; attrs?: Record<string, string> }): Span {
  if (body.action === "confirm") return { ...s, status: "confirmed" };
  if (body.action === "reject") return { ...s, status: "rejected" };
  return {
    ...s,
    status: "modified",
    label: body.label ?? s.label,
    start_cp: body.start_cp ?? s.start_cp,
    end_cp: body.end_cp ?? s.end_cp,
    attrs: body.attrs ?? s.attrs,
  };
}

const sameNums = (a: number[] | null | undefined, b: number[] | null | undefined) =>
  JSON.stringify([...(a ?? [])].sort((x, y) => x - y)) === JSON.stringify([...(b ?? [])].sort((x, y) => x - y));
const sameAttrs = (a: Record<string, string> | null | undefined, b: Record<string, string> | null | undefined) =>
  JSON.stringify(Object.entries(a ?? {}).sort()) === JSON.stringify(Object.entries(b ?? {}).sort());

/**
 * The request to send for a span action: a "modify" that changes nothing confirms a suggestion and is skipped
 * otherwise (null), so an unchanged span is not recorded as modified. Modifying a rejected span restores it.
 */
export function effectiveSpanPatch(s: Span, body: SpanPatch): SpanPatch | null {
  if (body.action !== "modify" || s.status === "rejected") return body;
  const changed =
    (body.label !== undefined && body.label !== s.label) ||
    (body.start_cp !== undefined && body.start_cp !== s.start_cp) ||
    (body.end_cp !== undefined && body.end_cp !== s.end_cp) ||
    (body.attrs !== undefined && !sameAttrs(body.attrs, s.attrs));
  if (changed) return body;
  return s.status === "suggested" ? { action: "confirm" } : null;
}

/** Same rule for alignments: unchanged tokens and target sentence confirm a suggestion. */
export function effectiveAlignPatch(a: Alignment, body: AlignmentPatch, tgtSentence: number | null | undefined): AlignmentPatch | null {
  if (body.action !== "modify" || a.status === "rejected") return body;
  const changed =
    (body.src_tokens !== undefined && !sameNums(body.src_tokens, a.src_tokens)) ||
    (body.tgt_tokens !== undefined && !sameNums(body.tgt_tokens, a.tgt_tokens)) ||
    (body.tgt_sentence_index !== undefined && body.tgt_sentence_index !== (a.tgt_sentence_index ?? tgtSentence));
  if (changed) return body;
  return a.status === "suggested" ? { action: "confirm" } : null;
}

/* ---------- keyboard ---------- */

export type SpanCommand =
  | { type: "confirm" }
  | { type: "reject" }
  | { type: "span"; delta: 1 | -1 }
  | { type: "sentence"; delta: 1 | -1 }
  | { type: "label"; label: string }
  | { type: "edit" }
  | { type: "relation" }
  | { type: "cancel" };

/** Span editor keys: digits / letters pick labels, Enter confirms, Del rejects, ←/→ spans, J/K sentences, R starts a relation. */
export function spanKeyCommand(e: KeyLike, ctx: { labels: LabelDef[]; relations: boolean }): SpanCommand | null {
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  switch (e.key) {
    case "Enter":
      return { type: "confirm" };
    case "Delete":
    case "Backspace":
      return { type: "reject" };
    case "ArrowRight":
      return { type: "span", delta: 1 };
    case "ArrowLeft":
      return { type: "span", delta: -1 };
    case "Escape":
      return { type: "cancel" };
  }
  const k = e.key.toLowerCase();
  if (k === "j") return { type: "sentence", delta: 1 };
  if (k === "k") return { type: "sentence", delta: -1 };
  if (k === "e") return { type: "edit" };
  if (k === "r" && ctx.relations) return { type: "relation" };
  const l = labelForKey(e.key, ctx.labels);
  return l ? { type: "label", label: l.name } : null;
}

/* ---------- alignment ---------- */

/** Token forms in order (strings or `{index?, form}`; indices are 1-based). */
export function tokenForms(tokens: PairToken[] | undefined): string[] {
  const list = (tokens ?? []).map((t, i) => (typeof t === "string" ? { index: i + 1, form: t } : { index: t.index ?? i + 1, form: t.form }));
  return list.sort((a, b) => a.index - b.index).map((t) => t.form);
}

export function pairDone(alignments: Alignment[]): boolean {
  return !alignments.some(isSuggested);
}

export function fmtScore(v: number | null | undefined): string {
  return v == null ? "—" : v.toFixed(2);
}

/** κ / α display. */
export function fmtKappa(v: number | null | undefined): string {
  return v == null || Number.isNaN(v) ? "—" : v.toFixed(2);
}

/** Landis & Koch bands. */
export function kappaBand(v: number | null | undefined): { text: string; cls: "" | "mid" | "low" } {
  if (v == null) return { text: "", cls: "" };
  if (v >= 0.8) return { text: "一致性高", cls: "" };
  if (v >= 0.6) return { text: "一致性较好", cls: "" };
  if (v >= 0.4) return { text: "一致性中等", cls: "mid" };
  return { text: "一致性低", cls: "low" };
}
