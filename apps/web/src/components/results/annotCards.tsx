import { useContext, useMemo } from "react";
import { Link } from "react-router";
import type { AnnotStatus } from "../../api";
import { DepGraph } from "../annot/DepGraph";
import { DiffRows, diffCounts } from "../annot/DiffRows";
import { Icon } from "../Icon";
import { Card, ResultContext } from "./cards";

function annotateUrl(projectId: string, q: Record<string, string | number | undefined>) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== "") p.set(k, String(v));
  return `/p/${projectId}/annotate?${p.toString()}`;
}

/* ---------- DependencyTree ---------- */
export interface DependencyTreeProps {
  document_id: string;
  sentence_index: number;
  tokens: { index: number; form: string; pos: string }[];
  arcs: { head: number; dep: number; label: string }[];
  highlight?: number[];
}

export function DependencyTreeCard(p: DependencyTreeProps) {
  const { projectId } = useContext(ResultContext);
  // Props arrive partially while the answer streams: keep only complete tokens and arcs between them.
  const tokens = useMemo(
    () => (p.tokens ?? []).filter((t) => t && typeof t.index === "number" && typeof t.form === "string").map((t) => ({ index: t.index, form: t.form, pos: typeof t.pos === "string" ? t.pos : "" })),
    [p.tokens],
  );
  const arcs = useMemo(() => {
    const ids = new Set(tokens.map((t) => t.index));
    return (p.arcs ?? [])
      .filter((a) => a && typeof a.label === "string" && ids.has(a.dep) && (a.head === 0 || ids.has(a.head)))
      .map((a) => ({ dep: a.dep, head: a.head, label: a.label }));
  }, [p.arcs, tokens]);
  const text = tokens.map((t) => t.form).join(" ");
  return (
    <Card
      component="DependencyTree"
      icon="tree"
      title="依存树"
      meta={`句 ${p.sentence_index}`}
      pin={{ kind: "text", ref: { document_id: p.document_id }, text, source: `助手 · DependencyTree · 句 ${p.sentence_index}` }}
      foot={
        <Link className="btn xs" to={annotateUrl(projectId, { doc: p.document_id, s: p.sentence_index })}>
          <Icon name="external" size={14} />
          在标注中打开
        </Link>
      }
    >
      <div className="ou-body depwrap left">
        {tokens.length ? <DepGraph tokens={tokens} arcs={arcs} highlight={p.highlight} /> : <div className="empty sm">没有词</div>}
      </div>
    </Card>
  );
}

/* ---------- AnnotationDiff ---------- */
export interface AnnotationDiffProps {
  layer_id: string;
  document_id: string;
  sentence_index: number;
  tokens: { form: string; model: string; human: string; status: AnnotStatus }[];
}

export function AnnotationDiffCard(p: AnnotationDiffProps) {
  const { projectId } = useContext(ResultContext);
  const tokens = (p.tokens ?? []).filter((t) => t && typeof t.form === "string");
  const c = diffCounts(tokens);
  return (
    <Card
      component="AnnotationDiff"
      icon="diff"
      title="预标差异"
      meta={`句 ${p.sentence_index}`}
      right={
        <span className="row" style={{ gap: 6 }}>
          {c.changed > 0 && <span className="tag t-warn">{c.changed} 处改动</span>}
          {c.rejected > 0 && <span className="tag t-err">{c.rejected} 处拒绝</span>}
          {c.changed + c.rejected === 0 && <span className="tag t-gray">无改动</span>}
        </span>
      }
      foot={
        <Link className="btn xs" to={annotateUrl(projectId, { layer: p.layer_id, doc: p.document_id, s: p.sentence_index })}>
          <Icon name="external" size={14} />
          在标注中打开
        </Link>
      }
    >
      <div className="ou-body">{tokens.length ? <DiffRows tokens={tokens} /> : <div className="empty sm">无差异</div>}</div>
    </Card>
  );
}
