import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Input, Modal, Popconfirm, Select } from "antd";
import { useRef, useState } from "react";
import { api, errorText, type VocabList } from "../../api";
import { Empty, ErrorAlert, Skeleton } from "../../components/common";
import { Icon } from "../../components/Icon";
import { listOf } from "../../lib/data";
import { fmt } from "../../lib/format";

export const VOCAB_LANGUAGES = [
  { value: "zh", label: "中文 zh" },
  { value: "en", label: "英文 en" },
  { value: "ja", label: "日文 ja" },
  { value: "fr", label: "法文 fr" },
  { value: "de", label: "德文 de" },
  { value: "es", label: "西班牙文 es" },
  { value: "ru", label: "俄文 ru" },
];

/** GET /projects/{id}/vocab-lists: built-in lists (project_id null) and the project's own. */
export function useVocabLists(projectId: string) {
  return useQuery({
    queryKey: ["vocab-lists", projectId],
    queryFn: async () => listOf(await api.get<VocabList[] | { items: VocabList[] }>(`/projects/${projectId}/vocab-lists`)),
  });
}

export function vocabListLabel(l: VocabList): string {
  return `${l.name}${l.project_id === null ? "（内置）" : ""} · ${l.language}`;
}

/** 管理词表: lists with levels and source; editors upload CSV / TXT (`词,等级` per line) and delete project lists. */
export function VocabListsDialog({ open, onClose, projectId, editable }: { open: boolean; onClose: () => void; projectId: string; editable: boolean }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const lists = useVocabLists(projectId);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState<string>("zh");
  const [file, setFile] = useState<File | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const upload = useMutation({
    mutationFn: () => {
      const body = new FormData();
      body.append("file", file!);
      body.append("name", name.trim());
      body.append("language", language);
      return api.post<VocabList & { duplicates?: number }>(`/projects/${projectId}/vocab-lists`, body);
    },
    onSuccess: (l) => {
      const dup = l?.duplicates ? `，${fmt(l.duplicates)} 个重复词只保留第一个等级` : "";
      message.success(`已添加词表 ${l?.name ?? name.trim()}（${fmt(l?.entries ?? 0)} 词${dup}）`);
      setName("");
      setFile(null);
      if (input.current) input.current.value = "";
      void qc.invalidateQueries({ queryKey: ["vocab-lists", projectId] });
    },
  });
  const del = useMutation({
    mutationFn: (id: string) => api.del(`/vocab-lists/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vocab-lists", projectId] }),
    onError: (e) => message.error(errorText(e)),
  });
  const items = lists.data ?? [];

  return (
    <Modal title="管理词表" open={open} onCancel={onClose} footer={null} width={640} destroyOnHidden>
      <div className="col gap-16">
        <ErrorAlert error={lists.error} />
        {lists.isPending && <Skeleton rows={3} />}
        {lists.data && items.length === 0 && <Empty icon="layers" text="暂无词表" />}
        {items.length > 0 && (
          <table className="tbl mid vocab-tbl">
            <thead>
              <tr>
                <th>名称</th>
                <th>语言</th>
                <th>等级</th>
                <th className="r">词条</th>
                <th>来源 · 许可</th>
                <th style={{ width: 44 }} />
              </tr>
            </thead>
            <tbody>
              {items.map((l) => (
                <tr key={l.id}>
                  <td style={{ fontWeight: 500 }}>
                    {l.name}
                    {l.project_id === null && <span className="tag t-info" style={{ marginLeft: 6 }}>内置</span>}
                  </td>
                  <td className="mono">{l.language}</td>
                  <td className="ellipsis" style={{ maxWidth: 160 }} title={l.levels.join("、")}>
                    {l.levels.join("、")}
                  </td>
                  <td className="r num">{l.entries != null ? fmt(l.entries) : "—"}</td>
                  <td className="ellipsis" style={{ maxWidth: 180 }} title={[l.source, l.license].filter(Boolean).join(" · ")}>
                    {[l.source, l.license].filter(Boolean).join(" · ") || "—"}
                  </td>
                  <td className="r">
                    {editable && l.project_id !== null && (
                      <Popconfirm title={`删除词表“${l.name}”？`} okText="删除" cancelText="取消" onConfirm={() => del.mutate(l.id)}>
                        <button className="btn ghost icon danger" type="button" aria-label={`删除 ${l.name}`}>
                          <Icon name="trash" size={14} />
                        </button>
                      </Popconfirm>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {editable && (
          <div className="col gap-12 vocab-upload">
            <h3>上传词表</h3>
            <div className="row gap-12" style={{ flexWrap: "wrap", alignItems: "flex-end" }}>
              <label className="col" style={{ gap: 4 }}>
                <span className="small">名称</span>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="HSK 3.0" style={{ width: 180 }} maxLength={100} aria-label="名称" />
              </label>
              <label className="col" style={{ gap: 4 }}>
                <span className="small">语言</span>
                <Select value={language} onChange={setLanguage} options={VOCAB_LANGUAGES} style={{ width: 140 }} aria-label="语言" />
              </label>
              <label className="col" style={{ gap: 4 }}>
                <span className="small">文件（CSV / TXT，每行 词,等级）</span>
                <input ref={input} type="file" accept=".csv,.txt,text/csv,text/plain" aria-label="词表文件" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </label>
              <button className="btn p s" type="button" disabled={!file || !name.trim() || upload.isPending} onClick={() => upload.mutate()}>
                {upload.isPending ? <span className="spin" /> : <Icon name="upload" size={14} />}
                上传
              </button>
            </div>
            <ErrorAlert error={upload.error} />
          </div>
        )}
      </div>
    </Modal>
  );
}
