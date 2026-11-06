import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Hit, type Job, type JobState, type SearchScope } from "../../api";
import { useJobCreated } from "../../lib/data";

/** GET /corpora/{id}/semantic-index (contracts/p10.md §六). */
export interface SemanticIndex {
  corpus_id: string;
  status: "none" | "building" | "ready" | "stale" | "failed";
  error: string | null;
  /** Sentences of the corpus now. */
  sentences: number;
  /** Sentences per document language; a build may cover one language. */
  languages: Record<string, number>;
  /** Language the index covers (null: all documents). */
  language: string | null;
  /** Sentences per second of the last build (default before one). */
  rate: number;
  /** Sentences in the semantic index (last build). */
  indexed: number | null;
  /** The stored vectors answer searches (also while a rebuild runs). */
  searchable: boolean;
  model: string | null;
  built_at: string | null;
  estimate_seconds: number;
  max_sentences: number;
  can_build: boolean;
  job: { id: string; state: JobState; progress: Job["progress"]; error: Job["error"]; queue_ahead: number | null } | null;
}

export interface SemanticHit extends Hit {
  /** Cosine similarity to the query sentence. */
  score: number;
}

export interface SemanticRequest {
  scope: SearchScope;
  text: string;
  top?: number;
}

export interface SemanticResult {
  items: SemanticHit[];
  status: SemanticIndex["status"];
  indexed: number | null;
  model: string | null;
}

export const SEMANTIC_MAX_TEXT = 500;

/** "约 40 秒" / "约 12 分钟" / "约 1.5 小时". */
export function estimateText(seconds: number): string {
  if (seconds < 60) return `约 ${Math.max(1, Math.round(seconds))} 秒`;
  if (seconds < 3600) return `约 ${Math.round(seconds / 60)} 分钟`;
  return `约 ${(seconds / 3600).toFixed(1)} 小时`;
}

export function useSemanticIndex(corpusId: string | undefined) {
  return useQuery({
    queryKey: ["semantic-index", corpusId],
    queryFn: () => api.get<SemanticIndex>(`/corpora/${corpusId}/semantic-index`),
    enabled: !!corpusId,
    refetchInterval: (q) => (q.state.data?.status === "building" ? 2000 : false),
    meta: { background: true },
  });
}

export function useBuildSemantic(corpusId: string | undefined, projectId: string) {
  const qc = useQueryClient();
  const jobCreated = useJobCreated();
  return useMutation({
    mutationFn: (language?: string) => api.post<Job>(`/corpora/${corpusId}/semantic-index`, language ? { language } : {}),
    onSuccess: () => {
      jobCreated(projectId);
      qc.invalidateQueries({ queryKey: ["semantic-index", corpusId] });
    },
  });
}
