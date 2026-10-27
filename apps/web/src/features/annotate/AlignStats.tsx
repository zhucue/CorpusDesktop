import { useMutation } from "@tanstack/react-query";
import { Select } from "antd";
import { useState } from "react";
import { api, type AlignmentStats, type Layer } from "../../api";
import { ErrorAlert } from "../../components/common";
import { Icon } from "../../components/Icon";
import { fmt } from "../../lib/format";

const NAMES: [string, string][] = [
  ["pairs", "句对"],
  ["one_to_one", "一对一"],
  ["one_to_many", "一对多"],
  ["unaligned", "未对齐"],
  ["avg_links", "平均对齐组数"],
  ["avg_word_pairs", "平均词对数"],
];
const SIDES: Record<string, string> = { src: "源", tgt: "目标" };

/** Numeric fields of the alignment statistics (nested counts such as unaligned.src flattened), known names first. */
export function alignStatRows(r: AlignmentStats): [string, number][] {
  const out: [string, number][] = [];
  const add = (label: string, v: unknown) => {
    if (typeof v === "number") out.push([label, v]);
    else if (v && typeof v === "object" && !Array.isArray(v))
      for (const [k, x] of Object.entries(v)) if (typeof x === "number") out.push([`${label}（${SIDES[k] ?? k}）`, x]);
  };
  for (const [k, label] of NAMES) add(label, r[k]);
  for (const [k, v] of Object.entries(r)) if (!NAMES.some(([n]) => n === k)) add(k, v);
  return out;
}

/** 对齐统计: POST /stats/alignment {layer_id} (synchronous). */
export function AlignmentStatsCard({ layers, initial }: { projectId?: string; layers: Layer[]; initial?: string }) {
  const [layerId, setLayerId] = useState<string | undefined>(initial ?? layers[0]?.id);
  const run = useMutation({ mutationFn: (id: string) => api.post<AlignmentStats>("/stats/alignment", { layer_id: id }) });
  const busy = run.isPending;
  const rows = run.data && run.variables === layerId ? alignStatRows(run.data) : [];
  return (
    <section className="card" aria-label="对齐统计">
      <div className="card-head">
        <h2>对齐统计</h2>
        <div className="grow" />
        {layers.length > 1 && (
          <Select size="small" style={{ width: 200 }} aria-label="对齐层" value={layerId} onChange={setLayerId} options={layers.map((l) => ({ value: l.id, label: l.name }))} />
        )}
        <button className="btn s" type="button" disabled={!layerId || busy} onClick={() => layerId && run.mutate(layerId)}>
          {busy ? <span className="spin" /> : <Icon name="play" size={14} />}
          计算
        </button>
      </div>
      <ErrorAlert error={run.error} style={{ margin: 16 }} />
      {rows.length > 0 && (
        <div className="card-pad align-stats" data-testid="align-stats">
          {rows.map(([label, v]) => (
            <div key={label}>
              <div className="stat-label">{label}</div>
              <div className="count">
                <span className="n">{Number.isInteger(v) ? fmt(v) : v.toFixed(2)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
