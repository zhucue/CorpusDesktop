import { useInfiniteQuery, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { App } from "antd";
import { useRef } from "react";
import {
  api,
  errorText,
  type Annotation,
  type AnnotationInput,
  type CursorPage,
  type LabelSet,
  type Layer,
  type LayerDocument,
  type LayerKind,
  type SentenceAnnot,
} from "../../api";
import { listOf } from "../../lib/data";
import { annotationMap, applyAction, confirmAll, restoreToken, withAnnotation } from "./model";

export { listOf };

export function useLayers(projectId: string | undefined) {
  return useQuery({
    queryKey: ["layers", projectId],
    queryFn: async () => listOf(await api.get<Layer[] | { items: Layer[] }>(`/projects/${projectId}/layers`)),
    enabled: !!projectId,
    refetchInterval: (q) => (q.state.data?.some((l) => l.status === "preannotating" || l.status === "created") ? 2000 : false),
    meta: { background: true },
  });
}

/**
 * Whether the user may annotate on this layer: owner / editor / annotator role, and on a single-mode layer only its
 * creator or a listed annotator; on a multi-mode layer only the listed annotators (contracts/p5.md §七).
 */
export function canWriteLayer(layer: Pick<Layer, "mode" | "annotators" | "created_by">, userId: string | undefined, role: string | undefined): boolean {
  if (!userId || !(role === "owner" || role === "editor" || role === "annotator")) return false;
  const listed = layer.annotators ?? [];
  if (layer.mode === "multi") return listed.includes(userId);
  return layer.created_by === userId || listed.includes(userId);
}

/** Most recently updated ready layer of `kind` on the corpus. */
export function defaultLayer(layers: Layer[], corpusId: string | undefined, kind: LayerKind): Layer | null {
  if (!corpusId) return null;
  const list = layers.filter((l) => l.corpus_id === corpusId && l.kind === kind && l.status === "ready");
  list.sort((a, b) => (b.updated_at ?? b.created_at).localeCompare(a.updated_at ?? a.created_at));
  return list[0] ?? null;
}

export function useLabelSets(projectId: string | undefined) {
  return useQuery({
    queryKey: ["label-sets", projectId],
    queryFn: async () => listOf(await api.get<LabelSet[] | { items: LabelSet[] }>("/label-sets", { project_id: projectId })),
    enabled: !!projectId,
    staleTime: 5 * 60 * 1000,
  });
}

export function useLayerDocs(layerId: string | undefined) {
  return useQuery({
    queryKey: ["layer-docs", layerId],
    queryFn: async () => listOf(await api.get<LayerDocument[] | { items: LayerDocument[] }>(`/layers/${layerId}/documents`)),
    enabled: !!layerId,
    meta: { background: true },
  });
}

export const SENTENCE_PAGE = 20;

export function useSentenceList(layerId: string, docId: string | null, status: "pending" | "all") {
  return useInfiniteQuery({
    queryKey: ["annot-sentences", layerId, docId, status],
    queryFn: ({ pageParam }) =>
      api.get<CursorPage<SentenceAnnot>>(`/layers/${layerId}/sentences`, {
        document_id: docId ?? undefined,
        cursor: pageParam ?? undefined,
        page_size: SENTENCE_PAGE,
        status,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: !!docId,
    staleTime: Infinity,
  });
}

export const sentenceKey = (layerId: string, docId: string | null, idx: number | null) => ["annot-sentence", layerId, docId, idx];

export function useSentence(layerId: string | undefined, docId: string | null, idx: number | null, seed?: SentenceAnnot) {
  return useQuery({
    queryKey: sentenceKey(layerId ?? "", docId, idx),
    queryFn: () => api.get<SentenceAnnot>(`/layers/${layerId}/sentences/${docId}/${idx}`),
    enabled: !!layerId && !!docId && idx != null,
    initialData: seed,
    staleTime: Infinity,
  });
}

/**
 * Token and sentence actions. Each one updates the sentence (and its row in the sentence list) at once,
 * then replaces it with the server's answer, or restores the previous value and shows the API error.
 */
export function useAnnotActions(layer: { id: string; kind: LayerKind }, projectId: string) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function put(docId: string, idx: number, fn: (s: SentenceAnnot) => SentenceAnnot) {
    qc.setQueryData<SentenceAnnot>(sentenceKey(layer.id, docId, idx), (s) => (s ? fn(s) : s));
    qc.setQueriesData<InfiniteData<CursorPage<SentenceAnnot>>>({ queryKey: ["annot-sentences", layer.id, docId] }, (d) =>
      d
        ? { ...d, pages: d.pages.map((p) => ({ ...p, items: p.items.map((it) => (it.sentence_index === idx ? fn(it) : it)) })) }
        : d,
    );
  }

  function current(s: SentenceAnnot): SentenceAnnot {
    return qc.getQueryData<SentenceAnnot>(sentenceKey(layer.id, s.document_id, s.sentence_index)) ?? s;
  }

  // Counts (documents, layer progress, diff, stats) refresh shortly after a burst of edits.
  function refresh() {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      qc.invalidateQueries({ queryKey: ["layer-docs", layer.id] });
      qc.invalidateQueries({ queryKey: ["layers", projectId] });
      qc.invalidateQueries({ queryKey: ["layer-diff", layer.id] });
      qc.invalidateQueries({ queryKey: ["layer-stats", layer.id] });
    }, 800);
  }

  async function act(s: SentenceAnnot, input: Omit<AnnotationInput, "document_id" | "sentence_index">): Promise<boolean> {
    const full: AnnotationInput = { document_id: s.document_id, sentence_index: s.sentence_index, ...input };
    const prev = annotationMap(current(s)).get(full.token_index);
    put(s.document_id, s.sentence_index, (x) => applyAction(x, full));
    try {
      const a = await api.post<Annotation>(`/layers/${layer.id}/annotations`, full);
      put(s.document_id, s.sentence_index, (x) => withAnnotation(x, a));
      refresh();
      return true;
    } catch (e) {
      put(s.document_id, s.sentence_index, (x) => restoreToken(x, full.token_index, prev));
      message.error(errorText(e));
      return false;
    }
  }

  async function confirmSentence(s: SentenceAnnot): Promise<boolean> {
    const before = current(s);
    put(s.document_id, s.sentence_index, (x) => confirmAll(x, layer.kind));
    try {
      const r = await api.post<SentenceAnnot>(`/layers/${layer.id}/sentences/${s.document_id}/${s.sentence_index}/confirm`, {});
      put(s.document_id, s.sentence_index, () => r);
      refresh();
      return true;
    } catch (e) {
      put(s.document_id, s.sentence_index, () => before);
      message.error(errorText(e));
      return false;
    }
  }

  async function resetSentence(s: SentenceAnnot): Promise<boolean> {
    try {
      const r = await api.post<SentenceAnnot>(`/layers/${layer.id}/sentences/${s.document_id}/${s.sentence_index}/reset`, {});
      put(s.document_id, s.sentence_index, () => r);
      refresh();
      return true;
    } catch (e) {
      message.error(errorText(e));
      return false;
    }
  }

  return { act, confirmSentence, resetSentence };
}
