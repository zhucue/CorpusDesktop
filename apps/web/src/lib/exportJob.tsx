import { useMutation } from "@tanstack/react-query";
import { App } from "antd";
import { useEffect, useRef, useState } from "react";
import { api, errorText, type Job } from "../api";
import { quietJobs, useJob, useJobCreated } from "./data";

function save(href: string, filename: string) {
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/**
 * Export as a background job: toast "已开始导出", poll it, download the file when it finishes (with a 下载 link in
 * the completion toast). Leaving the page hands the job back to the task tray, which toasts with the link.
 */
export function useExportJob(projectId: string) {
  const { message, notification } = App.useApp();
  const jobCreated = useJobCreated();
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  const pending = useRef<string | null>(null);
  pending.current = jobId;

  const start = useMutation({
    mutationFn: (req: { url: string; body: object; label: string }) => api.post<Job>(req.url, req.body),
    onSuccess: (j, req) => {
      quietJobs.add(j.id);
      setJobId(j.id);
      jobCreated(projectId);
      message.info(`已开始导出 ${req.label}`);
    },
    onError: (e) => message.error(errorText(e)),
  });

  useEffect(() => {
    const j = job.data;
    if (!j || j.id !== jobId || j.state === "queued" || j.state === "running") return;
    setJobId(null);
    if (j.state === "succeeded") {
      const href = `/api/jobs/${j.id}/download`;
      const name = typeof j.result?.filename === "string" ? j.result.filename : "";
      save(href, name);
      notification.success({ message: "导出完成", description: <a href={href}>下载 {name}</a>, placement: "top", duration: 6 });
    } else notification.error({ message: "导出失败", description: j.error?.message ?? "任务已取消", placement: "top", duration: 6 });
  }, [job.data, jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(
    () => () => {
      if (pending.current) quietJobs.delete(pending.current);
    },
    [],
  );

  return { start: start.mutate, busy: start.isPending || !!jobId };
}
