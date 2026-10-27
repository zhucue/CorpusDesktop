import { App } from "antd";
import { useEffect, useRef } from "react";
import { Link } from "react-router";
import type { Job } from "../../api";
import { isActiveJob, quietJobs, useProjectJobs } from "../../lib/data";
import { fmt } from "../../lib/format";
import { Progress, Sparkline } from "../common";

export const jobKindLabels: Record<string, string> = { import: "导入", index: "建索引", export: "导出", stats: "统计", preannotate: "预标注" };

export function jobTitle(j: Job): string {
  return `${jobKindLabels[j.kind] ?? j.kind}${j.progress.message ? ` · ${j.progress.message}` : ""}`;
}

export function progressText(j: Job): string {
  const { done, total } = j.progress;
  return total ? `${fmt(done)} / ${fmt(total)}` : `已处理 ${fmt(done)}`;
}

export function TaskTray({ projectId, open, onToggle }: { projectId: string; open: boolean; onToggle: () => void }) {
  const jobs = useProjectJobs(projectId);
  const { notification } = App.useApp();
  const items = jobs.data?.items ?? [];
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
              j.kind === "export" ? (
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
  }, [jobs.data]); // eslint-disable-line react-hooks/exhaustive-deps

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
          {shown.length === 0 && <div className="empty sm">暂无任务</div>}
          {shown.map((j) => {
            const deltas = (speed.current.get(j.id) ?? []).map((v, i, a) => (i ? v - a[i - 1] : 0)).slice(1);
            return (
              <div className="job-mini" key={j.id}>
                <div className="row">
                  <span className="grow ellipsis">{jobTitle(j)}</span>
                  <span className="mono small muted">#{j.id.slice(0, 8)}</span>
                </div>
                <Progress done={j.progress.done} total={j.progress.total} state={j.state} thin />
                <div className="row small muted">
                  <span className="num grow">{j.state === "failed" ? (j.error?.message ?? "失败") : progressText(j)}</span>
                  {isActiveJob(j) && deltas.length > 1 && <Sparkline values={deltas} w={48} h={14} label="处理速度" />}
                  {j.progress.total ? <span className="num">{Math.round((j.progress.done / j.progress.total) * 100)}%</span> : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <button className="capsule" type="button" aria-expanded={open} aria-controls="tray-panel" onClick={onToggle}>
        <svg className={`ring ${anyFailed && !running.length ? "err" : ""}`} viewBox="0 0 24 24" aria-hidden>
          <circle className="bg" cx="12" cy="12" r="9" />
          <circle className="fg" cx="12" cy="12" r="9" pathLength={100} strokeDasharray={100} strokeDashoffset={(100 - pct).toFixed(1)} />
        </svg>
        <span>{running.length ? `${running.length} 个任务运行中` : "任务"}</span>
      </button>
    </div>
  );
}
