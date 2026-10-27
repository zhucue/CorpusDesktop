import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Progress, Space, Table, Tag, Typography } from "antd";
import { useState } from "react";
import { api, errorText, type Job, type JobState, type Page } from "../api";
import { fmtTime } from "../corpora";
import { useProjectId } from "../projects";

const PAGE_SIZE = 50;

const kindLabels: Record<Job["kind"], string> = { import: "导入", index: "建索引", export: "导出" };
const stateView: Record<JobState, { label: string; color: string }> = {
  queued: { label: "排队中", color: "default" },
  running: { label: "运行中", color: "processing" },
  succeeded: { label: "已完成", color: "success" },
  failed: { label: "失败", color: "error" },
  cancelled: { label: "已取消", color: "default" },
};

const active = (j: Job) => j.state === "queued" || j.state === "running";

function JobProgress({ job }: { job: Job }) {
  const { done, total, message } = job.progress;
  return (
    <Space direction="vertical" size={0} style={{ width: "100%" }}>
      {total ? (
        <Progress
          percent={Math.floor((done / total) * 100)}
          size="small"
          status={job.state === "failed" ? "exception" : active(job) ? "active" : undefined}
          format={() => `${done}/${total}`}
        />
      ) : (
        active(job) && <Typography.Text>已处理 {done}</Typography.Text>
      )}
      {message && <Typography.Text type="secondary">{message}</Typography.Text>}
      {job.kind === "export" && job.state === "succeeded" && job.result && (
        <Typography.Text>
          {job.result.filename} · {(job.result.rows ?? 0).toLocaleString("zh-CN")} 行
        </Typography.Text>
      )}
      {job.error && <Typography.Text type="danger">{job.error.message}</Typography.Text>}
    </Space>
  );
}

export default function Jobs() {
  const projectId = useProjectId();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [page, setPage] = useState(1);
  const jobs = useQuery({
    queryKey: ["jobs", projectId, page],
    queryFn: () => api.get<Page<Job>>(`/projects/${projectId}/jobs`, { page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items.some(active) ? 3000 : false),
  });

  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "cancel" | "retry" }) => api.post<Job>(`/jobs/${id}/${action}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs", projectId] });
      qc.invalidateQueries({ queryKey: ["corpora", projectId] });
    },
    onError: (e) => message.error(errorText(e)),
  });

  return (
    <Card title="任务">
      {jobs.error && <Alert type="error" showIcon message={errorText(jobs.error)} />}
      <Table<Job>
        rowKey="id"
        size="small"
        loading={jobs.isPending}
        dataSource={jobs.data?.items}
        locale={{ emptyText: "暂无任务" }}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total: jobs.data?.total ?? 0,
          showSizeChanger: false,
          onChange: setPage,
        }}
        columns={[
          { title: "类型", width: 80, render: (_, j) => kindLabels[j.kind] ?? j.kind },
          {
            title: "状态",
            width: 90,
            render: (_, j) => {
              const v = stateView[j.state] ?? { label: j.state, color: "default" };
              return <Tag color={v.color}>{v.label}</Tag>;
            },
          },
          { title: "进度", render: (_, j) => <JobProgress job={j} /> },
          { title: "创建时间", width: 170, render: (_, j) => fmtTime(j.created_at) },
          { title: "结束时间", width: 170, render: (_, j) => fmtTime(j.finished_at) },
          {
            title: "操作",
            width: 140,
            render: (_, j) => (
              <Space size={0}>
                {active(j) && (
                  <Button type="link" size="small" onClick={() => act.mutate({ id: j.id, action: "cancel" })}>
                    取消
                  </Button>
                )}
                {(j.state === "failed" || j.state === "cancelled") && (
                  <Button type="link" size="small" onClick={() => act.mutate({ id: j.id, action: "retry" })}>
                    重试
                  </Button>
                )}
                {j.kind === "export" && j.state === "succeeded" && (
                  <Button type="link" size="small" href={`/api/jobs/${j.id}/download`}>
                    下载
                  </Button>
                )}
              </Space>
            ),
          },
        ]}
      />
    </Card>
  );
}
