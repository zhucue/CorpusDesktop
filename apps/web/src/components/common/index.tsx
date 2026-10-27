import { Tooltip } from "antd";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { errorCode, errorText, type CorpusStatus, type JobState } from "../../api";
import { fmt } from "../../lib/format";
import { reducedMotion } from "../../theme/motion";
import { Icon, type IconName } from "../Icon";

/* ---------- monogram / avatar (B8) ---------- */
const HUES = [212, 168, 38, 350, 256, 96, 22, 196];
export function hueOf(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return HUES[h % HUES.length];
}

export function Monogram({ name, size }: { name: string; size?: "lg" | "xl" }) {
  return (
    <span className={`monogram ${size ?? ""}`} style={{ ["--h" as string]: hueOf(name || "?") }} aria-hidden>
      {Array.from(name || "?")[0]}
    </span>
  );
}

export function Avatar({ name }: { name: string }) {
  return (
    <span className="avatar" data-h style={{ ["--h" as string]: hueOf(name || "?") }} aria-hidden>
      {Array.from(name || "?")[0]?.toUpperCase()}
    </span>
  );
}

/* ---------- tooltip with the 300 ms delay (B16) ---------- */
export function Tip({ title, children }: { title: ReactNode; children: React.ReactElement }) {
  return (
    <Tooltip title={title} mouseEnterDelay={0.3}>
      {children}
    </Tooltip>
  );
}

/* ---------- query chip with syntax colouring (B12) ---------- */
function qTokens(tok: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  let t = tok;
  if (/^[+-]./.test(t)) {
    out.push(<span key={`${key}o`} className={t[0] === "+" ? "qc" : "qn"}>{t[0]}</span>);
    t = t.slice(1);
  }
  if (/^\$\d+(-\d+)?$/.test(t) || t === "*" || t === "?") return [...out, <span key={key} className="qg">{t}</span>];
  if (/^".*"$/.test(t)) return [...out, <span key={key} className="qs">{t}</span>];
  if (/^[{[].*[}\]]$/.test(t)) return [...out, <span key={key} className="qa">{t}</span>];
  if (t === "|") return [<span key={key} className="qc">|</span>];
  t.split("|").forEach((alt, i) => {
    if (i) out.push(<span key={`${key}b${i}`} className="qc">|</span>);
    if (/^".*"$/.test(alt)) {
      out.push(<span key={`${key}s${i}`} className="qs">{alt}</span>);
      return;
    }
    const slash = alt.indexOf("/");
    if (slash < 0) out.push(<span key={`${key}w${i}`} className="qw">{alt}</span>);
    else {
      if (slash > 0) out.push(<span key={`${key}w${i}`} className="qw">{alt.slice(0, slash)}</span>);
      out.push(<span key={`${key}p${i}`} className="qp">{alt.slice(slash)}</span>);
    }
  });
  return out;
}

export function QueryChip({ q, className }: { q: string; className?: string }) {
  const parts = q.split(/(\s+)/);
  return (
    <span className={`q ${className ?? ""}`}>
      {parts.map((p, i) => (!p || /^\s+$/.test(p) ? p : qTokens(p, String(i))))}
    </span>
  );
}

/* ---------- sparkline (B13) ---------- */
export function Sparkline({ values, w = 64, h = 18, label }: { values: number[]; w?: number; h?: number; label?: string }) {
  if (values.length < 2) return null;
  const mn = Math.min(...values);
  const mx = Math.max(...values);
  const pts = values.map((y, i) => [(i / (values.length - 1)) * w, h - 2 - ((y - mn) / (mx - mn || 1)) * (h - 4)]);
  const line = pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  return (
    <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={label ?? `趋势 ${values.join("、")}`}>
      <polygon className="ar" points={`0,${h} ${line} ${w},${h}`} />
      <polyline className="ln" points={line} />
      <circle className="pt" r={2} cx={last[0].toFixed(1)} cy={last[1].toFixed(1)} />
    </svg>
  );
}

/* ---------- count with rolling digits (B9) ---------- */
export function useCountUp(target: number | null, ms = 900): number | null {
  const [v, setV] = useState(target);
  const from = useRef(0);
  useEffect(() => {
    if (target == null) {
      setV(null);
      return;
    }
    if (reducedMotion()) {
      setV(target);
      return;
    }
    const start = performance.now();
    const a = from.current;
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / ms);
      const e = 1 - (1 - k) ** 3;
      setV(Math.round(a + (target - a) * e));
      if (k < 1) raf = requestAnimationFrame(step);
      else from.current = target;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

export function Count({ value, unit, pending }: { value: number | null; unit: string; pending?: string }) {
  const v = useCountUp(pending ? null : value);
  if (pending) return <div className="count pending">{pending}</div>;
  return (
    <div className="count">
      <span className="n">{fmt(v ?? 0)}</span>
      <span className="unit">{unit}</span>
    </div>
  );
}

/* ---------- status tags (B7) ---------- */
const corpusView: Record<CorpusStatus, { label: string; cls: string; busy?: "dot" | "spin" }> = {
  empty: { label: "空", cls: "t-gray" },
  importing: { label: "导入中", cls: "t-run", busy: "dot" },
  indexing: { label: "建索引", cls: "t-run", busy: "spin" },
  ready: { label: "可检索", cls: "t-ok" },
  stale: { label: "索引过期", cls: "t-warn" },
  failed: { label: "失败", cls: "t-err" },
};

export function CorpusStatusTag({ status }: { status: CorpusStatus }) {
  const v = corpusView[status] ?? { label: status, cls: "t-gray" };
  return (
    <span className={`tag ${v.cls}`}>
      {v.busy === "dot" && <span className="dot pulse" />}
      {v.busy === "spin" && <span className="spin" style={{ width: 10, height: 10 }} />}
      {v.label}
    </span>
  );
}

export const jobStateView: Record<JobState, { label: string; cls: string }> = {
  queued: { label: "排队中", cls: "t-gray" },
  running: { label: "运行中", cls: "t-run" },
  succeeded: { label: "已完成", cls: "t-ok" },
  failed: { label: "失败", cls: "t-err" },
  cancelled: { label: "已取消", cls: "t-gray" },
};

export function JobStateTag({ state }: { state: JobState }) {
  const v = jobStateView[state] ?? { label: state, cls: "t-gray" };
  return (
    <span className={`tag ${v.cls}`}>
      {state === "running" && <span className="dot pulse" />}
      {v.label}
    </span>
  );
}

/* ---------- progress (5.1) ---------- */
export function Progress({ done, total, state, thin }: { done: number; total: number | null; state?: JobState; thin?: boolean }) {
  const cls = state === "succeeded" ? "ok" : state === "failed" ? "err" : state === "cancelled" ? "gray" : total ? "striped" : "indet";
  const pct = total ? Math.min(100, (done / total) * 100) : state === "succeeded" ? 100 : 0;
  return (
    <span className={`prog ${cls} ${thin ? "thin" : ""}`} role="progressbar" aria-valuenow={total ? Math.round(pct) : undefined} aria-valuemin={0} aria-valuemax={100}>
      <i style={{ ["--v" as string]: `${pct}%` }} />
    </span>
  );
}

/* ---------- empty state and errors ---------- */
export function Empty({ icon = "info", text, children }: { icon?: IconName; text: ReactNode; children?: ReactNode }) {
  return (
    <div className="empty">
      <Icon name={icon} />
      <span className="sm">{text}</span>
      {children && <div className="row">{children}</div>}
    </div>
  );
}

/** Shows the API message verbatim with the code in small mono after it (doc 10 错误显示). */
export function ErrorAlert({ error, children, style }: { error: unknown; children?: ReactNode; style?: React.CSSProperties }) {
  if (!error) return null;
  const code = errorCode(error);
  return (
    <div className="alert err" role="alert" style={style}>
      <Icon name="alert" size={14} />
      <div className="grow">
        {errorText(error)}
        {code && <span className="err-code">{code}</span>}
      </div>
      {children}
    </div>
  );
}

export function Skeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="col" style={{ padding: "16px 18px", gap: 14 }}>
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} className="skel" style={{ width: `${88 - ((i * 13) % 30)}%` }} />
      ))}
    </div>
  );
}
