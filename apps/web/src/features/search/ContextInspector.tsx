import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, type ContextResult, type EvidenceInput, type Hit, type Layer } from "../../api";
import { AlignGraph } from "../../components/annot/AlignGraph";
import { ErrorAlert, Skeleton } from "../../components/common";
import { PinButton } from "../../components/global/evidence";
import { Icon } from "../../components/Icon";
import { markTerms } from "../../components/results/Kwic";
import { useAlignPair } from "../annotate/spanData";
import { tokenForms } from "../annotate/spanModel";
import { fmtVersion, metadataText } from "../../lib/format";

function Sentence({ text, highlight, terms }: { text: string; highlight: [number, number] | null; terms: string[] }) {
  if (!highlight) return <>{markTerms(text, terms)}</>;
  // highlight offsets are code points; Array.from splits by code point
  const chars = Array.from(text);
  const [s, e] = highlight;
  return (
    <>
      {markTerms(chars.slice(0, s).join(""), terms)}
      <strong className="hit">{chars.slice(s, e).join("")}</strong>
      {markTerms(chars.slice(e).join(""), terms)}
    </>
  );
}

export function hitEvidence(hit: Hit, query: string, scope: EvidenceInput["ref"]["scope"], corpusName: string): EvidenceInput {
  return {
    kind: "hit",
    ref: { hit_id: hit.hit_id, document_id: hit.document_id, start_cp: hit.start_cp, end_cp: hit.end_cp, search_query: query, scope },
    text: `${hit.left}${hit.match}${hit.right}`.replace(/\s+/g, " ").trim(),
    source: `${hit.document_title} · ${corpusName}`,
  };
}

/** 双语对照 with word links from a word alignment layer of the hit's corpus; plain aligned text without one. */
function Bilingual({ hit, layer, projectId }: { hit: Hit; layer: Layer | null; projectId?: string }) {
  const pairs = useAlignPair(layer?.id ?? "", hit.document_id, hit.sentence_index, !!layer);
  const linked = (pairs.data ?? []).filter((p) => p.tgt && p.alignments.some((a) => a.level !== "sentence" && a.status !== "rejected"));
  if (!hit.aligned.length && !linked.length) return null;
  return (
    <div className="insp-body">
      <div className="row">
        <h2 className="sec-title grow">双语对照</h2>
        {layer && linked.length > 0 && projectId && (
          <Link className="btn xs" to={`/p/${projectId}/annotate?${new URLSearchParams({ layer: layer.id, doc: hit.document_id, s: String(hit.sentence_index) }).toString()}`}>
            <Icon name="external" size={14} />
            在标注中校对
          </Link>
        )}
      </div>
      <ErrorAlert error={pairs.error} />
      {linked.length > 0
        ? linked.map((p) => (
            <AlignGraph
              key={`${p.tgt!.document_id}:${p.tgt!.sentence_index}`}
              src={tokenForms(p.src.tokens)}
              tgt={tokenForms(p.tgt!.tokens)}
              links={p.alignments.filter((a) => a.level !== "sentence").map((a) => ({ key: String(a.id), src: a.src_tokens, tgt: a.tgt_tokens, status: a.status }))}
            />
          ))
        : hit.aligned.map((a, i) => (
            <p className="sm" key={i}>
              <span className="tag t-gray mono" style={{ marginRight: 6 }}>
                {a.language}
              </span>
              {a.text}
            </p>
          ))}
    </div>
  );
}

/** 360 px context inspector: neighbouring sentences, aligned text, document metadata, index version, pin. */
export default function ContextInspector({
  hit,
  terms,
  indexVersion,
  evidence,
  alignLayer = null,
  projectId,
  onClose,
}: {
  hit: Hit | null;
  terms: string[];
  indexVersion: string | number | null | undefined;
  evidence: EvidenceInput | null;
  /** Ready word alignment layer whose source is the hit's corpus. */
  alignLayer?: Layer | null;
  projectId?: string;
  onClose?: () => void;
}) {
  const [before, setBefore] = useState(1);
  const [after, setAfter] = useState(1);
  useEffect(() => {
    setBefore(1);
    setAfter(1);
  }, [hit?.hit_id]);
  const ctx = useQuery({
    queryKey: ["context", hit?.hit_id, before, after],
    queryFn: () =>
      api.get<ContextResult>("/search/context", {
        document_id: hit!.document_id,
        sentence_index: hit!.sentence_index,
        start_cp: hit!.start_cp,
        end_cp: hit!.end_cp,
        before,
        after,
      }),
    enabled: !!hit,
    placeholderData: keepPreviousData,
  });

  return (
    <aside className={`inspector ctx ${hit ? "" : "no-hit"}`} aria-label="上下文">
      <div className="card-head">
        <h2 className="sec-title grow">上下文</h2>
        {hit && (
          <span className="mono small muted ellipsis" style={{ maxWidth: 200 }}>
            句 {hit.sentence_index + 1} · {hit.start_cp}:{hit.end_cp}
          </span>
        )}
        {hit && onClose && (
          <button className="btn ghost icon xs" type="button" aria-label="关闭上下文" onClick={onClose}>
            <Icon name="x" size={14} />
          </button>
        )}
      </div>
      {!hit ? (
        <div className="empty sm">选择一行查看上下文</div>
      ) : (
        <>
          <div className="insp-body">
            <div className="row">
              <button className="btn s" type="button" onClick={() => setBefore((n) => Math.min(20, n + 1))}>
                前 1 句
              </button>
              <button className="btn s" type="button" onClick={() => setAfter((n) => Math.min(20, n + 1))}>
                后 1 句
              </button>
              <div className="grow" />
              <span className="small muted num">
                −{before} / +{after}
              </span>
            </div>
            <ErrorAlert error={ctx.error} />
            {ctx.isPending && <Skeleton rows={3} />}
            {ctx.data?.sentences.map((s) => (
              <p key={s.index} className={s.index === hit.sentence_index ? "cur" : "side-s"}>
                <Sentence text={s.text} highlight={s.index === hit.sentence_index ? s.highlight : null} terms={terms} />
              </p>
            ))}
          </div>
          <Bilingual hit={hit} layer={alignLayer} projectId={projectId} />
          <div className="insp-body">
            <dl className="kv">
              <dt>文档</dt>
              <dd>{hit.document_title}</dd>
              <dt>句序号</dt>
              <dd className="mono">{hit.sentence_index + 1}</dd>
              <dt>码点</dt>
              <dd className="mono">
                {hit.start_cp}–{hit.end_cp}
              </dd>
              {Object.entries(ctx.data?.document.metadata ?? hit.metadata).map(([k, v]) => (
                <span key={k} style={{ display: "contents" }}>
                  <dt>{k}</dt>
                  <dd className="mono">{typeof v === "object" ? metadataText(v as Record<string, unknown>) : String(v)}</dd>
                </span>
              ))}
              <dt>索引版本</dt>
              <dd className="mono">{fmtVersion(indexVersion)}</dd>
            </dl>
          </div>
          {evidence && (
            <div className="insp-foot">
              <span className="row sm">
                <PinButton input={evidence} />
                钉住到证据篮
              </span>
            </div>
          )}
        </>
      )}
    </aside>
  );
}
