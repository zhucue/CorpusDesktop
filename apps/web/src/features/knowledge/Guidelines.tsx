import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Popconfirm, Select } from "antd";
import { useState } from "react";
import { api, errorText, type KbDocument } from "../../api";
import { Empty, ErrorAlert, Skeleton } from "../../components/common";
import { Markdown } from "../../components/common/Markdown";
import { Icon } from "../../components/Icon";
import { fmtShortTime } from "../../lib/format";
import { useLabelSets } from "../annotate/data";
import { useKbDocument } from "./data";

function GuideEditor({ doc, editable }: { doc: KbDocument; editable: boolean }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const labelSets = useLabelSets(doc.project_id);
  const [title, setTitle] = useState(doc.title);
  const [body, setBody] = useState(doc.body ?? "");
  const [labelSet, setLabelSet] = useState<string | undefined>(doc.meta?.label_set_id || undefined);
  const [editing, setEditing] = useState(false);
  const dirty = title !== doc.title || body !== (doc.body ?? "") || (labelSet ?? "") !== (doc.meta?.label_set_id ?? "");
  const save = useMutation({
    mutationFn: () =>
      api.patch<KbDocument>(`/kb/documents/${doc.id}`, {
        title: title.trim() || "未命名规范",
        body,
        meta: { ...doc.meta, label_set_id: labelSet ?? null },
      }),
    onSuccess: (d) => {
      qc.setQueryData<KbDocument>(["kb-doc", doc.id], (old) => ({ ...(old ?? doc), ...d, body }));
      void qc.invalidateQueries({ queryKey: ["kb-docs", doc.project_id] });
      message.success("已保存");
      setEditing(false);
    },
    onError: (e) => message.error(errorText(e)),
  });
  const del = useMutation({
    mutationFn: () => api.del(`/kb/documents/${doc.id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["kb-docs", doc.project_id] }),
    onError: (e) => message.error(errorText(e)),
  });
  const ls = (labelSets.data ?? []).find((l) => l.id === labelSet);

  return (
    <article className="card">
      <div className="card-head">
        {editing ? (
          <input className="note-title" value={title} aria-label="规范标题" onChange={(e) => setTitle(e.target.value)} />
        ) : (
          <h2 className="grow" style={{ textTransform: "none", letterSpacing: 0, fontSize: 14, color: "var(--text)" }}>
            {doc.title}
          </h2>
        )}
        {editable && !editing && (
          <button className="btn xs" type="button" onClick={() => setEditing(true)}>
            <Icon name="edit" size={14} />
            编辑
          </button>
        )}
        {editable && (
          <Popconfirm title="删除这份规范？" okText="删除" cancelText="取消" onConfirm={() => del.mutate()}>
            <button className="btn xs ghost danger" type="button" aria-label="删除规范">
              <Icon name="trash" size={14} />
            </button>
          </Popconfirm>
        )}
      </div>
      <div className="card-pad col gap-12">
        <div className="row">
          <span className="label">标签集</span>
          {editing ? (
            <Select
              size="small"
              allowClear
              style={{ width: 240 }}
              placeholder="不关联"
              value={labelSet}
              onChange={setLabelSet}
              loading={labelSets.isPending}
              options={(labelSets.data ?? []).map((l) => ({ value: l.id, label: `${l.name}（${l.labels.length} 个标签）` }))}
              aria-label="关联标签集"
            />
          ) : (
            <span className="sm">{ls ? `「${ls.name}」· ${ls.labels.length} 个标签` : <span className="muted">未关联</span>}</span>
          )}
        </div>
        {editing ? (
          <div className="md-split">
            <textarea className="md-input" aria-label="规范正文" value={body} placeholder="Markdown" onChange={(e) => setBody(e.target.value)} />
            <div className="md-preview">{body.trim() ? <Markdown text={body} /> : <span className="muted sm">预览</span>}</div>
          </div>
        ) : body.trim() ? (
          <Markdown text={body} />
        ) : (
          <span className="muted sm">空规范</span>
        )}
      </div>
      {editing && (
        <div className="card-foot">
          <span className="small muted">更新于 {fmtShortTime(doc.updated_at)}</span>
          <div className="grow" />
          <button
            className="btn s"
            type="button"
            onClick={() => {
              setTitle(doc.title);
              setBody(doc.body ?? "");
              setLabelSet(doc.meta?.label_set_id || undefined);
              setEditing(false);
            }}
          >
            取消
          </button>
          <button className="btn s p" type="button" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
            保存
          </button>
        </div>
      )}
    </article>
  );
}

function GuidePane({ id, editable }: { id: string; editable: boolean }) {
  const doc = useKbDocument(id);
  if (doc.error) return <ErrorAlert error={doc.error} />;
  if (!doc.data) return <div className="card"><Skeleton rows={6} /></div>;
  return <GuideEditor key={doc.data.id} doc={doc.data} editable={editable} />;
}

export default function GuidelinesTab({
  projectId,
  docs,
  editable,
  selected,
  onSelect,
}: {
  projectId: string;
  docs: KbDocument[];
  editable: boolean;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const labelSets = useLabelSets(projectId);
  const guides = docs.filter((d) => d.kind === "guideline");
  const current = selected && guides.some((g) => g.id === selected) ? selected : (guides[0]?.id ?? null);
  const create = useMutation({
    mutationFn: () => api.post<KbDocument>(`/projects/${projectId}/kb/documents`, { kind: "guideline", title: "未命名规范", body: "" }),
    onSuccess: (d) => {
      qc.setQueryData<KbDocument[]>(["kb-docs", projectId], (old) => (old ? [d, ...old] : old));
      void qc.invalidateQueries({ queryKey: ["kb-docs", projectId] });
      onSelect(d.id);
    },
    onError: (e) => message.error(errorText(e)),
  });
  return (
    <section className="kb-split">
      <div className="card" style={{ padding: 10 }}>
        {editable && (
          <button className="btn s p" type="button" style={{ width: "100%", marginBottom: 6 }} disabled={create.isPending} onClick={() => create.mutate()}>
            <Icon name="plus" size={14} />
            新建规范
          </button>
        )}
        {guides.length === 0 && <div className="empty sm">暂无规范</div>}
        {guides.map((g) => {
          const ls = (labelSets.data ?? []).find((l) => l.id === g.meta?.label_set_id);
          return (
            <button key={g.id} className={`list-item ${g.id === current ? "on" : ""}`} type="button" style={{ width: "100%" }} onClick={() => onSelect(g.id)}>
              <span className="grow" style={{ textAlign: "left" }}>
                <span className="li-title ellipsis" style={{ display: "block" }}>
                  {g.title}
                </span>
                <span className="small muted">{ls ? `标签集「${ls.name}」· ${ls.labels.length} 个标签` : "未关联标签集"}</span>
              </span>
            </button>
          );
        })}
      </div>
      {current ? <GuidePane key={current} id={current} editable={editable} /> : <Empty icon="filetext" text="新建一份标注规范，关联到标签集" />}
    </section>
  );
}
