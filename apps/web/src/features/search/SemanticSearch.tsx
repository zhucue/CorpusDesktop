import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Corpus, type SearchScope } from "../../api";
import { Empty, ErrorAlert } from "../../components/common";
import { Icon } from "../../components/Icon";
import { KwicTable, type KwicRow } from "../../components/results/Kwic";
import { fmt } from "../../lib/format";
import ContextInspector, { hitEvidence } from "./ContextInspector";
import { SemanticIndexPanel } from "./SemanticIndexPanel";
import { SEMANTIC_MAX_TEXT, useSemanticIndex, type SemanticHit, type SemanticRequest, type SemanticResult } from "./semantic";

const TOP = 50;

/** Evidence of a semantic hit: the whole sentence; no query to go back to (the text is not a query). */
function semanticEvidence(hit: SemanticHit, scope: SearchScope, corpusName: string) {
  const ev = hitEvidence(hit, "", scope, corpusName);
  return { ...ev, ref: { ...ev.ref, search_query: undefined } };
}

/**
 * 语义检索 (contracts/p10.md §六): one sentence in, the most similar sentences of the scope out, with their cosine
 * similarity. Rows reuse the KWIC table (whole sentence as the hit), the context inspector and evidence pins.
 */
export default function SemanticSearch({ projectId, scope, corpus }: { projectId: string; scope: SearchScope | null; corpus: Corpus | null | undefined }) {
  const [text, setText] = useState("");
  const [req, setReq] = useState<SemanticRequest | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const index = useSemanticIndex(corpus?.id);
  const result = useQuery({
    queryKey: ["semantic-search", req],
    queryFn: () => api.post<SemanticResult>("/search/semantic", req),
    enabled: !!req,
    staleTime: Infinity,
    retry: false,
  });
  const ready = !!index.data?.searchable;
  const corpusName = corpus?.name ?? "";
  const rows: (KwicRow & { hit: SemanticHit })[] = (result.data?.items ?? []).map((h) => ({
    id: h.hit_id,
    left: h.left,
    match: h.match,
    right: h.right,
    source: h.document_title,
    locator: `句 ${h.sentence_index + 1} · 相似度 ${h.score.toFixed(2)}`,
    aligned: h.aligned,
    evidence: semanticEvidence(h, req!.scope, corpusName),
    hit: h,
  }));
  const selectedHit = rows.find((r) => r.id === selected)?.hit ?? null;
  const t = text.trim();

  function run() {
    if (!scope || !t || !ready) return;
    setReq({ scope, text: t, top: TOP });
    setSelected(null);
  }

  return (
    <>
      <section className="card query-card" aria-label="语义检索">
        <form
          className="row"
          style={{ gap: 10 }}
          onSubmit={(e) => {
            e.preventDefault();
            run();
          }}
        >
          <label htmlFor="sem-q" className="sr-only">
            句子
          </label>
          <input
            id="sem-q"
            className="query-input"
            value={text}
            maxLength={SEMANTIC_MAX_TEXT}
            onChange={(e) => setText(e.target.value)}
            autoComplete="off"
            placeholder="我喜欢读书"
          />
          <span className="small muted num">
            {Array.from(text).length}/{SEMANTIC_MAX_TEXT}
          </span>
          <button className="btn p lg" type="submit" disabled={!scope || !t || !ready || result.isFetching}>
            {result.isFetching ? <span className="spin" /> : <Icon name="search" />}
            检索
          </button>
        </form>
        {!scope && (
          <div className="alert info">
            <Icon name="info" size={14} />
            <span>先选择范围</span>
          </div>
        )}
        {corpus && <SemanticIndexPanel corpusId={corpus.id} projectId={projectId} />}
      </section>

      {(result.data || result.error || result.isFetching) && (
        <section className="results-row">
          <div className="card grow" style={{ display: "flex", flexDirection: "column" }}>
            <div className="card-head kwic-head">
              <h2 className="sec-title">相似句</h2>
              {result.data && <span className="small muted num">{fmt(result.data.items.length)} 句 · 按相似度排序</span>}
              {result.data?.status === "stale" && <span className="tag t-warn">语义索引已过期</span>}
            </div>
            <ErrorAlert error={result.error} style={{ margin: 16 }} />
            {result.isFetching && !result.data ? (
              <div className="col" style={{ padding: 16 }}>
                {Array.from({ length: 6 }, (_, i) => (
                  <span key={i} className="skel h20" />
                ))}
              </div>
            ) : result.data && result.data.items.length === 0 ? (
              <Empty icon="searchx" text="范围内没有相似句" />
            ) : (
              result.data && (
                <div className="kwic-scroll" style={{ opacity: result.isFetching ? 0.55 : 1 }}>
                  <KwicTable rows={rows} wrap selected={selected} onSelect={setSelected} />
                </div>
              )
            )}
          </div>
          <ContextInspector
            hit={selectedHit}
            terms={[]}
            evidence={selectedHit && req ? semanticEvidence(selectedHit, req.scope, corpusName) : null}
            projectId={projectId}
            parallel={!!corpus?.parallel}
            onClose={() => setSelected(null)}
          />
        </section>
      )}
    </>
  );
}
