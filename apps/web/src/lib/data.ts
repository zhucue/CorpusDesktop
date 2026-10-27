import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router";
import {
  MAX_PAGE_SIZE,
  api,
  type Corpus,
  type Job,
  type Page,
  type Project,
  type SavedQuery,
  type Scope,
  type SearchScope,
  type Subcorpus,
  type User,
} from "../api";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<User>("/auth/me"),
    retry: false,
    staleTime: Infinity,
  });
}

export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get<Page<Project>>("/projects", { page_size: MAX_PAGE_SIZE }),
  });
}

export function useProjectId(): string {
  return useParams().projectId!;
}

export function useProject() {
  const id = useProjectId();
  return useQuery({ queryKey: ["project", id], queryFn: () => api.get<Project>(`/projects/${id}`) });
}

export function canEdit(p?: Project): boolean {
  return p?.role === "owner" || p?.role === "editor";
}

const busy = (c: Corpus) => c.status === "importing" || c.status === "indexing";

export function useCorpora(projectId: string | undefined) {
  return useQuery({
    queryKey: ["corpora", projectId],
    queryFn: () => api.get<Page<Corpus>>("/corpora", { project_id: projectId, page_size: MAX_PAGE_SIZE }),
    enabled: !!projectId,
    refetchInterval: (q) => (q.state.data?.items.some(busy) ? 3000 : false),
    meta: { background: true },
  });
}

export function useCorpus(id: string | undefined) {
  return useQuery({
    queryKey: ["corpus", id],
    queryFn: () => api.get<Corpus>(`/corpora/${id}`),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data && busy(q.state.data) ? 3000 : false),
  });
}

export function useSubcorpora(projectId: string | undefined) {
  return useQuery({
    queryKey: ["subcorpora", projectId],
    queryFn: () => api.get<Page<Subcorpus>>(`/projects/${projectId}/subcorpora`, { page_size: MAX_PAGE_SIZE }),
    enabled: !!projectId,
  });
}

export function useSavedQueries(projectId: string | undefined) {
  return useQuery({
    queryKey: ["queries", projectId],
    queryFn: () => api.get<Page<SavedQuery>>(`/projects/${projectId}/queries`, { page_size: MAX_PAGE_SIZE }),
    enabled: !!projectId,
  });
}

const activeJob = (j: Job) => j.state === "queued" || j.state === "running";
export const isActiveJob = activeJob;

/** Project job list shared by the task tray and the jobs page; polls every 2 s while something runs. */
export function useProjectJobs(projectId: string | undefined) {
  return useQuery({
    queryKey: ["jobs", projectId, "tray"],
    queryFn: () => api.get<Page<Job>>(`/projects/${projectId}/jobs`, { page: 1, page_size: 50 }),
    enabled: !!projectId,
    refetchInterval: (q) => (q.state.data?.items.some(activeJob) ? 2000 : false),
    meta: { background: true },
  });
}

/** Jobs started in the background of a page (e.g. the search distribution): the tray lists them without a toast. */
export const quietJobs = new Set<string>();

/** Call after creating a job so the tray starts polling. */
export function useJobCreated() {
  const qc = useQueryClient();
  return (projectId: string) => qc.invalidateQueries({ queryKey: ["jobs", projectId] });
}

/** Poll one job until it finishes. */
export function useJob(id: string | null | undefined, interval = 1000) {
  return useQuery({
    queryKey: ["job", id],
    queryFn: () => api.get<Job>(`/jobs/${id}`),
    enabled: !!id,
    refetchInterval: (q) => (!q.state.data || activeJob(q.state.data) ? interval : false),
    meta: { background: true },
  });
}

/* ---------- scope helpers ---------- */

export const scopeKey = (s: Scope) => ("corpus_id" in s ? `corpus:${s.corpus_id}` : `subcorpus:${s.subcorpus_id}`);
export function scopeFromKey(key: string): Scope {
  const [kind, id] = key.split(":", 2);
  return kind === "corpus" ? { corpus_id: id } : { subcorpus_id: id };
}

export function sameScope(a: SearchScope | null | undefined, b: SearchScope | null | undefined): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

export interface ScopeInfo {
  corpus: Corpus | null;
  subcorpus: Subcorpus | null;
  name: string;
}

export function describeScope(scope: SearchScope | null | undefined, corpora: Corpus[], subcorpora: Subcorpus[]): ScopeInfo {
  if (!scope) return { corpus: null, subcorpus: null, name: "" };
  if ("subcorpus_id" in scope) {
    const sub = subcorpora.find((s) => s.id === scope.subcorpus_id) ?? null;
    const corpus = sub ? (corpora.find((c) => c.id === sub.corpus_id) ?? null) : null;
    return { corpus, subcorpus: sub, name: sub ? `子库「${sub.name}」` : "子库" };
  }
  const corpus = corpora.find((c) => c.id === scope.corpus_id) ?? null;
  const filtered = "filter" in scope;
  return { corpus, subcorpus: null, name: (corpus?.name ?? "语料库") + (filtered ? " · 临时筛选" : "") };
}
