import { useInfiniteQuery, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { App } from "antd";
import { useCallback, useRef, useState } from "react";
import {
  MAX_PAGE_SIZE,
  api,
  errorText,
  type Alignment,
  type AlignmentPatch,
  type CursorPage,
  type Layer,
  type Member,
  type Page,
  type Relation,
  type SentencePair,
  type SentenceSpans,
  type Span,
  type SpanPatch,
} from "../../api";
import { useMe } from "../../lib/data";
import { effectiveAlignPatch, effectiveSpanPatch, patchedSpan } from "./spanModel";

export const SPAN_PAGE = 20;

/* Span and relation ids are numbers in the API; the editor keys DOM nodes by id, so they are kept as strings here. */
const normSpan = (x: Span): Span => ({ ...x, id: String(x.id) });
const normRel = (r: Relation): Relation => ({ ...r, id: String(r.id), from_span_id: String(r.from_span_id), to_span_id: String(r.to_span_id) });
const normSentence = (s: SentenceSpans): SentenceSpans => ({ ...s, spans: (s.spans ?? []).map(normSpan), relations: (s.relations ?? []).map(normRel) });
const normPage = (p: CursorPage<SentenceSpans>): CursorPage<SentenceSpans> => ({ ...p, items: p.items.map(normSentence) });
/** Numeric ids go back to the API as numbers. */
const apiId = (id: string): string | number => (/^\d+$/.test(id) ? Number(id) : id);

export function useMembers(projectId: string | undefined) {
  return useQuery({
    queryKey: ["members", projectId],
    queryFn: () => api.get<Page<Member>>(`/projects/${projectId}/members`, { page_size: MAX_PAGE_SIZE }),
    enabled: !!projectId,
    staleTime: 60 * 1000,
  });
}

/* ---------- spans ---------- */

export function useSpanSentences(layerId: string, docId: string | null, status: "pending" | "all") {
  return useInfiniteQuery({
    queryKey: ["span-sentences", layerId, docId, status],
    queryFn: async ({ pageParam }) =>
      normPage(
        await api.get<CursorPage<SentenceSpans>>(`/layers/${layerId}/spans`, {
          document_id: docId ?? undefined,
          cursor: pageParam ?? undefined,
          page_size: SPAN_PAGE,
          status,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: !!docId,
    staleTime: Infinity,
  });
}

/**
 * Sentences around `idx` (paragraph view): the page after cursor `<doc>:<idx-3>`, five sentences.
 * Assumes the P3 cursor convention (items after the cursor sentence).
 */
export function useSpanWindow(layerId: string, docId: string | null, idx: number | null, enabled: boolean) {
  return useQuery({
    queryKey: ["span-window", layerId, docId, idx],
    queryFn: async () =>
      normPage(
        await api.get<CursorPage<SentenceSpans>>(`/layers/${layerId}/spans`, {
          document_id: docId ?? undefined,
          cursor: idx != null && idx >= 3 ? `${docId}:${idx - 3}` : undefined,
          page_size: idx != null && idx < 3 ? idx + 3 : 5,
          status: "all",
        }),
      ),
    enabled: enabled && !!docId && idx != null,
    staleTime: Infinity,
  });
}

/** One sentence's spans (KWIC highlight): cursor before it, page size 1; null when the sentence is not in the layer. */
export async function fetchSentenceSpans(layerId: string, docId: string, idx: number): Promise<SentenceSpans | null> {
  const page = await api.get<CursorPage<SentenceSpans>>(`/layers/${layerId}/spans`, {
    document_id: docId,
    sentence_index: idx,
    cursor: idx > 0 ? `${docId}:${idx - 1}` : undefined,
    page_size: 1,
    status: "all",
  });
  const s = page.items.find((x) => x.document_id === docId && x.sentence_index === idx);
  return s ? normSentence(s) : null;
}

/** A sentence opened by link (?s=) that the loaded list does not contain. */
export function useSpanSentence(layerId: string, docId: string | null, idx: number | null, enabled: boolean) {
  return useQuery({
    queryKey: ["span-one", layerId, docId, idx],
    queryFn: () => fetchSentenceSpans(layerId, docId!, idx!),
    enabled: enabled && !!docId && idx != null,
    staleTime: Infinity,
  });
}

type SentFn =(s: SentenceSpans) => SentenceSpans;

/** Apply `fn` to one sentence wherever it is cached (sentence lists and paragraph windows of the list layer). */
function useSentencePatcher(listLayerId: string) {
  const qc = useQueryClient();
  return (docId: string, idx: number, fn: SentFn) => {
    const hit = (s: SentenceSpans) => (s.document_id === docId && s.sentence_index === idx ? fn(s) : s);
    qc.setQueriesData<InfiniteData<CursorPage<SentenceSpans>>>({ queryKey: ["span-sentences", listLayerId] }, (d) =>
      d ? { ...d, pages: d.pages.map((p) => ({ ...p, items: p.items.map(hit) })) } : d,
    );
    qc.setQueriesData<CursorPage<SentenceSpans>>({ queryKey: ["span-window", listLayerId] }, (d) => (d ? { ...d, items: d.items.map(hit) } : d));
    qc.setQueriesData<SentenceSpans | null>({ queryKey: ["span-one", listLayerId] }, (d) => (d ? hit(d) : d));
  };
}

function useRefresh(layerIds: (string | null | undefined)[], projectId: string) {
  const qc = useQueryClient();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  return () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      qc.invalidateQueries({ queryKey: ["layers", projectId] });
      for (const id of layerIds) {
        if (!id) continue;
        qc.invalidateQueries({ queryKey: ["layer-docs", id] });
        qc.invalidateQueries({ queryKey: ["layer-stats", id] });
        qc.invalidateQueries({ queryKey: ["agreement", id] });
      }
    }, 800);
  };
}

/**
 * Span and relation actions. Spans live on the span layer, relations on the relation layer; the sentence list
 * belongs to the layer being reviewed. Status and label changes show at once; failures reload and show the API error.
 */
export function useSpanActions(opts: { listLayerId: string; spanLayerId: string; relationLayerId: string | null; projectId: string }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const patch = useSentencePatcher(opts.listLayerId);
  const refresh = useRefresh([opts.listLayerId, opts.spanLayerId, opts.relationLayerId], opts.projectId);

  function fail(e: unknown) {
    message.error(errorText(e));
    qc.invalidateQueries({ queryKey: ["span-sentences", opts.listLayerId] });
    qc.invalidateQueries({ queryKey: ["span-window", opts.listLayerId] });
  }
  const putSpan = (s: SentenceSpans, span: Span) =>
    patch(s.document_id, s.sentence_index, (x) => ({ ...x, spans: x.spans.some((y) => y.id === span.id) ? x.spans.map((y) => (y.id === span.id ? span : y)) : [...x.spans, span] }));
  const putRel = (s: SentenceSpans, rel: Relation) =>
    patch(s.document_id, s.sentence_index, (x) => ({ ...x, relations: x.relations.some((y) => y.id === rel.id) ? x.relations.map((y) => (y.id === rel.id ? rel : y)) : [...x.relations, rel] }));

  async function createSpan(s: SentenceSpans, start_cp: number, end_cp: number, label: string): Promise<Span | null> {
    try {
      const span = normSpan(await api.post<Span>(`/layers/${opts.spanLayerId}/spans`, { document_id: s.document_id, start_cp, end_cp, label }));
      putSpan(s, span);
      refresh();
      return span;
    } catch (e) {
      fail(e);
      return null;
    }
  }

  async function patchSpan(s: SentenceSpans, span: Span, request: SpanPatch): Promise<boolean> {
    const body = effectiveSpanPatch(span, request);
    if (!body) return true;
    putSpan(s, patchedSpan(span, body));
    try {
      putSpan(s, normSpan(await api.patch<Span>(`/layers/${opts.spanLayerId}/spans/${span.id}`, body)));
      refresh();
      return true;
    } catch (e) {
      fail(e);
      return false;
    }
  }

  async function deleteSpan(s: SentenceSpans, span: Span): Promise<boolean> {
    try {
      await api.del(`/layers/${opts.spanLayerId}/spans/${span.id}`);
      patch(s.document_id, s.sentence_index, (x) => ({
        ...x,
        spans: x.spans.filter((y) => y.id !== span.id),
        relations: x.relations.filter((r) => r.from_span_id !== span.id && r.to_span_id !== span.id),
      }));
      refresh();
      return true;
    } catch (e) {
      fail(e);
      return false;
    }
  }

  async function createRelation(s: SentenceSpans, from: string, to: string, label: string): Promise<Relation | null> {
    if (!opts.relationLayerId) return null;
    try {
      const rel = normRel(await api.post<Relation>(`/layers/${opts.relationLayerId}/relations`, { from_span_id: apiId(from), to_span_id: apiId(to), label }));
      putRel(s, rel);
      refresh();
      return rel;
    } catch (e) {
      fail(e);
      return null;
    }
  }

  async function patchRelation(s: SentenceSpans, rel: Relation, body: { action: "confirm" | "modify" | "reject"; label?: string }): Promise<boolean> {
    if (!opts.relationLayerId) return false;
    putRel(s, { ...rel, status: body.action === "confirm" ? "confirmed" : body.action === "reject" ? "rejected" : "modified", label: body.label ?? rel.label });
    try {
      putRel(s, normRel(await api.patch<Relation>(`/layers/${opts.relationLayerId}/relations/${rel.id}`, body)));
      refresh();
      return true;
    } catch (e) {
      fail(e);
      return false;
    }
  }

  /**
   * Shift+Enter: the user's suggestions in the sentence → confirmed (spans of a span layer starting in it, or the
   * relations of a relation layer) and the sentence counts as reviewed; the server's sentence replaces the cache.
   */
  async function confirmSentence(s: SentenceSpans, kind: "span" | "relation", keep: (x: { annotator_id: string | null }) => boolean): Promise<boolean> {
    const done = <T extends { status: string; annotator_id: string | null }>(x: T): T => (x.status === "suggested" && keep(x) ? { ...x, status: "confirmed" } : x);
    patch(s.document_id, s.sentence_index, (x) =>
      kind === "span" ? { ...x, spans: x.spans.map((y) => (y.start_cp >= x.start_cp ? done(y) : y)) } : { ...x, relations: x.relations.map(done) },
    );
    try {
      const r = normSentence(await api.post<SentenceSpans>(`/layers/${opts.listLayerId}/sentences/${s.document_id}/${s.sentence_index}/confirm`, {}));
      patch(s.document_id, s.sentence_index, (x) => ({ ...x, spans: r.spans, relations: kind === "relation" ? r.relations : x.relations, done: r.done ?? true }));
      refresh();
      return true;
    } catch (e) {
      fail(e);
      return false;
    }
  }

  return { createSpan, patchSpan, deleteSpan, createRelation, patchRelation, confirmSentence };
}

/* ---------- alignment ---------- */

export function useAlignPairs(layerId: string, docId: string | null) {
  return useInfiniteQuery({
    queryKey: ["align-pairs", layerId, docId],
    queryFn: ({ pageParam }) =>
      api.get<CursorPage<SentencePair>>(`/layers/${layerId}/alignments`, { src_document_id: docId ?? undefined, cursor: pageParam ?? undefined, page_size: SPAN_PAGE }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: !!docId,
    staleTime: Infinity,
  });
}

/** Pairs of one source sentence (cursor before it, page size 1); [] when the sentence is not in the layer. */
export async function fetchSentencePairs(layerId: string, docId: string, idx: number): Promise<SentencePair[]> {
  const page = await api.get<CursorPage<SentencePair>>(`/layers/${layerId}/alignments`, {
    src_document_id: docId,
    cursor: idx > 0 ? `${docId}:${idx - 1}` : undefined,
    page_size: 1,
  });
  return page.items.filter((p) => p.src.document_id === docId && p.src.sentence_index === idx);
}

/** A source sentence opened by link (?s=) that the loaded pair list does not contain. */
export function useAlignPair(layerId: string, docId: string | null, idx: number | null, enabled: boolean) {
  return useQuery({
    queryKey: ["align-one", layerId, docId, idx],
    queryFn: () => fetchSentencePairs(layerId, docId!, idx!),
    enabled: enabled && !!docId && idx != null,
    staleTime: Infinity,
  });
}

export function useAlignActions(layerId: string, projectId: string) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const refresh = useRefresh([layerId], projectId);

  /** A pair is one source sentence with one target (or none); a source sentence can have several pairs. */
  const same = (a: SentencePair, b: SentencePair) =>
    a.src.document_id === b.src.document_id &&
    a.src.sentence_index === b.src.sentence_index &&
    (a.tgt?.document_id ?? null) === (b.tgt?.document_id ?? null) &&
    (a.tgt?.sentence_index ?? null) === (b.tgt?.sentence_index ?? null);
  function put(p: SentencePair, fn: (p: SentencePair) => SentencePair) {
    qc.setQueriesData<InfiniteData<CursorPage<SentencePair>>>({ queryKey: ["align-pairs", layerId, p.src.document_id] }, (d) =>
      d ? { ...d, pages: d.pages.map((pg) => ({ ...pg, items: pg.items.map((x) => (same(x, p) ? fn(x) : x)) })) } : d,
    );
    qc.setQueriesData<SentencePair[]>({ queryKey: ["align-one", layerId, p.src.document_id] }, (d) => (d ? d.map((x) => (same(x, p) ? fn(x) : x)) : d));
  }
  const setAlignments = (p: SentencePair, alignments: Alignment[]) => put(p, (x) => ({ ...x, alignments }));
  const replace = (p: SentencePair, id: Alignment["id"], a: Alignment) => put(p, (x) => ({ ...x, alignments: x.alignments.map((y) => (y.id === id ? a : y)) }));

  function fail(e: unknown) {
    message.error(errorText(e));
    qc.invalidateQueries({ queryKey: ["align-pairs", layerId] });
    qc.invalidateQueries({ queryKey: ["align-one", layerId] });
  }

  async function patchOne(p: SentencePair, a: Alignment, request: AlignmentPatch): Promise<Alignment> {
    const body = effectiveAlignPatch(a, request, p.tgt?.sentence_index);
    if (!body) return a;
    const r = await api.patch<Alignment>(`/layers/${layerId}/alignments/${a.id}`, body);
    replace(p, a.id, r);
    return r;
  }

  /** New alignment for the pair's source sentence; the target defaults to the pair's target. */
  async function create(
    p: SentencePair,
    tmpId: string,
    body: { tgt_document_id?: string; tgt_sentence_index?: number; src_tokens?: number[]; tgt_tokens?: number[] },
  ): Promise<Alignment> {
    const r = await api.post<Alignment>(`/layers/${layerId}/alignments`, {
      src_document_id: p.src.document_id,
      src_sentence_index: p.src.sentence_index,
      tgt_document_id: body.tgt_document_id ?? p.tgt?.document_id,
      tgt_sentence_index: body.tgt_sentence_index ?? p.tgt?.sentence_index,
      ...(body.src_tokens ? { src_tokens: body.src_tokens, tgt_tokens: body.tgt_tokens } : {}),
    });
    put(p, (x) => ({ ...x, alignments: x.alignments.some((y) => y.id === tmpId) ? x.alignments.map((y) => (y.id === tmpId ? r : y)) : [...x.alignments, r] }));
    return r;
  }

  /** Run steps in order after an optimistic update; reload the pair list when one fails. */
  async function run(steps: (() => Promise<unknown>)[]): Promise<boolean> {
    try {
      for (const s of steps) await s();
      refresh();
      return true;
    } catch (e) {
      fail(e);
      return false;
    }
  }

  return { setAlignments, patchOne, create, run };
}

/* ---------- multi-annotator view ---------- */

/**
 * Whose annotations the editor shows on a multi-annotator layer: annotators see their own (the API filters);
 * owners and editors choose one annotator or everyone. Single-mode layers show everything.
 */
export function useAnnotatorView(layer: Layer, canManage: boolean, projectId: string) {
  const me = useMe();
  const members = useMembers(layer.mode === "multi" && canManage ? projectId : undefined);
  const multi = layer.mode === "multi";
  const myId = me.data?.id;
  const [pick, setPick] = useState<string | null | undefined>(undefined);
  const value = pick !== undefined ? pick : multi && myId && (layer.annotators ?? []).includes(myId) ? myId : null;
  const email = (id: string) => members.data?.items.find((m) => m.user_id === id)?.email ?? (id === myId ? (me.data?.email ?? id) : id.slice(0, 8));
  const options = multi && canManage ? [{ value: "", label: "全部标注者" }, ...(layer.annotators ?? []).map((id) => ({ value: id, label: email(id) }))] : [];
  const keep = useCallback((x: { annotator_id: string | null }) => !multi || !value || x.annotator_id == null || x.annotator_id === value, [multi, value]);
  return { multi, value, setValue: (v: string | null) => setPick(v), options, keep, email };
}

