import { useMemo } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api, type Hit } from "../../api";
import { DepGraph } from "../../components/annot/DepGraph";
import type { GraphArc, GraphToken } from "../../components/annot/geometry";
import { ErrorAlert } from "../../components/common";
import { Icon } from "../../components/Icon";
import { useSentence } from "../annotate/data";
import { graphOf, tokenViews, uposOf } from "../annotate/model";

/** GET /corpora/{id}/documents/{doc}/sentences/{n}: the stored sentence with its system (imported) tokens. */
export interface CorpusSentence {
  document_id: string;
  sentence_index: number;
  text: string;
  start_cp: number;
  end_cp: number;
  tokens: { index: number; form: string; start_cp: number; end_cp: number; pos: string | null; lemma: string | null; head: number | null; deprel: string | null }[];
}

/** Native dependencies (CoNLL-U head / deprel from import) as a graph; read-only, so every arc is solid. */
export function nativeGraph(s: CorpusSentence): { tokens: GraphToken[]; arcs: GraphArc[] } {
  return {
    tokens: s.tokens.map((t) => ({ index: t.index, form: t.form, pos: uposOf(t.pos) })),
    arcs: s.tokens.filter((t) => t.head != null).map((t) => ({ dep: t.index, head: t.head!, label: t.deprel ?? "" })),
  };
}

/** Tokens overlapping the hit (document code points). */
export function hitTokens(tokens: { index: number; start_cp: number; end_cp: number }[], hit: Pick<Hit, "start_cp" | "end_cp">): number[] {
  return tokens.filter((t) => t.start_cp < hit.end_cp && t.end_cp > hit.start_cp).map((t) => t.index);
}

/**
 * KWIC row expander: the hit's sentence from a dependency layer, hit tokens highlighted.
 * With a POS layer selected, the tags under the words come from that layer (effective value) instead of system tags.
 * Without a layer (corpusId given), the corpus's own dependencies from import are shown read-only.
 */
export default function SentenceTree({
  layerId,
  corpusId,
  posLayerId,
  hit,
  projectId,
}: {
  layerId: string | null;
  corpusId?: string;
  posLayerId?: string | null;
  hit: Hit;
  projectId: string;
}) {
  if (!layerId) return corpusId ? <NativeTree corpusId={corpusId} hit={hit} /> : null;
  return <LayerTree layerId={layerId} posLayerId={posLayerId} hit={hit} projectId={projectId} />;
}

function NativeTree({ corpusId, hit }: { corpusId: string; hit: Hit }) {
  const q = useQuery({
    queryKey: ["corpus-sentence", corpusId, hit.document_id, hit.sentence_index],
    queryFn: () => api.get<CorpusSentence>(`/corpora/${corpusId}/documents/${hit.document_id}/sentences/${hit.sentence_index}`),
    staleTime: 5 * 60 * 1000,
  });
  const graph = useMemo(() => (q.data ? nativeGraph(q.data) : null), [q.data]);
  const highlight = useMemo(() => hitTokens(q.data?.tokens ?? [], hit), [q.data, hit]);
  if (q.error) return <ErrorAlert error={q.error} />;
  if (!graph) return <span className="skel h20" style={{ display: "block", width: "60%" }} />;
  if (!graph.arcs.length) return <div className="kwic-tree">该句无依存标注</div>;
  return (
    <div className="kwic-tree">
      <div className="depwrap left">
        <DepGraph tokens={graph.tokens} arcs={graph.arcs} highlight={highlight} />
      </div>
    </div>
  );
}

function LayerTree({ layerId, posLayerId, hit, projectId }: { layerId: string; posLayerId?: string | null; hit: Hit; projectId: string }) {
  const q = useSentence(layerId, hit.document_id, hit.sentence_index);
  const pos = useSentence(posLayerId && posLayerId !== layerId ? posLayerId : undefined, hit.document_id, hit.sentence_index);
  const graph = useMemo(() => {
    if (!q.data) return null;
    const g = graphOf(tokenViews(q.data, "dep"));
    if (!pos.data) return g;
    const tags = new Map(tokenViews(pos.data, "pos").map((v) => [v.index, v.status === "rejected" ? null : v.label]));
    return { ...g, tokens: g.tokens.map((t) => ({ ...t, pos: tags.get(t.index) ?? t.pos })) };
  }, [q.data, pos.data]);
  const highlight = useMemo(() => hitTokens(q.data?.tokens ?? [], hit), [q.data, hit]);
  if (q.error) return <ErrorAlert error={q.error} />;
  // The POS layer only relabels: wait for it briefly, fall back to system tags if it fails.
  if (!graph || (posLayerId && posLayerId !== layerId && pos.isPending && !pos.error))
    return <span className="skel h20" style={{ display: "block", width: "60%" }} />;
  return (
    <div className="kwic-tree">
      <div className="depwrap left">
        <DepGraph tokens={graph.tokens} arcs={graph.arcs} highlight={highlight} />
      </div>
      <Link
        className="btn xs"
        to={`/p/${projectId}/annotate?${new URLSearchParams({ layer: layerId, doc: hit.document_id, s: String(hit.sentence_index) }).toString()}`}
      >
        <Icon name="external" size={14} />
        在标注中打开
      </Link>
    </div>
  );
}
