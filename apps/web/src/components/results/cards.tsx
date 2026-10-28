import { createContext, useContext } from "react";
import { Link, useNavigate } from "react-router";
import type { EvidenceInput, JobKind, JobState, Scope } from "../../api";
import { useJob } from "../../lib/data";
import { fmt, fmtValue } from "../../lib/format";
import { Empty, JobStateTag, Progress } from "../common";
import { PinButton } from "../global/evidence";
import { jobKindLabels } from "../global/TaskTray";
import { Icon, type IconName } from "../Icon";
import { jobKindIcon } from "../iconSets";
import { KwicTable as KwicRows } from "./Kwic";

/** Where result cards link to: the project and the session scope. */
export const ResultContext = createContext<{ projectId: string; scope: Scope | null }>({ projectId: "", scope: null });

function searchUrl(projectId: string, query: string, scope: Scope | null) {
  const p = new URLSearchParams({ q: query });
  if (scope) p.set("scope", JSON.stringify(scope));
  return `/p/${projectId}/search?${p.toString()}`;
}

export function Card({
  icon,
  title,
  meta,
  right,
  pin,
  children,
  foot,
  component,
}: {
  icon: IconName;
  title: string;
  meta?: React.ReactNode;
  right?: React.ReactNode;
  pin?: EvidenceInput;
  children: React.ReactNode;
  foot?: React.ReactNode;
  component: string;
}) {
  return (
    <div className="ou" data-component={component}>
      <div className="ou-head">
        <span className="ou-ic">
          <Icon name={icon} />
        </span>
        <span className="ou-title">{title}</span>
        {meta && <span className="ou-meta">{meta}</span>}
        <div className="grow" />
        {right && <span className="ou-meta">{right}</span>}
        {pin && <PinButton input={pin} />}
      </div>
      {children}
      {foot && <div className="ou-foot">{foot}</div>}
    </div>
  );
}

function StatLink({ statId, label = "在统计中打开" }: { statId: string; label?: string }) {
  const { projectId } = useContext(ResultContext);
  return (
    <Link className="btn xs" to={`/p/${projectId}/stats?stat=${encodeURIComponent(statId)}`}>
      <Icon name="external" size={14} />
      {label}
    </Link>
  );
}

function cardPin(component: string, text: string): EvidenceInput {
  return { kind: "text", ref: {}, text, source: `助手 · ${component}` };
}

/* ---------- KwicTable ---------- */
export interface KwicTableProps {
  search_id: string;
  query: string;
  scope_name: string;
  counts: { hits: number; sentences: number; documents: number };
  rows: { hit_id: string; left: string; match: string; right: string; source: string; aligned?: string }[];
  total: number;
}

export function KwicTableCard(p: KwicTableProps) {
  const { projectId, scope } = useContext(ResultContext);
  return (
    <Card
      component="KwicTable"
      icon="textsearch"
      title="KWIC"
      meta={p.query}
      right={`${fmt(p.counts?.hits ?? p.total)} 命中`}
      foot={
        <Link className="btn xs" to={searchUrl(projectId, p.query, scope)}>
          <Icon name="external" size={14} />
          打开完整结果
        </Link>
      }
    >
      <KwicRows
        compact
        rows={(p.rows ?? []).map((r) => ({
          id: r.hit_id,
          left: r.left,
          match: r.match,
          right: r.right,
          source: r.source,
          aligned: r.aligned ? [{ language: "", text: r.aligned }] : undefined,
          evidence: { kind: "hit", ref: { hit_id: r.hit_id, search_query: p.query, scope: scope ?? undefined }, text: `${r.left}${r.match}${r.right}`, source: `${r.source} · ${p.scope_name}` },
        }))}
      />
      {(p.rows ?? []).length === 0 && <Empty icon="searchx" text="没有命中" />}
    </Card>
  );
}

/* ---------- FreqChart ---------- */
export interface FreqChartProps {
  stat_id: string;
  title: string;
  unit: string;
  rows: { label: string; value: number; per_million?: number }[];
  top: number;
}

export function FreqChartCard(p: FreqChartProps) {
  const { projectId, scope } = useContext(ResultContext);
  const navigate = useNavigate();
  const rows = (p.rows ?? []).slice(0, p.top || 10);
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <Card
      component="FreqChart"
      icon="chartbar"
      title={p.title || "频次"}
      meta={p.unit}
      right={`前 ${rows.length}${p.rows?.length > rows.length ? ` / ${p.rows.length}` : ""}`}
      pin={cardPin("FreqChart", `${p.title} · ${rows.map((r) => r.label).slice(0, 3).join("、")}`)}
      foot={<StatLink statId={p.stat_id} />}
    >
      <div className="ou-body">
        {rows.length === 0 ? (
          <Empty icon="barchart" text="无结果" />
        ) : (
          <div className="hbars">
            {rows.map((r, i) => (
              <div
                className="hbar"
                key={i}
                style={{ ["--i" as string]: i, cursor: "pointer" }}
                role="button"
                tabIndex={0}
                title="打开例句"
                onClick={() => navigate(searchUrl(projectId, `"${r.label}"`, scope))}
              >
                <span className="lab">{r.label}</span>
                <span className="track">
                  <i style={{ ["--v" as string]: `${((r.value / max) * 100).toFixed(1)}%` }} />
                </span>
                <span className="val">
                  {fmtValue(r.value)}
                  {r.per_million != null ? ` · ${fmtValue(r.per_million, 1)}` : ""}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

/* ---------- CollocationTable ---------- */
export interface CollocationTableProps {
  stat_id: string;
  node: string;
  window: number;
  measure: string;
  rows: { collocate: string; freq: number; score: number }[];
}

export function CollocationTableCard(p: CollocationTableProps) {
  const { projectId, scope } = useContext(ResultContext);
  const navigate = useNavigate();
  const gap = p.window > 1 ? ` $${p.window - 1} ` : " ";
  return (
    <Card
      component="CollocationTable"
      icon="chartnetwork"
      title="搭配"
      meta={`${p.node} · ±${p.window} · ${p.measure}`}
      right={`${fmt(p.rows?.length ?? 0)} 项`}
      pin={cardPin("CollocationTable", `${p.node} 搭配 · ${(p.rows ?? []).slice(0, 3).map((r) => r.collocate).join("、")}`)}
      foot={<StatLink statId={p.stat_id} />}
    >
      <div className="ou-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
        <table className="tbl mid">
          <thead>
            <tr>
              <th>搭配词</th>
              <th className="r">共现</th>
              <th className="r">{p.measure}</th>
              <th />
            </tr>
          </thead>
          <tbody className="stagger">
            {(p.rows ?? []).map((r, i) => (
              <tr key={i} style={{ ["--i" as string]: i }}>
                <td style={{ fontWeight: 500 }}>{r.collocate}</td>
                <td className="r num">{fmt(r.freq)}</td>
                <td className="r num" style={{ color: "var(--accent)", fontWeight: 600 }}>
                  {fmtValue(r.score)}
                </td>
                <td className="r">
                  <button className="back" type="button" onClick={() => navigate(searchUrl(projectId, `${p.node}${gap}"${r.collocate}"`, scope))}>
                    例句
                    <Icon name="right" size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ---------- KeywordTable ---------- */
export interface KeywordTableProps {
  stat_id: string;
  target: string;
  reference: string;
  measure: string;
  rows: { word: string; target_freq: number; reference_freq: number; score: number }[];
}

export function KeywordTableCard(p: KeywordTableProps) {
  const { projectId, scope } = useContext(ResultContext);
  const navigate = useNavigate();
  return (
    <Card
      component="KeywordTable"
      icon="chartscatter"
      title="关键词"
      meta={`${p.target} 对 ${p.reference}`}
      right={p.measure === "log_ratio" ? "Log Ratio" : "LL"}
      pin={cardPin("KeywordTable", `关键词 · ${(p.rows ?? []).slice(0, 3).map((r) => r.word).join("、")}`)}
      foot={<StatLink statId={p.stat_id} />}
    >
      <div className="ou-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
        <table className="tbl mid">
          <thead>
            <tr>
              <th>词</th>
              <th className="r">目标</th>
              <th className="r">参照</th>
              <th className="r">{p.measure === "log_ratio" ? "Log Ratio" : "LL"}</th>
            </tr>
          </thead>
          <tbody className="stagger">
            {(p.rows ?? []).map((r, i) => (
              <tr key={i} style={{ ["--i" as string]: i, cursor: "pointer" }} onClick={() => navigate(searchUrl(projectId, `"${r.word}"`, scope))}>
                <td className="mono">{r.word}</td>
                <td className="r num">{fmt(r.target_freq)}</td>
                <td className="r num">{fmt(r.reference_freq)}</td>
                <td className="r num">{fmtValue(r.score)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ---------- DistributionChart ---------- */
export interface DistributionChartProps {
  stat_id: string;
  field: string;
  rows: { bin: string; hits: number; per_million: number }[];
}

export function DistributionChartCard(p: DistributionChartProps) {
  const rows = p.rows ?? [];
  const max = Math.max(...rows.map((r) => r.per_million ?? 0), 1e-9);
  return (
    <Card component="DistributionChart" icon="barchart" title="分布" meta={`${p.field === "position" ? "文档位置" : p.field} · 每百万词`} foot={<StatLink statId={p.stat_id} />}>
      <div className="ou-body">
        <div className="vbars">
          {rows.map((r, i) => (
            <div className="vbar" key={i} style={{ ["--i" as string]: i }} title={`${r.bin} · ${fmt(r.hits)} 命中 · ${fmtValue(r.per_million, 1)} 每百万`}>
              <em>{fmtValue(r.per_million, 1)}</em>
              <i style={{ ["--v" as string]: `${(((r.per_million ?? 0) / max) * 82).toFixed(1)}%` }} />
              <span>{r.bin}</span>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

/* ---------- EvidenceCard ---------- */
export interface EvidenceCardProps {
  evidence_id: string;
  text: string;
  source: string;
}

export function EvidenceCardView(p: EvidenceCardProps) {
  return (
    <Card component="EvidenceCard" icon="basket" title="证据" right="已钉住">
      <div className="ou-body col" style={{ gap: 4 }}>
        <div className="sm" style={{ lineHeight: 1.7 }}>
          {p.text}
        </div>
        <span className="mono small muted">{p.source}</span>
      </div>
    </Card>
  );
}

/* ---------- JobStatus ---------- */
export interface JobStatusProps {
  job_id: string;
  kind: string;
  state: string;
  progress: { done: number; total: number | null; message: string };
}

export function JobStatusCard(p: JobStatusProps) {
  const { projectId } = useContext(ResultContext);
  const live = useJob(p.job_id, 2000);
  const state = (live.data?.state ?? p.state) as JobState;
  const progress = live.data?.progress ?? p.progress ?? { done: 0, total: null, message: "" };
  return (
    <Card
      component="JobStatus"
      icon={jobKindIcon[p.kind as JobKind] ?? "clock"}
      title={`${jobKindLabels[p.kind] ?? p.kind}任务`}
      meta={`#${p.job_id.slice(0, 8)}`}
      right={<JobStateTag state={state} />}
      foot={
        <Link className="btn xs" to={`/p/${projectId}/jobs?job=${encodeURIComponent(p.job_id)}`}>
          <Icon name="external" size={14} />
          打开任务
        </Link>
      }
    >
      <div className="ou-body col" style={{ gap: 6 }}>
        <Progress done={progress.done} total={progress.total} state={state} />
        <div className="row small muted">
          <span className="num grow">{progress.total ? `${fmt(progress.done)} / ${fmt(progress.total)}` : `已处理 ${fmt(progress.done)}`}</span>
          <span>{live.data?.error?.message ?? progress.message}</span>
        </div>
      </div>
    </Card>
  );
}

/* ---------- Callout ---------- */
export interface CalloutProps {
  tone: "info" | "warning";
  text: string;
}

export function CalloutView(p: CalloutProps) {
  return (
    <div className={`callout ${p.tone === "warning" ? "warning" : "info"}`} role="note">
      <Icon name={p.tone === "warning" ? "alert" : "info"} size={14} />
      <span>{p.text}</span>
    </div>
  );
}

