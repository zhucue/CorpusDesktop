import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { ApiError, api, type Job, type StatMethod, type StatResult } from "../../api";
import { quietJobs, useJob, useJobCreated } from "../../lib/data";

/**
 * Start a statistics job for `body` (once per distinct body and runKey), poll it, then load the StatResult.
 * Pass body = null to stay idle. quiet: true = never toast on completion; "mounted" = no toast while the calling
 * page is open (its result shows there), the task tray toasts once the user has left.
 */
export function useStatJob(method: StatMethod, body: object | null, projectId: string, runKey = 0, opts: { quiet?: boolean | "mounted" } = {}) {
  const jobCreated = useJobCreated();
  const create = useQuery({
    queryKey: ["stat-run", method, body, runKey],
    queryFn: () => api.post<Job>(`/stats/${method}`, body),
    enabled: !!body,
    staleTime: Infinity,
    gcTime: 30 * 60 * 1000,
    retry: false,
    meta: { background: true },
  });
  const id = create.data?.id;
  useEffect(() => {
    if (!id) return;
    if (opts.quiet) quietJobs.add(id);
    jobCreated(projectId);
    if (opts.quiet !== "mounted") return;
    return () => {
      quietJobs.delete(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  const job = useJob(id);
  const current = job.data ?? create.data;
  const statId = current?.state === "succeeded" ? (current.result?.stat_id ?? null) : null;
  const stat = useStatResult(statId);
  const running = !!body && (create.isFetching || (!!current && (current.state === "queued" || current.state === "running")) || stat.isFetching);
  const jobError = current?.state === "failed" && current.error ? new ApiError(0, current.error.code, current.error.message) : null;
  const error = create.error ?? job.error ?? stat.error ?? jobError;
  return { job: current, stat: stat.data, running, error, failed: current?.state === "failed" || current?.state === "cancelled" };
}

export function useStatResult(statId: string | null | undefined) {
  return useQuery({
    queryKey: ["stat", statId],
    queryFn: () => api.get<StatResult>(`/stats/${statId}`),
    enabled: !!statId,
    staleTime: Infinity,
  });
}
