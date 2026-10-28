import type { Corpus } from "../../api";
import { CorpusStatusTag } from "../../components/common";

export function StatusCell({ c }: { c: Corpus }) {
  const live = c.status === "ready" || c.status === "stale";
  return (
    <div className="state">
      <span className="row" style={{ gap: 4 }}>
        <CorpusStatusTag status={c.status} />
        {c.updating && (
          <span className="tag t-run">
            <span className="dot pulse" />
            更新中
          </span>
        )}
      </span>
      {c.status === "failed" && c.error && <span className="state-msg err-text">{c.error}</span>}
      {live && !c.updating && c.error && <span className="state-msg err-text">上次更新失败：{c.error}</span>}
      {c.status === "stale" && !c.updating && <span className="state-msg">文档已变更，需重建索引</span>}
    </div>
  );
}
