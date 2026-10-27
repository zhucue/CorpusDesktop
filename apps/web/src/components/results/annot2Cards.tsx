import { useContext, useMemo } from "react";
import { Link } from "react-router";
import type { AnnotStatus } from "../../api";
import { AlignGraph } from "../annot/AlignGraph";
import { SpanText, type FlowSpan } from "../annot/SpanText";
import { cpLength, labelColor } from "../annot/spans";
import { Icon } from "../Icon";
import { Card, ResultContext } from "./cards";

function annotateUrl(projectId: string, q: Record<string, string | number | undefined>) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== "") p.set(k, String(v));
  return `/p/${projectId}/annotate?${p.toString()}`;
}

/* ---------- SpanView (contracts/p5.md §四: start/end are code points in text; relation from/to index spans, 0-based) ---------- */
export interface SpanViewProps {
  document_id: string;
  sentence_index: number;
  text: string;
  spans: { start: number; end: number; label: string }[];
  relations: { from: number; to: number; label: string }[];
}

export function SpanViewCard(p: SpanViewProps) {
  const { projectId } = useContext(ResultContext);
  const text = typeof p.text === "string" ? p.text : "";
  const len = cpLength(text);
  // Props arrive partially while the answer streams: keep complete spans inside the text; indices stay aligned with p.spans.
  const spans = useMemo(() => {
    const raw = p.spans ?? [];
    const ok = (s: SpanViewProps["spans"][number]) =>
      !!s && typeof s.label === "string" && Number.isInteger(s.start) && Number.isInteger(s.end) && s.start >= 0 && s.end <= len && s.end > s.start;
    const order = [...new Set(raw.filter(ok).map((s) => s.label))];
    return raw.map((s, i): FlowSpan | null => (ok(s) ? { id: `s${i}`, start: s.start, end: s.end, label: s.label, status: "suggested", color: labelColor(s.label, order) } : null));
  }, [p.spans, len]);
  const relations = useMemo(
    () =>
      (p.relations ?? [])
        .filter((r) => r && typeof r.label === "string" && spans[r.from] && spans[r.to])
        .map((r, i) => ({ id: `r${i}`, from: spans[r.from]!.id, to: spans[r.to]!.id, label: r.label, status: "suggested" as AnnotStatus })),
    [p.relations, spans],
  );
  const shown = spans.filter((s): s is FlowSpan => !!s);
  const n = (p.sentence_index ?? 0) + 1;
  return (
    <Card
      component="SpanView"
      icon="pen"
      title="片段标注"
      meta={`句 ${n} · ${shown.length} 个片段`}
      pin={{ kind: "text", ref: { document_id: p.document_id }, text, source: `助手 · SpanView · 句 ${n}` }}
      foot={
        <Link className="btn xs" to={annotateUrl(projectId, { doc: p.document_id, s: p.sentence_index, kind: "span" })}>
          <Icon name="external" size={14} />
          在标注中打开
        </Link>
      }
    >
      <div className="ou-body">
        {text ? <SpanText pieces={[{ key: "t", cp: 0, text }]} spans={shown} relations={relations} className="sm-size" label={text} /> : <div className="empty sm">没有文本</div>}
      </div>
    </Card>
  );
}

/* ---------- AlignmentGraph (links: 1-based token numbers) ---------- */
export interface AlignmentGraphProps {
  src_tokens: string[];
  tgt_tokens: string[];
  links: { src: number[]; tgt: number[]; status?: AnnotStatus }[];
}

export function AlignmentGraphCard(p: AlignmentGraphProps) {
  const { projectId } = useContext(ResultContext);
  const src = (p.src_tokens ?? []).filter((t) => typeof t === "string");
  const tgt = (p.tgt_tokens ?? []).filter((t) => typeof t === "string");
  const links = (p.links ?? [])
    .filter((l) => l && Array.isArray(l.src) && Array.isArray(l.tgt))
    .map((l, i) => ({ key: String(i), src: l.src.filter((x) => x >= 1 && x <= src.length), tgt: l.tgt.filter((x) => x >= 1 && x <= tgt.length), status: l.status }));
  const sugg = links.filter((l) => l.status === "suggested").length;
  return (
    <Card
      component="AlignmentGraph"
      icon="align"
      title="词对齐"
      meta={`${links.length} 组`}
      right={sugg > 0 ? <span className="tag t-run">{sugg} 组建议</span> : undefined}
      pin={{ kind: "text", ref: {}, text: `${src.join(" ")} ↔ ${tgt.join(" ")}`, source: "助手 · AlignmentGraph" }}
      foot={
        <Link className="btn xs" to={annotateUrl(projectId, { kind: "alignment" })}>
          <Icon name="external" size={14} />
          在标注中打开
        </Link>
      }
    >
      <div className="ou-body">{src.length && tgt.length ? <AlignGraph src={src} tgt={tgt} links={links} /> : <div className="empty sm">没有词</div>}</div>
    </Card>
  );
}
