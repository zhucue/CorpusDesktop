import { useMemo } from "react";
import { Link } from "react-router";
import type { Hit } from "../../api";
import { DepGraph } from "../../components/annot/DepGraph";
import { ErrorAlert } from "../../components/common";
import { Icon } from "../../components/Icon";
import { useSentence } from "../annotate/data";
import { graphOf, tokenViews } from "../annotate/model";

/** KWIC row expander: the hit's sentence from a dependency layer, hit tokens highlighted. */
export default function SentenceTree({ layerId, hit, projectId }: { layerId: string; hit: Hit; projectId: string }) {
  const q = useSentence(layerId, hit.document_id, hit.sentence_index);
  const graph = useMemo(() => (q.data ? graphOf(tokenViews(q.data, "dep")) : null), [q.data]);
  const highlight = useMemo(
    () => (q.data?.tokens ?? []).filter((t) => t.start_cp < hit.end_cp && t.end_cp > hit.start_cp).map((t) => t.index),
    [q.data, hit.start_cp, hit.end_cp],
  );
  if (q.error) return <ErrorAlert error={q.error} />;
  if (!graph) return <span className="skel h20" style={{ display: "block", width: "60%" }} />;
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
