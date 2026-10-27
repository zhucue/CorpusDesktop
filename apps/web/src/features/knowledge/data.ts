import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  MAX_PAGE_SIZE,
  api,
  type KbDocument,
  type KbKind,
  type KbLocator,
  type KbStatus,
  type Page,
  type Term,
} from "../../api";
import { listOf, pageOf } from "../../lib/data";

export const kindLabels: Record<KbKind, string> = { literature: "文献", url: "网页", guideline: "规范", note: "笔记" };

export const statusView: Record<KbStatus, { label: string; cls: string; busy?: boolean }> = {
  queued: { label: "排队中", cls: "t-gray", busy: true },
  parsing: { label: "解析中", cls: "t-run", busy: true },
  embedding: { label: "向量化", cls: "t-run", busy: true },
  ready: { label: "可检索", cls: "t-ok" },
  failed: { label: "失败", cls: "t-err" },
};

export const isBusyDoc = (d: Pick<KbDocument, "status">) => d.status === "queued" || d.status === "parsing" || d.status === "embedding";

export const ACCEPT_KB = ".pdf,.docx,.md,.markdown,.txt";
export const MAX_KB_BYTES = 50 * 1024 * 1024;

/** "第 3 页" / "2 核心概念 › 2.1 定义" / "第 12 行"; plain strings pass through. */
export function locatorText(loc: KbLocator | string | null | undefined): string {
  if (!loc) return "";
  if (typeof loc === "string") return loc;
  const parts: string[] = [];
  if (loc.page != null) parts.push(`第 ${loc.page} 页`);
  if (loc.heading_path) {
    const path = Array.isArray(loc.heading_path) ? loc.heading_path.join(" › ") : loc.heading_path;
    if (path) parts.push(path);
  }
  if (loc.line != null) parts.push(`第 ${loc.line} 行`);
  return parts.join(" · ");
}

/** File extension shown in the 类型 column (PDF, DOCX, MD, TXT, URL). */
export function docType(d: Pick<KbDocument, "kind" | "source">): string {
  if (d.kind === "url") return "URL";
  if (d.kind === "note" || d.kind === "guideline") return "MD";
  const m = /\.([a-z0-9]+)$/i.exec(d.source ?? "");
  return m ? m[1].toUpperCase() : kindLabels[d.kind];
}

export type KbTab = "lit" | "terms" | "guides" | "notes";

/** Deep link into the knowledge page: a document (opens its tab / drawer, scrolls to a chunk) or a term. */
export function knowledgeHref(
  projectId: string,
  p: { tab?: KbTab; doc?: string; chunk?: string; term?: string; tq?: string } = {},
): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v) q.set(k, v);
  const s = q.toString();
  return `/p/${projectId}/knowledge${s ? `?${s}` : ""}`;
}

/* ---------- queries ---------- */

export function useKbDocuments(projectId: string | undefined) {
  return useQuery({
    queryKey: ["kb-docs", projectId],
    queryFn: async () => listOf(await api.get<KbDocument[] | Page<KbDocument>>(`/projects/${projectId}/kb/documents`, { page_size: MAX_PAGE_SIZE })),
    enabled: !!projectId,
    refetchInterval: (q) => (q.state.data?.some(isBusyDoc) ? 2000 : false),
    meta: { background: true },
  });
}

export function useKbDocument(id: string | null | undefined) {
  return useQuery({
    queryKey: ["kb-doc", id],
    queryFn: () => api.get<KbDocument>(`/kb/documents/${id}`),
    enabled: !!id,
  });
}

export interface TermFilter {
  q?: string;
  status?: string;
  language?: string;
  page?: number;
  page_size?: number;
}

export function useTerms(projectId: string | undefined, f: TermFilter = {}, enabled = true) {
  return useQuery({
    queryKey: ["kb-terms", projectId, f],
    queryFn: async () =>
      pageOf(
        await api.get<Term[] | Page<Term>>(`/projects/${projectId}/kb/terms`, {
          q: f.q,
          status: f.status,
          language: f.language,
          page: f.page,
          page_size: f.page_size ?? MAX_PAGE_SIZE,
        }),
      ),
    enabled: !!projectId && enabled,
    meta: { background: true },
  });
}

/** After a term changes: replace it in every cached list, then refetch in the background. */
export function useTermUpdated() {
  const qc = useQueryClient();
  return (t: Term) => {
    qc.setQueriesData<Page<Term>>({ queryKey: ["kb-terms"] }, (old) =>
      old ? { ...old, items: old.items.map((x) => (x.id === t.id ? t : x)) } : old,
    );
    void qc.invalidateQueries({ queryKey: ["kb-terms"] });
  };
}

/* ---------- writes shared with other pages ---------- */

/** POST answers one document, a list or `{items}` depending on how many files went up. */
export function docsOf(x: KbDocument | KbDocument[] | Page<KbDocument>): KbDocument[] {
  if (Array.isArray(x)) return x;
  if (x && "items" in x && Array.isArray(x.items)) return x.items;
  return [x as KbDocument];
}

export async function uploadKbFiles(projectId: string, files: File[]): Promise<KbDocument[]> {
  const body = new FormData();
  for (const f of files) body.append("files", f);
  return docsOf(await api.post<KbDocument | KbDocument[] | Page<KbDocument>>(`/projects/${projectId}/kb/documents`, body));
}

export function createNote(projectId: string, title: string, body: string): Promise<KbDocument> {
  return api.post<KbDocument>(`/projects/${projectId}/kb/documents`, { kind: "note", title, body });
}

/** Append Markdown to the end of a note (blank line between), as kb.save does. */
export async function appendToNote(noteId: string, markdown: string): Promise<KbDocument> {
  const cur = await api.get<KbDocument>(`/kb/documents/${noteId}`);
  const prev = (cur.body ?? "").replace(/\s+$/, "");
  return api.patch<KbDocument>(`/kb/documents/${noteId}`, { body: prev ? `${prev}\n\n${markdown}` : markdown });
}

/** kb_import jobs started in this tab (POST response), by document id; list rows may carry job_id too. */
export const importJobs = new Map<string, string>();
export const importJobOf = (d: Pick<KbDocument, "id" | "job_id">): string | null => d.job_id ?? importJobs.get(d.id) ?? null;
