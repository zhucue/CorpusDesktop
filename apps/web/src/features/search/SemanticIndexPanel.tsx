import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Select } from "antd";
import { useState } from "react";
import { api, errorText } from "../../api";
import { ErrorAlert, Progress } from "../../components/common";
import { Icon } from "../../components/Icon";
import { fmt, fmtRelative } from "../../lib/format";
import { estimateText, useBuildSemantic, useSemanticIndex, type SemanticIndex } from "./semantic";

const STATUS: Record<SemanticIndex["status"], { label: string; cls: string }> = {
  none: { label: "未建", cls: "t-gray" },
  building: { label: "建立中", cls: "t-run" },
  ready: { label: "已建", cls: "t-ok" },
  stale: { label: "已过期", cls: "t-warn" },
  failed: { label: "失败", cls: "t-err" },
};

const ALL = "";

/** 语义索引 status of one corpus with 建语义索引 / 重建 (owner, editor; built-in corpora: admins), progress and errors.
 * Corpora with several document languages (parallel corpora) may index one language. */
export function SemanticIndexPanel({ corpusId, projectId }: { corpusId: string; projectId: string }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const q = useSemanticIndex(corpusId);
  const build = useBuildSemantic(corpusId, projectId);
  const [pick, setPick] = useState<string | null>(null);
  const cancel = useMutation({
    mutationFn: (jobId: string) => api.post(`/jobs/${jobId}/cancel`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["semantic-index", corpusId] }),
    onError: (e) => message.error(errorText(e)),
  });
  if (q.error) return <ErrorAlert error={q.error} />;
  const s = q.data;
  if (!s) return null;
  const v = STATUS[s.status];
  const langs = Object.entries(s.languages ?? {});
  const language = pick ?? s.language ?? ALL;
  const target = language ? (s.languages[language] ?? 0) : s.sentences;
  const tooLarge = target > s.max_sentences;
  const job = s.job;
  const running = s.status === "building" && job;
  const langLabel = s.language ? `${s.language} · ` : "";
  return (
    <div className="col" style={{ gap: 8 }} role="group" aria-label="语义索引">
      <div className="row wrap" style={{ gap: 8 }}>
        <span className="stat-label">语义索引</span>
        <span className={`tag ${v.cls}`}>
          {s.status === "building" && <span className="dot pulse" />}
          {v.label}
        </span>
        {s.status === "ready" && (
          <span className="small sub num">
            {langLabel}
            {fmt(s.indexed ?? 0)} 句{s.built_at ? ` · ${fmtRelative(s.built_at)}` : ""}
          </span>
        )}
        {s.status === "stale" && <span className="small sub">{s.error ?? `文档有增删：索引 ${langLabel}${fmt(s.indexed ?? 0)} 句，需重建`}</span>}
        {running && (
          <span className="small sub num">
            {job.state === "queued" ? `排队中${job.queue_ahead ? `，前面 ${job.queue_ahead} 个任务` : ""}` : `${fmt(job.progress.done)} / ${fmt(job.progress.total ?? target)} 句`}
          </span>
        )}
        <div className="grow" />
        {running && s.can_build && (
          <button className="btn xs" type="button" disabled={cancel.isPending} onClick={() => cancel.mutate(job.id)}>
            取消
          </button>
        )}
        {s.can_build && s.status !== "building" && (
          <>
            {langs.length > 1 && (
              <Select
                size="small"
                value={language}
                onChange={setPick}
                style={{ width: 170 }}
                aria-label="建索引的语言"
                options={[{ value: ALL, label: `全部语言 · ${fmt(s.sentences)} 句` }, ...langs.map(([l, n]) => ({ value: l, label: `${l} · ${fmt(n)} 句` }))]}
              />
            )}
            <span className="small sub num">
              {langs.length > 1 ? "" : `${fmt(target)} 句 · `}预计 {estimateText(target / (s.rate || 200))}
            </span>
            <button className="btn xs" type="button" disabled={tooLarge || build.isPending} onClick={() => build.mutate(language || undefined)}>
              <Icon name="databasezap" size={14} />
              {s.status === "none" ? "建语义索引" : "重建语义索引"}
            </button>
          </>
        )}
        {!s.can_build && (s.status === "none" || s.status === "failed") && <span className="small sub num">{fmt(s.sentences)} 句</span>}
      </div>
      {running && job.state === "running" && <Progress done={job.progress.done} total={job.progress.total} state="running" thin />}
      {s.status === "ready" && s.error && (
        <div className="alert warn" role="status">
          <Icon name="alert" size={14} />
          <span className="grow">{s.error}</span>
        </div>
      )}
      {s.status === "failed" && s.error && (
        <div className="alert err" role="alert">
          <Icon name="alert" size={14} />
          <span className="grow">{s.error}</span>
        </div>
      )}
      {tooLarge && s.can_build && s.status !== "building" && (
        <span className="small" style={{ color: "var(--error)" }}>
          共 {fmt(target)} 句，超过语义索引上限 {fmt(s.max_sentences)} 句
        </span>
      )}
      <ErrorAlert error={build.error} />
    </div>
  );
}
