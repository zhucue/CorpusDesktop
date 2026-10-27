import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { App, Popconfirm } from "antd";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api, errorText, type Job, type Layer, type LayerDocument } from "../../api";
import { Empty, ErrorAlert, Skeleton, Tip } from "../../components/common";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/shell/AppShell";
import { useShell } from "../../components/shell/shell";
import { canEdit, useCorpora, useJob, useJobCreated, useProject, useProjectId } from "../../lib/data";
import { fmt } from "../../lib/format";
import { listOf, useLayers } from "./data";
import { layerPct } from "./model";
import NewLayerDialog, { kindLabels } from "./NewLayerDialog";
import Workspace from "./Workspace";
import "./annotate.css";

export function ProgressRing({ pct, ok }: { pct: number; ok?: boolean }) {
  return (
    <span className={`pring ${ok ? "ok" : ""}`} style={{ ["--v" as string]: pct }} role="img" aria-label={`完成 ${pct}%`}>
      <svg viewBox="0 0 40 40" aria-hidden>
        <circle className="bg" cx="20" cy="20" r="16" />
        <circle className="fg" cx="20" cy="20" r="16" pathLength={100} />
      </svg>
      <b>{pct}%</b>
    </span>
  );
}

function LayerItem({
  layer,
  on,
  canManage,
  onSelect,
  onDelete,
  onRetry,
}: {
  layer: Layer;
  on: boolean;
  canManage: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onRetry: () => void;
}) {
  const busy = layer.status === "preannotating" || layer.status === "created";
  const job = useJob(busy ? layer.job_id : null, 2000);
  const pct = layerPct(layer.progress);
  const done = layer.progress.confirmed + layer.progress.modified + layer.progress.rejected;
  const jp = job.data?.progress;
  return (
    <div className={`layer-item ${on ? "on" : ""}`}>
      <button className={`layer ${on ? "on" : ""}`} type="button" aria-current={on ? "true" : undefined} onClick={onSelect} aria-label={`${layer.name}，${pct}%`}>
        <span className="layer-row">
          <ProgressRing pct={pct} ok={pct === 100} />
          <span className="grow col" style={{ gap: 3, minWidth: 0 }}>
            <span className="li-title">
              <span className="ellipsis">{layer.name}</span>
              <span className="tag t-gray" style={{ marginLeft: "auto" }}>
                {kindLabels[layer.kind]}
              </span>
            </span>
            <span className="row between small muted" style={{ gap: 6 }}>
              {busy ? (
                <span className="row gap-4">
                  <span className="spin" style={{ width: 10, height: 10, color: "var(--accent)" }} />
                  预标中{jp?.total ? ` ${fmt(jp.done)} / ${fmt(jp.total)} 篇` : ""}
                </span>
              ) : layer.status === "failed" ? (
                <span className="err-text">预标失败</span>
              ) : (
                <span className="ellipsis mono" title={`${layer.corpus_name} · ${layer.source_model}`}>
                  {layer.source_model}
                </span>
              )}
              <span className="num">
                {fmt(done)} / {fmt(layer.progress.total)}
              </span>
            </span>
            <span className="small muted ellipsis">{layer.corpus_name}</span>
          </span>
        </span>
      </button>
      {layer.status === "failed" && (
        <div className="layer-err">
          <span className="grow">{layer.error ?? "预标任务失败"}</span>
          {canManage && (
            <button className="btn xs" type="button" onClick={onRetry}>
              <Icon name="retry" size={14} />
              重试
            </button>
          )}
        </div>
      )}
      {canManage && (
        <Popconfirm title={`删除标注层「${layer.name}」？`} description="该层的全部标注一并删除。" okText="删除" okButtonProps={{ danger: true }} cancelText="取消" onConfirm={onDelete}>
          <button className="btn ghost icon xs layer-del" type="button" aria-label={`删除 ${layer.name}`}>
            <Icon name="trash" size={14} />
          </button>
        </Popconfirm>
      )}
    </div>
  );
}

export default function Annotate() {
  const projectId = useProjectId();
  const project = useProject();
  const shell = useShell();
  const corpora = useCorpora(projectId);
  const layers = useLayers(projectId);
  const qc = useQueryClient();
  const { message } = App.useApp();
  const jobCreated = useJobCreated();
  const [params, setParams] = useSearchParams();
  const [creating, setCreating] = useState(false);

  const role = project.data?.role;
  const canManage = canEdit(project.data);
  const canAnnotate = role === "owner" || role === "editor" || role === "annotator";
  const list = layers.data ?? [];
  const layerParam = params.get("layer");
  const docParam = params.get("doc");

  // A link with only ?doc= (DependencyTree "在标注中打开") opens the first layer that has that document, dependency layers first.
  const probe = !layerParam && !!docParam && list.length > 0;
  const ordered = useMemo(() => [...list].sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "dep" ? -1 : 1)), [list]);
  const docLists = useQueries({
    queries: (probe ? ordered : []).map((l) => ({
      queryKey: ["layer-docs", l.id],
      queryFn: async () => listOf(await api.get<LayerDocument[] | { items: LayerDocument[] }>(`/layers/${l.id}/documents`)),
    })),
  });
  const probed = probe ? ordered.find((_, i) => docLists[i]?.data?.some((d) => d.document_id === docParam)) : undefined;
  const probing = probe && !probed && docLists.some((q) => q.isPending);

  const layer = list.find((l) => l.id === layerParam) ?? probed ?? (probing ? undefined : list[0]);

  function selectLayer(id: string) {
    setParams({ layer: id }, { replace: false });
  }

  const preannotate = useMutation({
    mutationFn: (id: string) => api.post<Job>(`/layers/${id}/preannotate`, {}),
    onSuccess: (job) => {
      jobCreated(projectId);
      qc.invalidateQueries({ queryKey: ["layers", projectId] });
      message.success(`已提交预标注任务 #${job.id.slice(0, 8)}`);
    },
    onError: (e) => message.error(errorText(e)),
  });

  const exportJob = useMutation({
    mutationFn: (id: string) => api.post<Job>(`/layers/${id}/export`, { format: "conllu" }),
    onSuccess: () => {
      jobCreated(projectId);
      message.success(
        <span>
          已提交导出任务：CoNLL-U，<Link to={`/p/${projectId}/jobs`}>查看任务</Link>
        </span>,
      );
    },
    onError: (e) => message.error(errorText(e)),
  });

  const del = useMutation({
    mutationFn: (id: string) => api.del(`/layers/${id}`),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ["layers", projectId] });
      if (layerParam === id) setParams({}, { replace: true });
      message.success("已删除标注层");
    },
    onError: (e) => message.error(errorText(e)),
  });

  const usableCorpora = (corpora.data?.items ?? []).filter((c) => c.status === "ready" || c.status === "stale");
  const currentCorpus = shell.scopeInfo.corpus?.id;

  const layerList = (
    <section className="card layer-card" aria-label="标注层">
      <div className="row between" style={{ padding: "2px 4px 8px" }}>
        <h2>标注层</h2>
        {canManage && (
          <Tip title="新建标注层">
            <button className="btn ghost icon xs" type="button" aria-label="新建标注层" onClick={() => setCreating(true)}>
              <Icon name="plus" size={14} />
            </button>
          </Tip>
        )}
      </div>
      <div className="col gap-4">
        {list.map((l) => (
          <LayerItem
            key={l.id}
            layer={l}
            on={l.id === layer?.id}
            canManage={canManage}
            onSelect={() => selectLayer(l.id)}
            onDelete={() => del.mutate(l.id)}
            onRetry={() => preannotate.mutate(l.id)}
          />
        ))}
      </div>
    </section>
  );

  const busy = layer && (layer.status === "preannotating" || layer.status === "created");

  return (
    <>
      <PageHeader
        title="标注"
        crumbs={1}
        actions={
          <>
            {canManage && (
              <button className="btn s" type="button" disabled={!layer || !!busy || preannotate.isPending} onClick={() => layer && preannotate.mutate(layer.id)}>
                <Icon name="spark" size={14} />
                <span className="lbl">预标注</span>
              </button>
            )}
            <button className="btn s" type="button" disabled={!layer || exportJob.isPending} onClick={() => layer && exportJob.mutate(layer.id)}>
              <Icon name="download" size={14} />
              <span className="lbl">导出 CoNLL-U</span>
            </button>
            {canManage && (
              <button className="btn s p" type="button" onClick={() => setCreating(true)}>
                <Icon name="plus" size={14} />
                <span className="lbl">新建标注层</span>
              </button>
            )}
          </>
        }
      />
      <div className="content">
        <ErrorAlert error={layers.error} />
        {layers.isPending || probing ? (
          <div className="card">
            <Skeleton rows={6} />
          </div>
        ) : list.length === 0 ? (
          <section className="card empty-hero dotgrid" aria-label="没有标注层">
            <span className="eh-ic">
              <Icon name="pen" />
            </span>
            <h3>还没有标注层</h3>
            <div className="row">
              {usableCorpora.length > 0 ? (
                canManage && (
                  <button className="btn p" type="button" onClick={() => setCreating(true)}>
                    <Icon name="plus" size={14} />
                    新建标注层
                  </button>
                )
              ) : (
                <Link className="btn p" to={`/p/${projectId}/corpora`}>
                  <Icon name="db" size={14} />
                  先导入语料
                </Link>
              )}
            </div>
          </section>
        ) : layer ? (
          <Workspace key={layer.id} layer={layer} projectId={projectId} canAnnotate={canAnnotate} leftTop={layerList} />
        ) : (
          <Empty icon="pen" text="选择标注层" />
        )}
      </div>
      <NewLayerDialog
        open={creating}
        projectId={projectId}
        initialCorpus={currentCorpus}
        onClose={() => setCreating(false)}
        onCreated={(l) => {
          setCreating(false);
          message.success(`已新建标注层「${l.name}」，预标任务已提交`);
          selectLayer(l.id);
        }}
      />
    </>
  );
}
