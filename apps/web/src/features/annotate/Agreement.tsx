import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Input, Select } from "antd";
import { useState } from "react";
import { api, errorText, type Adjudication, type Agreement, type CursorPage, type Disagreement, type LabelDef, type Layer } from "../../api";
import { Empty, ErrorAlert, Skeleton } from "../../components/common";
import { fmt } from "../../lib/format";
import { fmtKappa, kappaBand } from "./spanModel";

export function useAgreement(layerId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["agreement", layerId],
    queryFn: () => api.get<Agreement>(`/layers/${layerId}/agreement`),
    enabled: !!layerId && enabled,
    staleTime: 30 * 1000,
    meta: { background: true },
  });
}

/** Mean pairwise κ (the layer-list gauge). */
export function meanKappa(a: Agreement | undefined): number | null {
  const ks = (a?.pairwise ?? []).map((p) => p.kappa).filter((k): k is number => typeof k === "number");
  return ks.length ? ks.reduce((x, y) => x + y, 0) / ks.length : null;
}

export function KappaGauge({ value, annotators }: { value: number | null; annotators: number }) {
  const band = kappaBand(value);
  const pct = value == null ? 0 : Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <span className={`gauge ${band.cls}`} title={annotators > 2 ? `Cohen's κ，${annotators} 名标注者两两平均` : "Cohen's κ"}>
      <svg viewBox="0 0 40 22" aria-hidden>
        <path className="bg" d="M4 20 A16 16 0 0 1 36 20" pathLength={100} />
        <path className="fg" d="M4 20 A16 16 0 0 1 36 20" pathLength={100} style={{ ["--v" as string]: pct }} />
      </svg>
      <span>
        <b className="num" style={{ fontWeight: 600, color: "var(--text)" }}>
          κ = {fmtKappa(value)}
        </b>{" "}
        {band.text}
      </span>
    </span>
  );
}

/** Annotator progress, pairwise κ matrix, α and per-label κ. */
export function AgreementView({ data }: { data: Agreement }) {
  const people = data.annotators;
  const name = (id: string) => people.find((p) => p.user_id === id)?.email ?? id.slice(0, 8);
  const cell = (a: string, b: string) => data.pairwise.find((p) => (p.a === a && p.b === b) || (p.a === b && p.b === a));
  const mean = meanKappa(data);
  return (
    <div className="col gap-20">
      <section className="grid-4" aria-label="一致性">
        <div className="card card-pad">
          <div className="stat-label">标注者</div>
          <div className="count">
            <span className="n">{fmt(people.length)}</span>
          </div>
        </div>
        <div className="card card-pad">
          <div className="stat-label">{people.length > 2 ? "κ 两两平均" : "Cohen's κ"}</div>
          <div className="count">
            <span className="n" data-testid="kappa-mean">
              {fmtKappa(mean)}
            </span>
          </div>
        </div>
        <div className="card card-pad">
          <div className="stat-label">Krippendorff's α</div>
          <div className="count">
            <span className="n" data-testid="alpha">
              {fmtKappa(data.alpha)}
            </span>
          </div>
        </div>
        {data.lenient ? (
          <div className="card card-pad">
            <div className="stat-label">重叠宽松 κ / α</div>
            <div className="count">
              <span className="n" data-testid="lenient">
                {fmtKappa(meanKappa({ ...data, pairwise: data.lenient.pairwise }))} / {fmtKappa(data.lenient.alpha)}
              </span>
            </div>
          </div>
        ) : (
          <div className="card card-pad">
            <div className="stat-label">比较单位</div>
            <div className="count">
              <span className="n">{fmt(Math.max(0, ...data.pairwise.map((p) => p.n)))}</span>
            </div>
          </div>
        )}
      </section>
      <div className="annot-stats">
        <section className="card" aria-label="两两一致性">
          <div className="card-head">
            <h2>两两 κ</h2>
            <span className="small muted">n = 共同完成的单位</span>
          </div>
          {people.length < 2 ? (
            <Empty icon="users" text="不足两名标注者" />
          ) : (
            <div className="stat-scroll">
              <table className="tbl kappa-tbl" data-testid="kappa-table">
                <thead>
                  <tr>
                    <th />
                    {people.map((p) => (
                      <th key={p.user_id} className="r ellipsis" title={p.email}>
                        {p.email}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {people.map((row) => (
                    <tr key={row.user_id}>
                      <th className="ellipsis" title={row.email} scope="row">
                        {row.email}
                      </th>
                      {people.map((col) => {
                        if (col.user_id === row.user_id)
                          return (
                            <td key={col.user_id} className="r muted">
                              —
                            </td>
                          );
                        const c = cell(row.user_id, col.user_id);
                        return (
                          <td key={col.user_id} className={`r num k-${kappaBand(c?.kappa).cls || "hi"}`} data-pair={`${row.user_id}:${col.user_id}`}>
                            {fmtKappa(c?.kappa)}
                            {c && <span className="small muted"> · {fmt(c.n)}</span>}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <section className="card" aria-label="标注者进度">
          <div className="card-head">
            <h2>标注者进度</h2>
          </div>
          <table className="tbl">
            <tbody>
              {people.map((p) => (
                <tr key={p.user_id}>
                  <td className="ellipsis" style={{ maxWidth: 200 }} title={p.email}>
                    {name(p.user_id)}
                  </td>
                  <td className="r num" style={{ width: 120 }}>
                    已完成 {fmt(p.done)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
      {data.per_label.length > 0 && (
        <section className="card" aria-label="按标签">
          <div className="card-head">
            <h2>按标签 κ</h2>
          </div>
          <table className="tbl">
            <tbody>
              {[...data.per_label]
                .sort((a, b) => (a.kappa ?? -2) - (b.kappa ?? -2))
                .map((l) => (
                  <tr key={l.label}>
                    <td className="mono">{l.label}</td>
                    <td className={`r num k-${kappaBand(l.kappa).cls || "hi"}`} style={{ width: 90 }}>
                      {fmtKappa(l.kappa)}
                    </td>
                    <td className="small muted" style={{ width: 110 }}>
                      {kappaBand(l.kappa).text}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

/** A disagreement value as text: labels, spans `text [label]`, alignment pairs. */
export function valueText(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.map(valueText).join("；");
  const o = v as Record<string, unknown>;
  if (Array.isArray(o.src_tokens) || Array.isArray(o.tgt_tokens)) return `${(o.src_tokens as number[] | undefined)?.join(",") ?? ""} → ${(o.tgt_tokens as number[] | undefined)?.join(",") ?? ""}`;
  if (typeof o.label === "string") {
    const where = typeof o.text === "string" ? o.text : o.start_cp != null ? `${o.start_cp}–${o.end_cp}` : "";
    return where ? `${where} [${o.label}]` : o.label;
  }
  if (o.status === "rejected") return "拒绝";
  return JSON.stringify(v);
}

const isAdjudicated = (d: Disagreement) => !!d.adjudicated;

function Adjudicate({ d, layerId, labels, canAdjudicate, email }: { d: Disagreement; layerId: string; labels: LabelDef[]; canAdjudicate: boolean; email: (id: string, fallback?: string) => string }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [custom, setCustom] = useState<string>("");
  const first = d.values.find((v) => v.value != null)?.value;
  const labelish = typeof first === "string" || (!!first && typeof first === "object" && typeof (first as { label?: unknown }).label === "string");
  const save = useMutation({
    mutationFn: (final: unknown) => api.post<Adjudication>(`/layers/${layerId}/adjudicate`, { target_kind: d.target_kind, target_key: d.target_key, final }),
    onSuccess: () => {
      message.success("已仲裁");
      qc.invalidateQueries({ queryKey: ["disagreements", layerId] });
      qc.invalidateQueries({ queryKey: ["agreement", layerId] });
    },
    onError: (e) => message.error(errorText(e)),
  });
  const final = d.final ?? (d.adjudicated && typeof d.adjudicated === "object" ? d.adjudicated.final : undefined);
  function customValue(): unknown {
    if (!custom) return undefined;
    if (typeof first === "string" || first == null) return custom;
    if (labelish) return { ...(first as object), label: custom };
    try {
      return JSON.parse(custom);
    } catch {
      return undefined;
    }
  }
  return (
    <div className="disagree" data-key={d.target_key}>
      <div className="row">
        <span className="mono small muted grow ellipsis">
          {d.sentence_index != null ? `句 ${d.sentence_index + 1}` : d.target_key}
          {d.text ? ` · ${d.text}` : ""}
        </span>
        <span className="tag t-gray">{d.target_kind}</span>
        {isAdjudicated(d) && (
          <span className="tag t-ok" data-testid="adjudicated">
            已仲裁
          </span>
        )}
      </div>
      <div className="col gap-4">
        {d.values.map((v) => (
          <div className="row dis-val" key={v.annotator_id}>
            <span className="ellipsis dis-who" title={email(v.annotator_id, v.email)}>
              {email(v.annotator_id, v.email)}
            </span>
            <span className="mono grow">{valueText(v.value)}</span>
            {canAdjudicate && (
              <button className="btn xs" type="button" disabled={save.isPending} onClick={() => save.mutate(v.value)}>
                采用
              </button>
            )}
          </div>
        ))}
        {final !== undefined && (
          <div className="row dis-val final">
            <span className="dis-who">仲裁</span>
            <span className="mono grow">{valueText(final)}</span>
          </div>
        )}
      </div>
      {canAdjudicate && (
        <div className="row" style={{ gap: 6 }}>
          {labelish && labels.length ? (
            <Select size="small" style={{ width: 200 }} placeholder="改为其他标签" aria-label="仲裁标签" value={custom || undefined} onChange={setCustom} showSearch options={labels.map((l) => ({ value: l.name, label: l.name }))} />
          ) : (
            <Input size="small" style={{ width: 240 }} className="mono" placeholder={labelish ? "标签" : "JSON"} aria-label="仲裁值" value={custom} onChange={(e) => setCustom(e.target.value)} />
          )}
          <button
            className="btn xs p"
            type="button"
            disabled={save.isPending || customValue() === undefined}
            onClick={() => {
              const v = customValue();
              if (v !== undefined) save.mutate(v);
            }}
          >
            设为结果
          </button>
        </div>
      )}
    </div>
  );
}

/** 一致性 tab of a multi-annotator layer. */
export function AgreementTab({ layer, labels, canAdjudicate }: { layer: Layer; labels: LabelDef[]; canAdjudicate: boolean }) {
  const q = useAgreement(layer.id);
  const dis = useInfiniteQuery({
    queryKey: ["disagreements", layer.id],
    enabled: canAdjudicate, // owners and editors only (403 otherwise)
    queryFn: ({ pageParam }) => api.get<CursorPage<Disagreement>>(`/layers/${layer.id}/disagreements`, { cursor: pageParam ?? undefined }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const [only, setOnly] = useState(true);
  const items = (dis.data?.pages.flatMap((p) => p.items) ?? []).filter((d) => !only || !isAdjudicated(d));
  const email = (id: string, fallback?: string) => fallback ?? q.data?.annotators.find((a) => a.user_id === id)?.email ?? id.slice(0, 8);
  return (
    <div className="col gap-20">
      <ErrorAlert error={q.error} />
      {q.data ? <AgreementView data={q.data} /> : !q.error && <Skeleton rows={6} />}
      {canAdjudicate && (
      <section className="card" aria-label="分歧">
        <div className="card-head">
          <h2>分歧</h2>
          <div className="grow" />
          <span className="pos-toggle">
            <button className="switch" type="button" role="switch" aria-checked={only} aria-label="只看未仲裁" onClick={() => setOnly((v) => !v)} />
            只看未仲裁
          </span>
        </div>
        <ErrorAlert error={dis.error} style={{ margin: 16 }} />
        {dis.isPending ? (
          <Skeleton rows={4} />
        ) : items.length === 0 && !dis.error ? (
          <Empty icon="check" text={only ? "没有未仲裁的分歧" : "没有分歧"} />
        ) : (
          <div className="diff-list">
            {items.map((d) => (
              <Adjudicate key={`${d.target_kind}:${d.target_key}`} d={d} layerId={layer.id} labels={labels} canAdjudicate={canAdjudicate} email={email} />
            ))}
          </div>
        )}
        {dis.hasNextPage && (
          <div className="card-foot">
            <button className="btn s ghost" type="button" disabled={dis.isFetchingNextPage} onClick={() => dis.fetchNextPage()}>
              {dis.isFetchingNextPage && <span className="spin" />}
              加载更多
            </button>
          </div>
        )}
      </section>
      )}
    </div>
  );
}
