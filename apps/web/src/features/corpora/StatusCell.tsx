import type { Corpus } from "../../api";
import { CorpusStatusTag } from "../../components/common";

export function StatusCell({ c }: { c: Corpus }) {
  return (
    <div className="state">
      <CorpusStatusTag status={c.status} />
      {c.status === "failed" && c.error && <span className="state-msg err-text">{c.error}</span>}
      {c.status === "stale" && <span className="state-msg">文档已变更，需重建索引</span>}
    </div>
  );
}
