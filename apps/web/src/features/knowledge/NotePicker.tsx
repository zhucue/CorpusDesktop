import { useQueryClient } from "@tanstack/react-query";
import { Input, Modal, Radio, Select } from "antd";
import { useEffect, useState } from "react";
import { api, type Evidence, type KbDocument } from "../../api";
import { ErrorAlert } from "../../components/common";
import { appendToNote, createNote, useKbDocuments } from "./data";

export type NoteTarget = { noteId: string } | { newTitle: string };

/** Append to an existing note or create one with `markdown` as its body. */
export async function writeToNote(projectId: string, target: NoteTarget, markdown: string): Promise<KbDocument> {
  return "noteId" in target ? appendToNote(target.noteId, markdown) : createNote(projectId, target.newTitle, markdown);
}

type EvidenceItem = Pick<Evidence, "id" | "text" | "source" | "ref">;

/** Body of an evidence ref: the server fills text / source / query from evidence_id. */
export const evidenceRef = (it: EvidenceItem, append = true) => ({
  kind: "evidence" as const,
  ref: { evidence_id: it.id, ...it.ref, text: it.text, source: it.source },
  append,
});

/**
 * Evidence basket → note: an empty new note (or the existing one), then one ref per item. The API appends
 * each quote block itself, so the body holds every item once and matches the 引用 list.
 */
export async function writeEvidenceToNote(projectId: string, target: NoteTarget, items: EvidenceItem[]): Promise<KbDocument> {
  const note = "noteId" in target ? await api.get<KbDocument>(`/kb/documents/${target.noteId}`) : await createNote(projectId, target.newTitle, "");
  for (const it of items) await api.post(`/kb/documents/${note.id}/refs`, evidenceRef(it));
  return note;
}

/** Pick an existing note or name a new one; `onPick` does the write and the dialog shows its error. */
export function NotePicker({
  open,
  projectId,
  title = "加入笔记",
  defaultTitle = "",
  onClose,
  onPick,
}: {
  open: boolean;
  projectId: string;
  title?: string;
  defaultTitle?: string;
  onClose: () => void;
  onPick: (t: NoteTarget) => Promise<void>;
}) {
  const qc = useQueryClient();
  const docs = useKbDocuments(open ? projectId : undefined);
  const notes = (docs.data ?? []).filter((d) => d.kind === "note").sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [noteId, setNoteId] = useState<string | undefined>();
  const [newTitle, setNewTitle] = useState(defaultTitle);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!open) return;
    setNewTitle(defaultTitle);
    setError(null);
  }, [open, defaultTitle]);
  useEffect(() => {
    if (open && docs.isSuccess && notes.length === 0) setMode("new");
  }, [open, docs.isSuccess, notes.length]);

  const ok = mode === "existing" ? !!noteId : newTitle.trim().length > 0;

  async function submit() {
    if (!ok) return;
    setBusy(true);
    setError(null);
    try {
      await onPick(mode === "existing" ? { noteId: noteId! } : { newTitle: newTitle.trim() });
      void qc.invalidateQueries({ queryKey: ["kb-docs", projectId] });
      if (mode === "existing") void qc.invalidateQueries({ queryKey: ["kb-doc", noteId] });
      onClose();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={title} open={open} onCancel={onClose} okText="确定" cancelText="取消" onOk={() => void submit()} okButtonProps={{ disabled: !ok, loading: busy }} destroyOnHidden width={440}>
      <div className="col" style={{ gap: 12 }}>
        <Radio.Group value={mode} onChange={(e) => setMode(e.target.value)}>
          <Radio.Button value="existing" disabled={docs.isSuccess && notes.length === 0}>
            现有笔记
          </Radio.Button>
          <Radio.Button value="new">新建笔记</Radio.Button>
        </Radio.Group>
        {mode === "existing" ? (
          <Select
            showSearch
            optionFilterProp="label"
            placeholder="选择笔记"
            loading={docs.isPending}
            value={noteId}
            onChange={setNoteId}
            options={notes.map((n) => ({ value: n.id, label: n.title || "未命名笔记" }))}
            aria-label="笔记"
          />
        ) : (
          <Input value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="笔记标题" maxLength={200} aria-label="笔记标题" autoFocus />
        )}
        <ErrorAlert error={error ?? docs.error} />
      </div>
    </Modal>
  );
}

/** One evidence item as a Markdown quote with its source and query — the same block the API appends (kb._evidence_block). */
export function evidenceMarkdown(e: { text: string; source: string; ref: { search_query?: string } }): string {
  const quote = e.text
    .trim()
    .split("\n")
    .map((l) => (l.trim() ? `> ${l}` : ">"))
    .join("\n");
  let tail = e.source ? `> —— ${e.source}` : "";
  if (e.ref?.search_query) tail += `${tail ? "；" : "> —— "}查询式：\`${e.ref.search_query}\``;
  return tail ? `${quote}\n>\n${tail}` : quote;
}

/** dataTransfer type of an evidence item dragged from the basket (JSON of id, text, source, ref). */
export const EVIDENCE_MIME = "application/x-corpus-evidence";
