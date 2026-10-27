import type { Annotation, AnnotationInput, AnnotStatus, LabelDef, LayerKind, SentenceAnnot } from "../../api";
import type { DiffToken } from "../../components/annot/DiffRows";
import type { GraphArc, GraphToken } from "../../components/annot/geometry";

/** One token as the editor shows it. Indices are 1-based; head 0 = root. */
export interface TokView {
  index: number;
  form: string;
  sysPos: string | null;
  /** pos layer: the tag; dep layer: the relation. */
  label: string | null;
  head: number | null;
  status: AnnotStatus;
  source: string;
  ann: Annotation | null;
}

export function annotationMap(s: SentenceAnnot): Map<number, Annotation> {
  return new Map(s.annotations.map((a) => [a.token_index, a]));
}

/**
 * Value shown for a token: the annotation's own value when it has one (suggestions included,
 * since Chinese dependency suggestions exist only in annotations), otherwise the system layer.
 */
export function tokenViews(s: SentenceAnnot, kind: LayerKind): TokView[] {
  const anns = annotationMap(s);
  return s.tokens.map((t) => {
    const a = anns.get(t.index) ?? null;
    const sysLabel = kind === "pos" ? t.system.pos : t.system.deprel;
    return {
      index: t.index,
      form: t.form,
      sysPos: t.system.pos,
      label: a?.label ?? a?.model_label ?? sysLabel,
      head: kind === "dep" ? (a?.head ?? a?.model_head ?? t.system.head) : null,
      status: a?.status ?? "suggested",
      source: a?.source ?? "system",
      ann: a,
    };
  });
}

export const isPending = (v: TokView) => v.status === "suggested";

export function sentenceStatus(s: SentenceAnnot): "pending" | "done" {
  const anns = annotationMap(s);
  const done = s.tokens.every((t) => {
    const st = anns.get(t.index)?.status;
    return !!st && st !== "suggested";
  });
  return done ? "done" : "pending";
}

/** Arcs for DepGraph; rejected tokens draw nothing. */
export function graphOf(views: TokView[]): { tokens: GraphToken[]; arcs: GraphArc[] } {
  return {
    tokens: views.map((v) => ({ index: v.index, form: v.form, pos: v.sysPos })),
    arcs: views
      .filter((v) => v.head != null && v.status !== "rejected")
      .map((v) => ({ dep: v.index, head: v.head!, label: v.label ?? "", suggested: v.status === "suggested" })),
  };
}

/** Optimistic result of one token action. */
export function applyAction(s: SentenceAnnot, input: AnnotationInput, now = new Date().toISOString()): SentenceAnnot {
  const tok = s.tokens.find((t) => t.index === input.token_index);
  if (!tok) return s;
  const prev = annotationMap(s).get(input.token_index);
  const base: Annotation = prev ?? {
    id: `tmp-${input.token_index}`,
    token_index: input.token_index,
    label: null,
    head: null,
    model_label: null,
    model_head: null,
    source: "system",
    status: "suggested",
    revision: 0,
    updated_by: null,
    updated_at: now,
  };
  const next: Annotation = { ...base, updated_at: now, revision: base.revision + 1 };
  if (input.action === "confirm") next.status = "confirmed";
  else if (input.action === "reject") next.status = "rejected";
  else {
    next.status = "modified";
    if (input.label !== undefined) next.label = input.label;
    if (input.head !== undefined) next.head = input.head;
  }
  return withAnnotation(s, next);
}

export function withAnnotation(s: SentenceAnnot, a: Annotation): SentenceAnnot {
  const rest = s.annotations.filter((x) => x.token_index !== a.token_index);
  const out: SentenceAnnot = { ...s, annotations: [...rest, a].sort((p, q) => p.token_index - q.token_index) };
  return { ...out, status: sentenceStatus(out) };
}

/** Restore one token's annotation (or its absence) after a failed request. */
export function restoreToken(s: SentenceAnnot, tokenIndex: number, prev: Annotation | undefined): SentenceAnnot {
  if (prev) return withAnnotation(s, prev);
  const out = { ...s, annotations: s.annotations.filter((x) => x.token_index !== tokenIndex) };
  return { ...out, status: sentenceStatus(out) };
}

/** Optimistic whole-sentence confirm: suggested → confirmed. */
export function confirmAll(s: SentenceAnnot, kind: LayerKind, now = new Date().toISOString()): SentenceAnnot {
  let out = s;
  for (const v of tokenViews(s, kind))
    if (isPending(v)) out = applyAction(out, { document_id: s.document_id, sentence_index: s.sentence_index, token_index: v.index, action: "confirm" }, now);
  return out;
}

/* ---------- diff ---------- */

export function diffTokens(s: SentenceAnnot, kind: LayerKind): DiffToken[] {
  const views = tokenViews(s, kind);
  const form = new Map(views.map((v) => [v.index, v.form]));
  const headText = (h: number | null) => (h == null ? "" : h === 0 ? "root" : (form.get(h) ?? String(h)));
  return views.map((v) => {
    const a = v.ann;
    const t = s.tokens.find((x) => x.index === v.index)!;
    if (kind === "pos") {
      const model = a?.model_label ?? t.system.pos ?? "";
      return { form: v.form, model, human: v.status === "suggested" ? "" : (v.label ?? ""), status: v.status };
    }
    const mLabel = a?.model_label ?? t.system.deprel ?? "";
    const mHead = a?.model_head ?? t.system.head;
    return {
      form: v.form,
      model: `${mLabel}→${headText(mHead)}`,
      human: v.status === "suggested" ? "" : `${v.label ?? ""}→${headText(v.head)}`,
      status: v.status,
    };
  });
}

/* ---------- labels and keys ---------- */

/** Letters after 1–9; E, J, K, P are taken by edit, sentence navigation and POS colouring. */
const LETTERS = "abcdfghilmnoqrstuvwxyz";

export function keyHint(i: number): string | null {
  if (i < 9) return String(i + 1);
  const l = LETTERS[i - 9];
  return l ? l.toUpperCase() : null;
}

export function labelForKey(key: string, labels: LabelDef[]): LabelDef | null {
  if (/^[1-9]$/.test(key)) return labels[Number(key) - 1] ?? null;
  if (key.length !== 1) return null;
  const i = LETTERS.indexOf(key.toLowerCase());
  return i >= 0 ? (labels[9 + i] ?? null) : null;
}

export type Command =
  | { type: "confirm" }
  | { type: "confirmSentence" }
  | { type: "reject" }
  | { type: "token"; delta: 1 | -1 }
  | { type: "sentence"; delta: 1 | -1 }
  | { type: "label"; label: string }
  | { type: "edit" }
  | { type: "posColor" };

export interface KeyLike {
  key: string;
  shiftKey?: boolean;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
}

/** Keyboard reducer for the editor: which command a key press means. */
export function keyCommand(e: KeyLike, ctx: { kind: LayerKind; labels: LabelDef[] }): Command | null {
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  switch (e.key) {
    case "Enter":
      return e.shiftKey ? { type: "confirmSentence" } : { type: "confirm" };
    case "Delete":
    case "Backspace":
      return ctx.kind === "pos" ? { type: "reject" } : null;
    case "ArrowRight":
      return { type: "token", delta: 1 };
    case "ArrowLeft":
      return { type: "token", delta: -1 };
  }
  const k = e.key.toLowerCase();
  if (k === "j") return { type: "sentence", delta: 1 };
  if (k === "k") return { type: "sentence", delta: -1 };
  if (k === "e") return { type: "edit" };
  if (k === "p") return { type: "posColor" };
  const l = labelForKey(e.key, ctx.labels);
  return l ? { type: "label", label: l.name } : null;
}

/** Next token after `from` that still needs review, wrapping; null when none is left. */
export function nextPending(views: TokView[], from: number): number | null {
  const n = views.length;
  const start = views.findIndex((v) => v.index === from);
  for (let k = 1; k <= n; k++) {
    const v = views[(start + k + n) % n];
    if (v && isPending(v)) return v.index;
  }
  return null;
}

export function layerPct(p: { total: number; confirmed: number; modified: number; rejected: number }): number {
  return p.total ? Math.round(((p.confirmed + p.modified + p.rejected) / p.total) * 100) : 0;
}

/**
 * Pre-annotation request that redoes the sentences listed in progress.failed_sentences: their documents and one
 * sentence range covering them (sentence_range applies to each document; reviewed rows are kept by the API).
 */
export function failedRetryBody(failed: unknown[] | undefined): { document_ids: string[]; sentence_range: { start: number; end: number } } | null {
  const items = (failed ?? []).filter(
    (f): f is { document_id: string; sentence_index: number } =>
      !!f && typeof (f as { document_id?: unknown }).document_id === "string" && Number.isInteger((f as { sentence_index?: unknown }).sentence_index),
  );
  if (!items.length) return null;
  const idx = items.map((f) => f.sentence_index);
  return { document_ids: [...new Set(items.map((f) => f.document_id))], sentence_range: { start: Math.min(...idx), end: Math.max(...idx) + 1 } };
}
