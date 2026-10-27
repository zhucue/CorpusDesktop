import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Segmented, Table } from "antd";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api, errorText, type Job, type Page } from "../../api";
import { ErrorAlert, JobStateTag, Progress, Sparkline } from "../../components/common";
import { hasDownload, jobKindLabels, progressText } from "../../components/global/TaskTray";
import { Icon, type IconName } from "../../components/Icon";
import { PageHeader } from "../../components/shell/AppShell";
import { isActiveJob, useJob, useProjectId } from "../../lib/data";
import { fmt, fmtDuration, fmtTime } from "../../lib/format";
import "./jobs.css";

const PAGE_SIZE = 50;
type Filter = "all" | "active" | "failed";
const kindIcon: Record<string, IconName> = { import: "upload", index: "layers", export: "download", stats: "chart", preannotate: "pen", kb_import: "book", kb_summarize: "spark", kb_extract: "term" };

function Actions({ job, onAct, pending }: { job: Job; onAct: (a: "cancel" | "retry") => void; pending: boolean }) {
  return (
    <span className="row" style={{ gap: 4 }} onClick={(e) => e.stopPropagation()}>
      {isActiveJob(job) && (
        <button className="btn xs" type="button" disabled={pending} onClick={() => onAct("cancel")}>
          取消
        </button>
      )}
      {(job.state === "failed" || job.state === "cancelled") && (
        <button className="btn xs" type="button" disabled={pending} onClick={() => onAct("retry")}>
          <Icon name="retry" size={14} />
          重试
        </button>
      )}
      {hasDownload(job) && (
        <a className="btn xs" href={`/api/jobs/${job.id}/download`}>
          <Icon name="download" size={14} />
          下载
        </a>
      )}
    </span>
  );
}

function resultText(j: Job): React.ReactNode {
  if (!j.result) return null;
  if (j.kind === "export" || typeof j.result.filename === "string") return j.result.rows != null ? `${j.result.filename ?? ""} · ${fmt(j.result.rows)} 行` : (j.result.filename ?? "");
  if (j.kind === "kb_extract") return `新增 ${fmt(Number(j.result.created ?? 0))} 条草稿，跳过 ${fmt(Number(j.result.skipped ?? 0))} 条`;
  if (j.kind === "stats" && j.result.stat_id) return <Link to={`/p/${j.project_id}/stats?stat=${j.result.stat_id}`} onClick={(e) => e.stopPropagation()}>查看结果</Link>;
  return null;
}

function Inspector({ id, projectId, onAct, onClose, pending }: { id: string; projectId: string; onAct: (job: Job, a: "cancel" | "retry") => void; onClose: () => void; pending: boolean }) {
  const job = useJob(id, 2000);
  const hist = useRef<number[]>([]);
  useEffect(() => {
    hist.current = [];
  }, [id]);
  const j = job.data;
  if (j && isActiveJob(j) && hist.current[hist.current.length - 1] !== j.progress.done) hist.current = [...hist.current, j.progress.done].slice(-12);
  const speed = hist.current.map((v, i, a) => (i ? v - a[i - 1] : 0)).slice(1);
  return (
    <aside className="inspector" aria-label="任务详情">
      <div className="card-head">
        <h2 className="sec-title grow">任务详情</h2>
        <span className="mono small muted">#{id.slice(0, 8)}</span>
        <button className="btn ghost icon xs" type="button" aria-label="关闭任务详情" onClick={onClose}>
          <Icon name="x" size={14} />
        </button>
      </div>
      <ErrorAlert error={job.error} style={{ margin: 16 }} />
      {j && (
        <>
          <div className="insp-body">
            <div className="row">
              <span className="jtype">
                <span className="ji">
                  <Icon name={kindIcon[j.kind] ?? "clock"} />
                </span>
                {jobKindLabels[j.kind] ?? j.kind}
              </span>
              <div className="grow" />
              <JobStateTag state={j.state} />
            </div>
            <Progress done={j.progress.done} total={j.progress.total} state={j.state} />
            <div className="row small muted">
              <span className="num grow">{progressText(j)}</span>
              {j.progress.total ? <span className="num">{Math.round((j.progress.done / j.progress.total) * 100)}%</span> : null}
            </div>
            {j.error && (
              <div className="alert err">
                <Icon name="alert" size={14} />
                <span>
                  {j.error.message}
                  <span className="err-code">{j.error.code}</span>
                </span>
              </div>
            )}
          </div>
          <div className="insp-body">
            <dl className="kv">
              <dt>编号</dt>
              <dd className="mono">{j.id}</dd>
              {j.progress.message && (
                <>
                  <dt>当前</dt>
                  <dd>{j.progress.message}</dd>
                </>
              )}
              <dt>开始</dt>
              <dd className="mono">{fmtTime(j.created_at)}</dd>
              {j.finished_at && (
                <>
                  <dt>结束</dt>
                  <dd className="mono">{fmtTime(j.finished_at)}</dd>
                  <dt>用时</dt>
                  <dd className="mono">{fmtDuration(Date.parse(j.finished_at) - Date.parse(j.created_at))}</dd>
                </>
              )}
              {(j.kind === "export" || j.kind === "kb_extract" || typeof j.result?.filename === "string") && j.result && (
                <>
                  <dt>产物</dt>
                  <dd>{resultText(j)}</dd>
                </>
              )}
              {j.kind === "stats" && j.result?.stat_id && (
                <>
                  <dt>结果</dt>
                  <dd>
                    <Link to={`/p/${projectId}/stats?stat=${j.result.stat_id}`}>打开统计结果</Link>
                  </dd>
                </>
              )}
            </dl>
            {isActiveJob(j) && speed.length > 1 && (
              <div className="row">
                <span className="small muted grow">处理速度</span>
                <Sparkline values={speed} w={120} h={24} label="处理速度" />
              </div>
            )}
          </div>
          <div className="insp-foot">
            <Actions job={j} pending={pending} onAct={(a) => onAct(j, a)} />
          </div>
        </>
      )}
    </aside>
  );
}

export default function Jobs() {
  const projectId = useProjectId();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<Filter>("all");
  const selected = params.get("job");
  const jobs = useQuery({
    queryKey: ["jobs", projectId, "page", page],
    queryFn: () => api.get<Page<Job>>(`/projects/${projectId}/jobs`, { page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items.some(isActiveJob) ? 2000 : false),
    meta: { background: true },
  });
  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "cancel" | "retry" }) => api.post<Job>(`/jobs/${id}/${action}`),
    onSuccess: (j, v) => {
      qc.invalidateQueries({ queryKey: ["jobs", projectId] });
      qc.invalidateQueries({ queryKey: ["job"] });
      qc.invalidateQueries({ queryKey: ["corpora", projectId] });
      if (v.action === "retry") setParams({ job: j.id });
    },
    onError: (e) => message.error(errorText(e)),
  });

  const all = jobs.data?.items ?? [];
  const today = new Date().toDateString();
  const sums: [string, number, IconName, string][] = [
    ["运行中", all.filter((j) => j.state === "running").length, "play", "t-run"],
    ["排队", all.filter((j) => j.state === "queued").length, "clock", "t-gray"],
    ["失败", all.filter((j) => j.state === "failed").length, "alert", "t-err"],
    ["今日完成", all.filter((j) => j.state === "succeeded" && j.finished_at && new Date(j.finished_at).toDateString() === today).length, "check", "t-ok"],
  ];
  const shown = filter === "active" ? all.filter(isActiveJob) : filter === "failed" ? all.filter((j) => j.state === "failed") : all;

  return (
    <>
      <PageHeader
        title="任务"
        crumbs={1}
        busy={all.some(isActiveJob)}
        actions={
          <Segmented<Filter>
            size="small"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "全部" },
              { value: "active", label: "运行中" },
              { value: "failed", label: "失败" },
            ]}
          />
        }
      />
      <div className="content">
        <section className="grid-4" aria-label="概况">
          {sums.map(([label, n, icon, cls]) => (
            <div className="card sumcard" key={label}>
              <span className={`si tag ${cls}`}>
                <Icon name={icon} />
              </span>
              <div>
                <div className="stat-label">{label}</div>
                <div className="count">{fmt(n)}</div>
              </div>
            </div>
          ))}
        </section>
        <div className="row" style={{ alignItems: "flex-start", gap: 20 }}>
          <section className="card grow">
            <ErrorAlert error={jobs.error} style={{ margin: 16 }} />
            <Table<Job>
              className="jobs"
              rowKey="id"
              loading={jobs.isPending}
              dataSource={shown}
              locale={{ emptyText: <span className="muted">暂无任务</span> }}
              rowClassName={(j) => (j.id === selected ? "ant-table-row-selected" : "")}
              onRow={(j) => ({ onClick: () => setParams({ job: j.id }), style: { cursor: "pointer" } })}
              expandable={{
                showExpandColumn: false,
                expandedRowKeys: shown.filter((j) => j.state === "failed" && j.error).map((j) => j.id),
                expandedRowRender: (j) => (
                  <div className="err-line">
                    <Icon name="alert" size={14} />
                    {j.error?.message}
                    <span className="err-code">{j.error?.code}</span>
                  </div>
                ),
              }}
              pagination={{ current: page, pageSize: PAGE_SIZE, total: jobs.data?.total ?? 0, showSizeChanger: false, onChange: setPage, hideOnSinglePage: true }}
              columns={[
                {
                  title: "类型",
                  render: (_, j) => (
                    <span className="jtype">
                      <span className="ji">
                        <Icon name={kindIcon[j.kind] ?? "clock"} />
                      </span>
                      {jobKindLabels[j.kind] ?? j.kind}
                      <span className="mono small muted">#{j.id.slice(0, 8)}</span>
                    </span>
                  ),
                },
                { title: "状态", width: 100, render: (_, j) => <JobStateTag state={j.state} /> },
                {
                  title: "进度",
                  width: 240,
                  render: (_, j) => (
                    <div className="jprog">
                      <Progress done={j.progress.done} total={j.progress.total} state={j.state} />
                      <div className="row">
                        <span className="num ellipsis">{j.state === "succeeded" && resultText(j) ? resultText(j) : progressText(j)}</span>
                        {j.progress.total ? <span className="num">{Math.round((j.progress.done / j.progress.total) * 100)}%</span> : null}
                      </div>
                    </div>
                  ),
                },
                { title: "开始", width: 170, render: (_, j) => <span className="small muted">{fmtTime(j.created_at)}</span> },
                { title: "", width: 150, render: (_, j) => <Actions job={j} pending={act.isPending} onAct={(a) => act.mutate({ id: j.id, action: a })} /> },
              ]}
            />
          </section>
          {selected && <Inspector id={selected} projectId={projectId} pending={act.isPending} onAct={(j, a) => act.mutate({ id: j.id, action: a })} onClose={() => setParams({})} />}
        </div>
      </div>
    </>
  );
}
