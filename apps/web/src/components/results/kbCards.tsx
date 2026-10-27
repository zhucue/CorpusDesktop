import { useContext } from "react";
import { Link } from "react-router";
import { knowledgeHref, locatorText } from "../../features/knowledge/data";
import { PinButton } from "../global/evidence";
import { Icon } from "../Icon";
import { Card, ResultContext } from "./cards";

/* ---------- TermCard ---------- */
export interface TermCardProps {
  term_id: string;
  term: string;
  translations: { language: string; text: string }[];
  definition: string;
  domain: string;
  examples: { text: string; source: string }[];
  status: string;
}

export function TermCardView(p: TermCardProps) {
  const { projectId } = useContext(ResultContext);
  const tr = (p.translations ?? []).filter((t) => t && typeof t.text === "string");
  const ex = (p.examples ?? []).filter((x) => x && typeof x.text === "string");
  return (
    <Card
      component="TermCard"
      icon="term"
      title="术语"
      meta={p.domain || undefined}
      right={p.status === "confirmed" ? <span className="tag t-ok">已确认</span> : <span className="tag t-gray">草稿</span>}
      pin={{ kind: "text", ref: {}, text: `${p.term}${tr[0] ? ` / ${tr[0].text}` : ""}：${p.definition ?? ""}`, source: "助手 · TermCard" }}
      foot={
        p.term_id ? (
          <Link className="btn xs" to={knowledgeHref(projectId, { tab: "terms", term: p.term_id, tq: p.term })}>
            <Icon name="external" size={14} />
            打开术语
          </Link>
        ) : undefined
      }
    >
      <div className="ou-body col" style={{ gap: 8 }}>
        <div className="row wrap" style={{ gap: 6 }}>
          <span className="termc-name">{p.term}</span>
          {tr.map((t, i) => (
            <span key={i} className={`tag ${i ? "t-line" : "t-accent-line"}`} title={t.language}>
              {t.text}
            </span>
          ))}
        </div>
        {p.definition && <p className="sm" style={{ lineHeight: 1.7 }}>{p.definition}</p>}
        {ex.map((x, i) => (
          <div className="termc-ex" key={i}>
            {x.text}
            {x.source && <span className="mono small muted"> {x.source}</span>}
          </div>
        ))}
      </div>
    </Card>
  );
}

/* ---------- KbCitation ---------- */
export interface KbCitationProps {
  /** `locator` is display text ("第 3 页", "标题 › 小节"); an object locator is formatted too. */
  items: { chunk_id: string; document_id: string; title: string; locator: string | Record<string, unknown>; text: string }[];
}

export function KbCitationCard(p: KbCitationProps) {
  const { projectId } = useContext(ResultContext);
  const items = (p.items ?? []).filter((x) => x && typeof x.document_id === "string");
  return (
    <Card component="KbCitation" icon="book" title="知识库出处" right={`${items.length} 条`}>
      <div className="ou-body">
        {items.length === 0 && <div className="empty sm">没有出处</div>}
        {items.map((x, i) => {
          const loc = locatorText(x.locator as never);
          return (
            <div className="kbc" key={x.chunk_id || i}>
              <span className="cite">{i + 1}</span>
              <div style={{ minWidth: 0 }}>
                <b style={{ fontWeight: 600 }}>{x.title}</b>
                {loc && <span className="mono small muted"> · {loc}</span>}
              </div>
              <span className="row" style={{ gap: 2 }}>
                <Link className="btn xs" to={knowledgeHref(projectId, { doc: x.document_id, chunk: x.chunk_id })}>
                  <Icon name="external" size={14} />
                  打开文档位置
                </Link>
                <PinButton input={{ kind: "text", ref: {}, text: x.text ?? "", source: [x.title, loc].filter(Boolean).join(" · ") }} />
              </span>
              {x.text && <div className="kbc-text">{x.text}</div>}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
