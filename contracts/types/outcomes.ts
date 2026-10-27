import type { ContextView, HitRef, QueryAST, QueryCounts, Recipe, ResearchError, ResearchProgress } from './research.ts';

export type QueryMethod = { query_run_id: string; result_set_id: string; snapshot_id: string; query: QueryAST; query_sha256: string; recipe: Recipe; counts: QueryCounts; result_sha256: string; index_identity_sha256: string };
export type EvidenceSummary = { id: string; project_id: string; created_by: string; created_at: string; query_run_id: string; result_set_id: string; snapshot_id: string; hit_ref: HitRef };
export type EvidenceView = EvidenceSummary & { context: ContextView; method: QueryMethod; context_sha256: string };
export type EvidenceAction = { action_id: string; existing: boolean; evidence: EvidenceView };
export type EvidenceList = { items: EvidenceSummary[]; total: number; next_cursor: string | null; allowed_actions: { create: boolean } };
export type NoteInput = { title: string; body: string; evidence_ids: string[]; query_run_ids: string[] };
export type NoteUpdate = NoteInput & { expected_revision: number };
export type NoteSummary = {
  id: string; project_id: string; created_by: string; created_at: string; updated_at: string; revision: number; title: string;
  evidence_ids: string[]; query_run_ids: string[]; authorization_evidence_ids: string[]; authorization_query_run_ids: string[];
  status: 'draft' | 'accepted'; accepted_by: string | null; accepted_at: string | null;
  allowed_actions: { update: boolean; accept: boolean; export: boolean };
};
export type NoteView = NoteSummary & { body: string };
export type NoteAction = { action_id: string; note: NoteView };
export type NoteList = { items: NoteSummary[]; total: number; next_cursor: string | null; allowed_actions: { create: boolean } };
export type ExportTarget = { kind: 'query_runs'; query_run_ids: string[] } | { kind: 'note_revision'; note_id: string; revision: number };
export type ExportInput = { target: ExportTarget; format: 'csv' | 'json' };
export type ExportResult = { filename: string; media_type: 'application/zip' | 'application/json'; container: 'zip' | 'file'; byte_size: number; sha256: string; manifest_sha256: string; row_count: number };
export type ExportView = {
  id: string; job_id: string; project_id: string; actor_id: string; target: ExportTarget; format: 'csv' | 'json';
  state: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED'; stage: 'QUEUED' | 'EXPORTING' | 'STORING' | 'COMPLETE' | 'FAILED' | 'CANCELLED';
  attempt: number; progress: ResearchProgress; error: ResearchError | null; result: ExportResult | null;
  created_at: string; updated_at: string; allowed_actions: { cancel: boolean; retry: boolean; download: boolean };
};
export type ExportAction = { action_id: string; export_id: string; job_id: string; state: ExportView['state']; run: ExportView };
export type ExportList = { items: ExportView[]; total: number; next_cursor: string | null };

/** No title, body, context, coordinates, filename or derived counts. */
export function evidenceMetadata(value: EvidenceSummary) {
  return { evidence_id: value.id, project_id: value.project_id, query_run_id: value.query_run_id,
    result_set_id: value.result_set_id, snapshot_id: value.snapshot_id, hit_ref: value.hit_ref, next_action: 'manual_evidence_view' };
}
export function noteMetadata(value: NoteSummary) {
  return { note_id: value.id, project_id: value.project_id, revision: value.revision,
    status: value.status, evidence_ids: value.evidence_ids, query_run_ids: value.query_run_ids, authorization_evidence_ids: value.authorization_evidence_ids, authorization_query_run_ids: value.authorization_query_run_ids, next_action: 'manual_note_view' };
}
export function exportMetadata(value: ExportView) {
  return { export_id: value.id, job_id: value.job_id, project_id: value.project_id, state: value.state,
    next_action: value.state === 'SUCCEEDED' ? 'manual_download' : 'exports.get' };
}
