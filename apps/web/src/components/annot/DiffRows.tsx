import type { AnnotStatus } from "../../api";
import { posCat } from "../../lib/pos";
import "./annot.css";

export interface DiffToken {
  form: string;
  model: string;
  human: string;
  status: AnnotStatus;
}

export type DiffKind = "changed" | "confirmed" | "rejected" | "pending";

export function diffKind(t: DiffToken): DiffKind {
  if (t.status === "rejected") return "rejected";
  if (t.status === "suggested") return "pending";
  if (t.status === "modified" && t.human !== t.model) return "changed";
  return "confirmed";
}

export function diffCounts(tokens: DiffToken[]): Record<DiffKind, number> {
  const c: Record<DiffKind, number> = { changed: 0, confirmed: 0, rejected: 0, pending: 0 };
  for (const t of tokens) c[diffKind(t)]++;
  return c;
}

/** Two-line comparison: model pre-annotation above, human result below; changed tokens highlighted. */
export function DiffRows({ tokens, modelSource, humanSource, colorPos }: { tokens: DiffToken[]; modelSource?: string; humanSource?: string; colorPos?: boolean }) {
  return (
    <div className="diff-rows">
      <div className="diff-line" data-row="model">
        <span className="dl-lab">预标</span>
        <span className="dl-src mono" title={modelSource}>
          {modelSource ?? ""}
        </span>
        <div className="toks">
          {tokens.map((t, i) => {
            const k = diffKind(t);
            return (
              <span key={i} className={`dtok ${k === "rejected" ? "rej" : ""}`}>
                <b>{t.form}</b>
                <span className="pos-tagchip" data-c={colorPos ? posCat(t.model) : 8}>
                  {t.model || "—"}
                </span>
              </span>
            );
          })}
        </div>
      </div>
      <div className="diff-line" data-row="human">
        <span className="dl-lab">人工</span>
        <span className="dl-src" title={humanSource}>
          {humanSource ?? ""}
        </span>
        <div className="toks">
          {tokens.map((t, i) => {
            const k = diffKind(t);
            const cls = k === "changed" ? "chg" : k === "rejected" ? "rej" : k === "pending" ? "pend" : "";
            return (
              <span key={i} className={`dtok ${cls}`} data-kind={k}>
                <b>{t.form}</b>
                <span className="pos-tagchip" data-c={colorPos && k !== "rejected" ? posCat(t.human || t.model) : 8}>
                  {k === "rejected" ? "—" : k === "pending" ? "待办" : t.human || "—"}
                </span>
              </span>
            );
          })}
        </div>
      </div>
    </div>
  );
}
