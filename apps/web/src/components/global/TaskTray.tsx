import { App } from "antd";
import { useEffect, useMemo, useRef } from "react";
import { Link } from "react-router";
import type { Job } from "../../api";
import { isActiveJob, quietJobs, useBuiltinJobs, useMe, useProjectJobs } from "../../lib/data";
import { fmt } from "../../lib/format";
import { Empty, Progress, Sparkline } from "../common";
import { Icon } from "../Icon";
import { jobKindIcon } from "../iconSets";

export const jobKindLabels: Record<string, string> = {
  import: "导入",
  index: "建索引",
  export: "导出",
  stats: "统计",
  preannotate: "预标注",
  kb_import: "文献导入",
  kb_summarize: "文献摘要",
  kb_extract: "术语抽取",
};

/** Jobs with a file to download (exports; knowledge-base exports may use their own kind). */
export const hasDownload = (j: Job) => j.state === "succeeded" && (j.kind === "export" || typeof j.result?.filename === "string");

/** What the job works on: "频次 · 语料名" for statistics, "导入 · 语料：文件" etc.; the step when there is no summary. */
export function jobTitle(j: Job): string {
  const label = jobKindLabels[j.kind] ?? j.kind;
  if (j.summary && j.summary !== j.kind) return j.kind === "stats" ? j.summary : `${label} · ${j.summary}`;
  return `${label}${j.progress.message ? ` · ${j.progress.message}` : ""}`;
}

/** Unit of done/total: reported by the job, or the "（字符）" suffix older jobs put in the message. */
export function progressUnit(j: Job): string {
  return j.progress.unit ?? /（(.+?)）$/.exec(j.progress.message)?.[1] ?? "";
}

export function progressText(j: Job): string {
  if (j.state === "queued") {
    if (j.queue_ahead == null) return "排队中";
    return j.queue_ahead > 0 ? `排队中 · 前面还有 ${fmt(j.queue_ahead)} 个任务` : "排队中 · 下一个执行";
  }
  if (j.state === "succeeded") return "已完成";
  if (j.state === "cancelled") return "已取消";
  const { done, total } = j.progress;
  const unit = progressUnit(j);
  const u = unit ? ` ${unit}` : "";
  return total ? `${fmt(done)} / ${fmt(total)}${u}` : `已处理 ${fmt(done)}${u}`;
}

/** Where a finished job's result opens: statistics result, download, or the job's detail. */
export function jobLink(j: Job, projectId: string): { to?: string; href?: string } {
  if (hasDownload(j)) return { href: `/api/jobs/${j.id}/download` };
  if (j.kind === "stats" && j.result?.stat_id) return { to: `/p/${projectId}/stats?stat=${j.result.stat_id}` };
  return { to: `/p/${projectId}/jobs?job=${j.id}` };
}

export function TaskTray({ projectId, open, onToggle }: { projectId: string; open: boolean; onToggle: () => void }) {
  const jobs = useProjectJobs(projectId);
  const me = useMe();
  const builtin = useBuiltinJobs(!!me.data?.is_admin);
  const { notification } = App.useApp();
  // Platform admins also see built-in corpus jobs, newest first together with the project's.
  const items = useMemo(() => {
    const own = jobs.data?.items ?? [];
    const extra = builtin.data?.items ?? [];
    if (!extra.length) return own;
    return [...own, ...extra].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  }, [jobs.data, builtin.data]);
  const running = items.filter(isActiveJob);
  const prev = useRef<Map<string, Job["state"]> | null>(null);
  const speed = useRef(new Map<string, number[]>());

  // Toast when a job we saw running reaches a final state; keep a short history of `done` for the speed sparkline.
  useEffect(() => {
    if (!jobs.data) return;
    const before = prev.current;
    const now = new Map(items.map((j) => [j.id, j.state]));
    if (before) {
      for (const j of items) {
        const was = before.get(j.id);
        if (!was || !(was === "queued" || was === "running") || isActiveJob(j) || quietJobs.has(j.id)) continue;
        const title = jobKindLabels[j.kind] ?? j.kind;
        if (j.state === "succeeded")
          notification.success({
            message: `${title}完成`,
            description:
              hasDownload(j) ? (
                <a href={`/api/jobs/${j.id}/download`}>下载 {j.result?.filename ?? ""}</a>
              ) : (
                <Link to={`/p/${projectId}/jobs`}>查看任务</Link>
              ),
            placement: "bottomRight",
            duration: 4,
          });
        else if (j.state === "failed")
          notification.error({ message: `${title}失败`, description: j.error?.message, placement: "bottomRight", duration: 6 });
      }
    }
    prev.current = now;
    for (const j of running) {
      const h = speed.current.get(j.id) ?? [];
      if (h[h.length - 1] !== j.progress.done) h.push(j.progress.done);
      speed.current.set(j.id, h.slice(-8));
    }
  }, [items]); // eslint-disable-line react-hooks/exhaustive-deps

  const withTotal = running.filter((j) => j.progress.total);
  const pct = withTotal.length
    ? (withTotal.reduce((s, j) => s + j.progress.done / (j.progress.total || 1), 0) / withTotal.length) * 100
    : running.length
      ? 0
      : 100;
  const shown = [...running, ...items.filter((j) => !isActiveJob(j)).slice(0, Math.max(0, 4 - running.length))];
  const anyFailed = items.slice(0, 5).some((j) => j.state === "failed");

  return (
    <div className="dock-item">
      <div className={`dock-panel ${open ? "open" : ""}`} id="tray-panel" role="dialog" aria-label="任务">
        <div className="dp-head">
          <b className="grow">{running.length ? "运行中的任务" : "最近任务"}</b>
          <Link className="btn xs ghost" to={`/p/${projectId}/jobs`}>
            全部任务
          </Link>
        </div>
        <div className="dp-body">
          {shown.length === 0 && <Empty icon="inbox" text="暂无任务" />}
          {shown.map((j) => {
            const deltas = (speed.current.get(j.id) ?? []).map((v, i, a) => (i ? v - a[i - 1] : 0)).slice(1);
            return (
              <div className="job-mini" key={j.id}>
                <div className="row">
                  <Icon name={jobKindIcon[j.kind] ?? "clock"} size={14} className="muted" />
                  {(() => {
                    const l = jobLink(j, projectId);
                    const t = jobTitle(j);
                    return l.href ? (
                      <a className="grow ellipsis" href={l.href} title={t}>
                        {t}
                      </a>
                    ) : (
                      <Link className="grow ellipsis" to={l.to!} title={t}>
                        {t}
                      </Link>
                    );
                  })()}
                  {j.project_id === null && <span className="tag t-gray">内置</span>}
                  <span className="mono small muted">#{j.id.slice(0, 8)}</span>
                </div>
                <Progress done={j.progress.done} total={j.progress.total} state={j.state} thin />
                <div className="row small muted">
                  <span className="num grow ellipsis">
                    {j.state === "failed" ? (j.error?.message ?? "失败") : j.state === "running" && j.progress.message ? `${j.progress.message} · ${progressText(j)}` : progressText(j)}
                  </span>
                  {isActiveJob(j) && deltas.length > 1 && <Sparkline values={deltas} w={48} h={14} label="处理速度" />}
                  {j.progress.total ? <span className="num">{Math.round((j.progress.done / j.progress.total) * 100)}%</span> : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <button className="capsule" type="button" aria-expanded={open} aria-controls="tray-panel" onClick={onToggle}>
        {(running.length > 0 || anyFailed) && (
          <svg className={`ring ${anyFailed && !running.length ? "err" : ""}`} viewBox="0 0 24 24" aria-hidden>
            <circle className="bg" cx="12" cy="12" r="9" />
            <circle className="fg" cx="12" cy="12" r="9" pathLength={100} strokeDasharray={100} strokeDashoffset={(100 - pct).toFixed(1)} />
          </svg>
        )}
        <span>{running.length ? `${running.length} 个任务运行中` : "任务"}</span>
      </button>
    </div>
  );
}
