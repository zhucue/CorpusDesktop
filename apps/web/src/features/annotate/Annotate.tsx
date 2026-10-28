import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { App, Dropdown, Popconfirm } from "antd";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api, errorText, type Job, type Layer, type LayerDocument, type LayerKind } from "../../api";
import { Empty, ErrorAlert, exportTip, Skeleton, Tip } from "../../components/common";
import { Icon } from "../../components/Icon";
import { layerIcon } from "../../components/iconSets";
import { PageHeader } from "../../components/shell/AppShell";
import { useShell } from "../../components/shell/shell";
import { canEdit, useCorpora, useJob, useJobCreated, useMe, useProject, useProjectId } from "../../lib/data";
import { fmt } from "../../lib/format";
import { canWriteLayer, listOf, useLayers } from "./data";
import { failedRetryBody, layerPct, modelName } from "./model";
import NewLayerDialog, { kindLabels } from "./NewLayerDialog";
import { KappaGauge, meanKappa, useAgreement } from "./Agreement";
import AlignWorkspace from "./AlignWorkspace";
import SpanWorkspace from "./SpanWorkspace";
import Workspace from "./Workspace";
import "./annotate.css";

const FORMAT_NAMES: Record<string, string> = { conllu: "CoNLL-U", brat: "brat standoff", json: "JSON", tmx: "TMX", xlsx: "XLSX 统计" };
const EXPORTS: Record<LayerKind, string[]> = { pos: ["conllu", "json"], dep: ["conllu", "json"], span: ["brat", "json", "xlsx"], relation: ["brat", "json"], alignment: ["tmx", "json"] };
/** What an export of the layer contains (services/worker/annot_tasks.EXPORT_SCOPE). */
export const EXPORT_SCOPE: Record<LayerKind, string> = {
  pos: "已确认、已修改的词取人工值；未校对的词取系统层自动值（语料自带，或预标写入的 jieba / Stanza 结果）",
  dep: "已确认、已修改的词取人工值；未校对的词取系统层自动值（语料自带，或预标写入的 jieba / Stanza 结果）",
  span: "已确认、已修改的片段；多人层为各标注者一致或已仲裁的片段；不含未校对的建议",
  relation: "已确认、已修改的关系及其端点片段，端点未确认时一并导出并标为未确认；多人层为一致或已仲裁的关系",
  alignment: "已确认、已修改的对齐和未校对的导入句对；多人层为一致或已仲裁的结果",
};
const FORMAT_NOTE: Record<string, string> = { conllu: "sent_id = 文档名-句号", tmx: "词对序号从 1 起", brat: "码点偏移" };
const COLLAPSE_KEY = "annotate.layers.collapsed";

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
  onRetry: (body?: object) => void;
}) {
  const busy = layer.status === "preannotating" || layer.status === "created";
  const job = useJob(busy ? layer.job_id : null, 2000);
  const pct = layerPct(layer.progress);
  const done = layer.progress.confirmed + layer.progress.modified + layer.progress.rejected;
  const jp = job.data?.progress;
  const multi = layer.mode === "multi";
  const agreement = useAgreement(layer.id, multi && layer.status === "ready");
  return (
    <div className={`layer-item ${on ? "on" : ""}`}>
      <button className={`layer ${on ? "on" : ""}`} type="button" aria-current={on ? "true" : undefined} onClick={onSelect} aria-label={`${layer.name}，${pct}%`}>
        <span className="layer-row">
          <ProgressRing pct={pct} ok={pct === 100} />
          <span className="grow col" style={{ gap: 3, minWidth: 0 }}>
            <span className="li-title">
              <span className="ellipsis">{layer.name}</span>
              <span className="tag t-gray" style={{ marginLeft: "auto" }}>
                <Icon name={layerIcon[layer.kind]} size={12} />
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
                <span className="ellipsis mono" title={`${layer.corpus_name} · ${modelName(layer.source_model)}`}>
                  {modelName(layer.source_model)}
                </span>
              )}
              <span className="num" style={{ whiteSpace: "nowrap", flexShrink: 0 }}>
                {fmt(done)} / {fmt(layer.progress.total)}
              </span>
            </span>
            <span className="small muted ellipsis">{multi ? `${layer.corpus_name} · ${layer.annotators?.length ?? 0} 名标注者` : layer.corpus_name}</span>
          </span>
        </span>
        {multi && agreement.data && (
          <span className="layer-gauge">
            <KappaGauge value={meanKappa(agreement.data)} annotators={agreement.data.annotators.length} />
          </span>
        )}
      </button>
      {!!layer.progress.failed_sentences?.length && layer.status !== "failed" && (
        <div className="layer-err">
          <span className="grow">{layer.progress.failed_sentences.length} 句预标失败</span>
          {canManage && !busy && failedRetryBody(layer.progress.failed_sentences) && (
            <button className="btn xs" type="button" onClick={() => onRetry(failedRetryBody(layer.progress.failed_sentences)!)}>
              <Icon name="retry" size={14} />
              重试这些句
            </button>
          )}
        </div>
      )}
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
  const [layersCollapsed, setCollapsedState] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const setLayersCollapsed = (v: boolean) => {
    setCollapsedState(v);
    try {
      localStorage.setItem(COLLAPSE_KEY, v ? "1" : "0");
    } catch {
      /* per-viewer convenience only */
    }
  };

  const role = project.data?.role;
  const canManage = canEdit(project.data);
  const me = useMe();
  const canAnnotateRole = role === "owner" || role === "editor" || role === "annotator";
  const list = layers.data ?? [];
  const layerParam = params.get("layer");
  const docParam = params.get("doc");

  // A link with only ?doc= (DependencyTree / SpanView "在标注中打开") opens the first layer that has that document,
  // layers of ?kind= first (dependency layers by default); ?kind= alone opens the first layer of that kind.
  const probe = !layerParam && !!docParam && list.length > 0;
  const kindParam = params.get("kind");
  const prefer = (k: string) => (kindParam ? (k === kindParam || (kindParam === "span" && k === "relation") ? 0 : 1) : k === "dep" ? 0 : 1);
  const ordered = useMemo(() => [...list].sort((a, b) => prefer(a.kind) - prefer(b.kind)), [list, kindParam]); // eslint-disable-line react-hooks/exhaustive-deps
  const docLists = useQueries({
    queries: (probe ? ordered : []).map((l) => ({
      queryKey: ["layer-docs", l.id],
      queryFn: async () => listOf(await api.get<LayerDocument[] | { items: LayerDocument[] }>(`/layers/${l.id}/documents`)),
    })),
  });
  const probed = probe ? ordered.find((_, i) => docLists[i]?.data?.some((d) => d.document_id === docParam)) : undefined;
  const probing = probe && !probed && docLists.some((q) => q.isPending);

  const layer = list.find((l) => l.id === layerParam) ?? probed ?? (probing ? undefined : ((kindParam ? list.find((l) => l.kind === kindParam) : undefined) ?? list[0]));

  function selectLayer(id: string) {
    setParams({ layer: id }, { replace: false });
  }

  const preannotate = useMutation({
    mutationFn: ({ id, body }: { id: string; body?: object }) => api.post<Job>(`/layers/${id}/preannotate`, body ?? {}),
    onSuccess: (job) => {
      jobCreated(projectId);
      qc.invalidateQueries({ queryKey: ["layers", projectId] });
      message.success(`已提交预标注任务 #${job.id.slice(0, 8)}`);
    },
    onError: (e) => message.error(errorText(e)),
  });

  const exportJob = useMutation({
    mutationFn: ({ id, format, annotators }: { id: string; format: string; annotators?: boolean }) =>
      api.post<Job>(`/layers/${id}/export`, { format, ...(annotators ? { annotators: true } : {}) }),
    onSuccess: (_, v) => {
      jobCreated(projectId);
      message.success(
        <span>
          已提交导出任务：{FORMAT_NAMES[v.format] ?? v.format}
          {v.annotators ? "（含各标注者原始标注）" : ""}，<Link to={`/p/${projectId}/jobs`}>查看任务</Link>
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

  // Collapsed, the list shows only the current layer; expanded it scrolls on its own (many layers never push the editor away).
  const shownLayers = layersCollapsed && layer ? list.filter((l) => l.id === layer.id) : list;
  const layerList = (
    <section className="card layer-card" aria-label="标注层">
      <div className="row between" style={{ padding: "2px 4px 8px" }}>
        <h2>
          标注层 <span className="small muted num">{fmt(list.length)}</span>
        </h2>
        <span className="row gap-4">
          {list.length > 1 && (
            <Tip title={layersCollapsed ? "展开全部标注层" : "只显示当前层"}>
              <button className="btn ghost icon xs" type="button" aria-label={layersCollapsed ? "展开标注层" : "收起标注层"} aria-expanded={!layersCollapsed} onClick={() => setLayersCollapsed(!layersCollapsed)}>
                <Icon name={layersCollapsed ? "down" : "up"} size={14} />
              </button>
            </Tip>
          )}
          {canManage && (
            <Tip title="新建标注层">
              <button className="btn ghost icon xs" type="button" aria-label="新建标注层" onClick={() => setCreating(true)}>
                <Icon name="plus" size={14} />
              </button>
            </Tip>
          )}
        </span>
      </div>
      <div className="col gap-4 layer-list">
        {shownLayers.map((l) => (
          <LayerItem
            key={l.id}
            layer={l}
            on={l.id === layer?.id}
            canManage={canManage}
            onSelect={() => selectLayer(l.id)}
            onDelete={() => del.mutate(l.id)}
            onRetry={(body) => preannotate.mutate({ id: l.id, body })}
          />
        ))}
      </div>
    </section>
  );

  const busy = layer && (layer.status === "preannotating" || layer.status === "created");
  const canAnnotate = !!layer && canWriteLayer(layer, me.data?.id, role);
  const readOnlyNote = canAnnotateRole ? "只有创建者和名单内的标注者可以修改此层" : "查看者只读";

  return (
    <>
      <PageHeader
        title="标注"
        crumbs={1}
        actions={
          <>
            {canManage &&
              (layer?.mode === "multi" ? (
                // Every annotator gets the same suggestions: agreement measured afterwards is no longer independent.
                <Popconfirm
                  title="多人层预标"
                  description={<span style={{ display: "block", maxWidth: 280 }}>预标会给每位标注者铺同一份模型建议，影响独立标注和一致性。</span>}
                  okText="仍然预标"
                  cancelText="取消"
                  disabled={!!busy || preannotate.isPending}
                  onConfirm={() => preannotate.mutate({ id: layer.id })}
                >
                  <button className="btn s" type="button" disabled={!!busy || preannotate.isPending}>
                    <Icon name="spark" size={14} />
                    <span className="lbl">预标注</span>
                  </button>
                </Popconfirm>
              ) : (
                <button className="btn s" type="button" disabled={!layer || !!busy || preannotate.isPending} onClick={() => layer && preannotate.mutate({ id: layer.id })}>
                  <Icon name="spark" size={14} />
                  <span className="lbl">预标注</span>
                </button>
              ))}
            <Dropdown
              trigger={["click"]}
              disabled={!layer || exportJob.isPending}
              menu={{
                style: { maxWidth: 340 },
                items: layer
                  ? [
                      {
                        type: "group",
                        label: <span className="export-scope">{EXPORT_SCOPE[layer.kind]}</span>,
                        children: EXPORTS[layer.kind].map((f) => {
                          const note = f === "tmx" && layer.level !== "word" ? undefined : FORMAT_NOTE[f];
                          return { key: f, label: note ? `${FORMAT_NAMES[f]} · ${note}` : FORMAT_NAMES[f] };
                        }),
                      },
                      ...(layer.mode === "multi" ? [{ type: "divider" as const }, { key: "json+annotators", label: "JSON · 另附各标注者原始标注" }] : []),
                    ]
                  : [],
                onClick: ({ key }) => layer && exportJob.mutate({ id: layer.id, format: key === "json+annotators" ? "json" : key, annotators: key === "json+annotators" }),
              }}
            >
              <button className="btn s" type="button" disabled={!layer || exportJob.isPending} title={exportTip("导出所选层")}>
                <Icon name="download" size={14} />
                <span className="lbl">导出</span>
                <Icon name="down" size={14} />
              </button>
            </Dropdown>
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
              <Icon name="highlighter" />
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
                  <Icon name="library" size={14} />
                  先导入语料
                </Link>
              )}
            </div>
          </section>
        ) : layer ? (
          layer.kind === "span" || layer.kind === "relation" ? (
            <SpanWorkspace key={layer.id} layer={layer} layers={list} projectId={projectId} canAnnotate={canAnnotate} readOnlyNote={readOnlyNote} canManage={canManage} leftTop={layerList} />
          ) : layer.kind === "alignment" ? (
            <AlignWorkspace key={layer.id} layer={layer} layers={list} projectId={projectId} canAnnotate={canAnnotate} readOnlyNote={readOnlyNote} canManage={canManage} leftTop={layerList} />
          ) : (
            <Workspace key={layer.id} layer={layer} projectId={projectId} canAnnotate={canAnnotate} readOnlyNote={readOnlyNote} leftTop={layerList} />
          )
        ) : (
          <Empty icon="highlighter" text="选择标注层" />
        )}
      </div>
      <NewLayerDialog
        open={creating}
        projectId={projectId}
        initialCorpus={currentCorpus}
        onClose={() => setCreating(false)}
        onCreated={(l) => {
          setCreating(false);
          message.success(l.job_id || l.status === "created" ? `已新建标注层「${l.name}」，预标任务已提交` : `已新建标注层「${l.name}」`);
          selectLayer(l.id);
        }}
      />
    </>
  );
}
