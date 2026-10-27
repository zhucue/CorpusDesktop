/** Private S3 build artifacts. INDEXED does not confer research or publication access. */
import type { SyncRunView, SyncState } from './source-sync.ts';
export type IndexStage = 'QUEUED' | 'FETCHING' | 'INDEXING' | 'VERIFYING' | 'STORING' | 'INDEXED' | 'FAILED' | 'CANCELLED';
export type IndexRunView = Pick<SyncRunView, 'id' | 'source_id' | 'source_identity' | 'state' | 'attempt' | 'created_at' | 'updated_at' | 'progress' | 'error' | 'allowed_actions'> & {
  acquisition_id: string; recipe: { id: string; sha256: string }; stage: IndexStage;
  result: { index_id: string; state: 'INDEXED'; searchable: false; identity_sha256: string; manifest_sha256: string;
    counts: Record<string, unknown>; artifact_bytes: number; quality: Record<string, unknown> } | null;
};
export type IndexRunList = { items: IndexRunView[]; total: number; next_cursor: string | null; allowed_actions: { start: boolean } };
export type IndexActionView = { action_id: string; index_run_id: string; job_id: string; state: SyncState; existing: boolean; run: IndexRunView };
