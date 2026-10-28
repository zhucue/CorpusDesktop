import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api, type KbSearchHit, type KbSearchResult, type Term } from "../../api";
import { Empty, ErrorAlert } from "../../components/common";
import { PinButton } from "../../components/global/evidence";
import { Icon } from "../../components/Icon";
import { kbDocIcon } from "../../components/iconSets";
import { kindLabels, knowledgeHref, locatorText } from "./data";
import { Marked, queryWords, snippetParts } from "./highlight";

type Mode = "hybrid" | "vector" | "keyword";
const MODES: [Mode, string][] = [
  ["hybrid", "混合"],
  ["vector", "向量"],
  ["keyword", "关键词"],
];

function warningOf(w: KbSearchResult["warning"]): { code: string; message: string } | null {
  if (!w) return null;
  const code = typeof w === "string" ? w : w.code;
  const message = typeof w === "string" ? "" : (w.message ?? "");
  return { code, message: code === "EMBED_UNAVAILABLE" ? "向量模型未就绪，已改用关键词检索" : message || code };
}

const RELEVANCE: Record<NonNullable<KbSearchHit["relevance"]>, [string, string]> = {
  high: ["高", "t-ok"],
  medium: ["中", "t-info"],
  low: ["低", "t-gray"],
};

export function termLabel(t: Pick<Term, "term" | "translations">): string {
  const tr = t.translations?.[0]?.text;
  return tr ? `${t.term} / ${tr}` : t.term;
}

/** Result list: warning banner, terms row, numbered chunks with highlighted snippets. */
export function KbHits({ projectId, q, result }: { projectId: string; q: string; result: KbSearchResult }) {
  const navigate = useNavigate();
  const warn = warningOf(result.warning);
  const terms = result.terms ?? [];
  const items = result.items ?? [];
  const words = [...queryWords(q), ...terms.map((t) => t.term)];
  const [showLow, setShowLow] = useState(false);
  const low = items.filter((h) => h.relevance === "low");
  // low-relevance hits fold away unless they are all there is
  const shown = showLow || low.length === items.length ? items : items.filter((h) => h.relevance !== "low");
  return (
    <div className="col" style={{ gap: 10 }}>
      {warn && (
        <div className="alert warn" role="alert">
          <Icon name="alert" size={14} />
          <span>
            {warn.message}
            <span className="err-code">{warn.code}</span>
          </span>
        </div>
      )}
      {terms.length > 0 && (
        <div className="row wrap kb-terms-row" aria-label="匹配术语">
          <span className="label">术语</span>
          {terms.map((t) => (
            <button
              key={t.id}
              type="button"
              className="chip ui"
              onClick={() => navigate(knowledgeHref(projectId, { tab: "terms", term: t.id, tq: t.term }))}
            >
              {termLabel(t)}
              {t.status === "draft" && <span className="small muted">草稿</span>}
            </button>
          ))}
        </div>
      )}
      {items.length === 0 ? (
        <Empty icon="searchx" text="没有匹配的片段" />
      ) : (
        <div className="hits">
          {shown.map((h, i) => {
            const loc = locatorText(h.chunk.locator);
            return (
              <div className="kb-hit" key={h.chunk.id} style={{ ["--i" as string]: i }} data-testid="kb-hit">
                <span className="cite">{i + 1}</span>
                <div style={{ minWidth: 0 }}>
                  <div className="row">
                    <b style={{ fontWeight: 600 }}>{h.document.title}</b>
                    <span className="tag t-gray">
                      <Icon name={kbDocIcon(h.document.kind, h.document.source, h.document.title)} size={12} />
                      {kindLabels[h.document.kind] ?? h.document.kind}
                    </span>
                  </div>
                  {loc && <div className="src mono">{loc}</div>}
                  <p className="snippet">
                    <Marked parts={snippetParts(h.chunk.text, h.highlight, words)} />
                  </p>
                </div>
                <div className="score">
                  {h.relevance && (
                    <div className="sbar">
                      相关度
                      <span className={`tag ${RELEVANCE[h.relevance][1]}`}>{RELEVANCE[h.relevance][0]}</span>
                    </div>
                  )}
                  <div className="row" style={{ justifyContent: "flex-end", gap: 4 }}>
                    <button
                      className="btn xs"
                      type="button"
                      onClick={() => navigate(knowledgeHref(projectId, { doc: h.document.id, chunk: h.chunk.id }))}
                    >
                      <Icon name="external" size={14} />
                      打开文档位置
                    </button>
                    <PinButton
                      input={{
                        // evidence ref.document_id names a corpus document; a knowledge chunk is cited by its source text
                        kind: "text",
                        ref: {},
                        text: h.chunk.text,
                        source: [h.document.title, loc].filter(Boolean).join(" · "),
                      }}
                    />
                  </div>
                </div>
              </div>
            );
          })}
          {low.length > 0 && low.length < items.length && (
            <button className="btn s ghost" type="button" style={{ alignSelf: "flex-start" }} onClick={() => setShowLow((v) => !v)}>
              <Icon name={showLow ? "up" : "down"} size={14} />
              {showLow ? "收起低相关结果" : `另有 ${low.length} 条低相关结果`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function KbSearch({ projectId }: { projectId: string }) {
  const [q, setQ] = useState("");
  const [mode, setMode] = useState<Mode>("hybrid");
  const [req, setReq] = useState<{ q: string; mode: Mode } | null>(null);
  const search = useQuery({
    queryKey: ["kb-search", projectId, req],
    queryFn: () => api.post<KbSearchResult>(`/projects/${projectId}/kb/search`, { q: req!.q, mode: req!.mode, top_k: 8 }),
    enabled: !!req,
    staleTime: 60_000,
  });

  function run(m = mode) {
    const t = q.trim();
    if (t) setReq({ q: t, mode: m });
  }

  return (
    <section className="card card-pad col gap-12" aria-label="检索知识库">
      <form
        className="row"
        style={{ gap: 10 }}
        onSubmit={(e) => {
          e.preventDefault();
          run();
        }}
      >
        <label htmlFor="kq" className="sr-only">
          检索知识库
        </label>
        <input
          id="kq"
          data-slash
          className="input"
          style={{ height: 42, fontSize: 15 }}
          value={q}
          placeholder="检索文献、规范、笔记"
          onChange={(e) => setQ(e.target.value)}
        />
        <div className="seg-mini" role="tablist" aria-label="检索方式">
          {MODES.map(([v, l]) => (
            <button
              key={v}
              type="button"
              role="tab"
              aria-selected={mode === v}
              onClick={() => {
                setMode(v);
                if (req) run(v);
              }}
            >
              {l}
            </button>
          ))}
        </div>
        <button className="btn p" type="submit" style={{ height: 42 }} disabled={!q.trim()}>
          <Icon name="search" size={14} />
          检索
        </button>
      </form>
      <ErrorAlert error={search.error} />
      {search.isFetching && !search.data && (
        <div className="hits">
          {[0, 1, 2].map((i) => (
            <div className="kb-hit" key={i}>
              <span className="skel" style={{ width: 18, height: 18, borderRadius: 9 }} />
              <div className="col" style={{ gap: 8 }}>
                <span className="skel" style={{ width: "40%" }} />
                <span className="skel" style={{ width: "95%", height: 10 }} />
                <span className="skel" style={{ width: "80%", height: 10 }} />
              </div>
              <span className="skel" style={{ height: 8 }} />
            </div>
          ))}
        </div>
      )}
      {search.data && req && (
        <div style={{ opacity: search.isFetching ? 0.55 : 1, transition: "opacity 200ms" }}>
          <KbHits key={`${req.q}|${req.mode}`} projectId={projectId} q={req.q} result={search.data} />
        </div>
      )}
    </section>
  );
}
