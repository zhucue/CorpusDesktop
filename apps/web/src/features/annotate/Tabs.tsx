import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { api, type DiffResult, type Layer, type LayerStats } from "../../api";
import { DiffRows, diffCounts, type DiffKind } from "../../components/annot/DiffRows";
import { Empty, ErrorAlert, Progress, Skeleton } from "../../components/common";
import { Icon } from "../../components/Icon";
import { EChart, type ChartTokens } from "../../components/results/EChart";
import { fmt } from "../../lib/format";
import { hbarOption } from "../stats/StatChart";
import { rowSearchHref } from "../stats/StatTable";
import { Link } from "react-router";
import { useProjectId } from "../../lib/data";
import { diffTokens } from "./model";

const KIND_VIEW: [DiffKind, string, string][] = [
  ["changed", "改动", "var(--warning-solid)"],
  ["confirmed", "确认", "var(--success-solid)"],
  ["rejected", "拒绝", "var(--error-solid)"],
  ["pending", "待办", "var(--text-4)"],
];

/** 预标差异: GET /layers/{id}/diff for the current document; counts filter the sentence blocks. */
export function DiffTab({ layer, docId, onOpen }: { layer: Layer; docId: string | null; onOpen: (sentenceIndex: number) => void }) {
  const [onlyChanged, setOnlyChanged] = useState(true);
  const [filter, setFilter] = useState<DiffKind | "all">("all");
  const q = useQuery({
    queryKey: ["layer-diff", layer.id, docId, onlyChanged],
    queryFn: () => api.get<DiffResult>(`/layers/${layer.id}/diff`, { document_id: docId ?? undefined, only_changed: String(onlyChanged) }),
    enabled: !!docId,
  });
  const blocks = useMemo(
    () =>
      (q.data?.items ?? []).map((s) => {
        const toks = diffTokens(s, layer.kind);
        return { s, toks, c: diffCounts(toks) };
      }),
    [q.data, layer.kind],
  );
  const shown = filter === "all" ? blocks : blocks.filter((b) => b.c[filter] > 0);
  const counts = q.data?.counts;
  return (
    <section className="card" aria-label="预标差异">
      <div className="card-head">
        <h2>预标 / 人工</h2>
        <span className="mono small muted">{layer.source_model}</span>
        <div className="grow" />
        <span className="pos-toggle">
          <button className="switch" type="button" role="switch" aria-checked={onlyChanged} aria-label="只看改动" onClick={() => setOnlyChanged((v) => !v)} />
          只看改动
        </span>
      </div>
      <div className="card-pad" style={{ paddingBottom: 6 }}>
        <div className="diff-sum" role="group" aria-label="差异计数">
          <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>
            全部 <b>{fmt(blocks.length)}</b> 句
          </button>
          {KIND_VIEW.map(([k, label, color]) => (
            <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(filter === k ? "all" : k)} data-kind={k}>
              <span className="dot" style={{ color }} />
              {label} <b>{counts ? fmt(counts[k]) : "–"}</b>
            </button>
          ))}
        </div>
      </div>
      <ErrorAlert error={q.error} style={{ margin: 16 }} />
      {q.isPending && docId ? (
        <Skeleton rows={4} />
      ) : shown.length === 0 && !q.error ? (
        <Empty icon="compare" text={onlyChanged ? "本文档没有改动" : "没有句子"} />
      ) : (
        <div className="diff-list">
          {shown.map(({ s, toks, c }, i) => (
            <div className="diff-blk" key={s.sentence_index} style={{ ["--i" as string]: Math.min(i, 12) }}>
              <div className="row">
                <span className="mono small muted grow">句 {s.sentence_index + 1}</span>
                {c.changed > 0 && <span className="tag t-warn">{c.changed} 处改动</span>}
                {c.rejected > 0 && <span className="tag t-err">{c.rejected} 处拒绝</span>}
                {c.pending > 0 && <span className="tag t-gray">{c.pending} 处待办</span>}
                {c.changed + c.rejected + c.pending === 0 && <span className="tag t-ok">全部确认</span>}
                <button className="btn xs ghost" type="button" onClick={() => onOpen(s.sentence_index)}>
                  <Icon name="edit" size={14} />
                  编辑
                </button>
              </div>
              <DiffRows tokens={toks} modelSource={layer.source_model} colorPos={layer.kind === "pos"} />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

const UNIT_NAMES: Record<Layer["kind"], string> = { pos: "token", dep: "token", span: "片段", relation: "关系", alignment: "对齐" };

/** "回到例句" for a label row: the search counts the same layer ({pos=}, {dep=}, [标签] with layers=…); null for other kinds. */
export function labelSearchHref(projectId: string, layer: Pick<Layer, "id" | "kind" | "corpus_id">, label: string): string | null {
  if (!/^[\p{L}\p{N}_.-]+$/u.test(label)) return null;
  const scope = { corpus_id: layer.corpus_id };
  if (layer.kind === "span") return rowSearchHref(projectId, `[${label}]`, scope, { span: layer.id });
  if (layer.kind === "pos") return rowSearchHref(projectId, `{pos=${label}}`, scope, { pos: layer.id });
  if (layer.kind === "dep") return rowSearchHref(projectId, `{dep=${label}}`, scope, { dep: layer.id });
  return null;
}

/** 统计: label frequencies (effective values) and per-document progress. */
export function StatsTab({ layer }: { layer: Layer }) {
  const projectId = useProjectId();
  const q = useQuery({ queryKey: ["layer-stats", layer.id], queryFn: () => api.get<LayerStats>(`/layers/${layer.id}/stats`) });
  const labels = useMemo(() => [...(q.data?.labels ?? [])].sort((a, b) => b.count - a.count), [q.data]);
  const top = useMemo(() => labels.slice(0, 20), [labels]);
  const build = useCallback(
    (t: ChartTokens) =>
      hbarOption(
        t,
        top.map((l) => l.label),
        top.map((l) => l.count),
        (i) => fmt(top[i].count),
      ),
    [top],
  );
  if (q.error) return <ErrorAlert error={q.error} />;
  if (!q.data) return <Skeleton rows={6} />;
  const p = q.data.progress;
  return (
    <div className="col gap-20">
      <section className="grid-4" aria-label="进度">
        {(
          [
            [UNIT_NAMES[layer.kind], p.total],
            ["已确认", p.confirmed],
            ["已修改", p.modified],
            [layer.kind === "dep" ? "待办" : "已拒绝", layer.kind === "dep" ? p.suggested : p.rejected],
          ] as [string, number][]
        ).map(([label, v]) => (
          <div className="card card-pad" key={label}>
            <div className="stat-label">{label}</div>
            <div className="count">
              <span className="n">{fmt(v)}</span>
            </div>
          </div>
        ))}
      </section>
      <div className="annot-stats">
        <section className="card" aria-label="标签频次">
          <div className="card-head">
            <h2>标签频次</h2>
            <span className="small muted">有效标注</span>
          </div>
          {labels.length === 0 ? (
            <Empty icon="tags" text="没有标签数据" />
          ) : (
            <div className="stat-scroll">
              <table className="tbl stat-tbl">
                <thead>
                  <tr>
                    <th>标签</th>
                    <th className="r">频次</th>
                    <th className="r">已确认</th>
                    <th className="r">已修改</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {labels.map((l) => (
                    <tr key={l.label}>
                      <td className="mono">{l.label}</td>
                      <td className="r num">{fmt(l.count)}</td>
                      <td className="r num">{fmt(l.confirmed)}</td>
                      <td className="r num">{fmt(l.modified)}</td>
                      <td className="r">
                        {labelSearchHref(projectId, layer, l.label) && (
                          <Link className="back" to={labelSearchHref(projectId, layer, l.label)!}>
                            回到例句
                            <Icon name="right" size={14} />
                          </Link>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        {top.length > 0 && (
          <section className="card" aria-label="频次图">
            <div className="card-head">
              <h2>前 {top.length} 个标签</h2>
            </div>
            <div className="card-pad">
              <EChart build={build} height={Math.max(160, top.length * 28)} label="标签频次条形图" />
            </div>
          </section>
        )}
      </div>
      <section className="card" aria-label="文档进度">
        <div className="card-head">
          <h2>文档进度</h2>
          <span className="small muted">句</span>
        </div>
        {q.data.per_document.length === 0 ? (
          <Empty icon="folderopen" text="没有文档" />
        ) : (
          <table className="tbl">
            <tbody>
              {q.data.per_document.map((d) => {
                const total = d.sentences ?? (d.done ?? 0) + (d.pending ?? 0);
                return (
                  <tr key={d.document_id}>
                    <td className="ellipsis" style={{ maxWidth: 280 }}>
                      {d.title ?? d.document_id}
                    </td>
                    <td style={{ width: "40%" }}>
                      <Progress done={d.done ?? 0} total={total || null} state={total && d.done === total ? "succeeded" : undefined} thin />
                    </td>
                    <td className="r num" style={{ width: 110 }}>
                      {fmt(d.done ?? 0)} / {fmt(total)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
