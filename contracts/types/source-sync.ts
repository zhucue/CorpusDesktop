/** S2 admin acquisition; VALIDATED is not an indexed or public release. */
export type SyncState = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED';
export type SyncStage = 'QUEUED' | 'ACQUIRING' | 'PARSING' | 'STORING' | 'VALIDATED' | 'FAILED' | 'CANCELLED';
export type SyncRunView = {
  id: string; source_id: string; connector_id: string; source_revision: number;
  source_identity: { name: string; publisher: string; entry_kind: string; official_url: string };
  state: SyncState; stage: SyncStage; attempt: number; created_at: string; updated_at: string;
  progress: { processed_bytes: number; total_bytes: number | null; processed_records: number; total_records: number | null; file_name: string | null };
  result: { acquisition_id: string; state: 'VALIDATED'; searchable: false; manifest_sha256: string; export_date: string | null;
    quality: Record<string, unknown>; diff: Record<string, unknown>; license: Record<string, unknown> } | null;
  error: { code: string; message: string; retryable: boolean } | null;
  allowed_actions: { cancel: boolean; retry: boolean };
};
export type SyncRunList = { items: SyncRunView[]; total: number; next_cursor: string | null; allowed_actions: { start: boolean } };
export type SyncActionView = { action_id: string; sync_run_id: string; job_id: string; state: SyncState; run: SyncRunView };
