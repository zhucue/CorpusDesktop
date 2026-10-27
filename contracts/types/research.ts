import type { IndexCounts } from './source-release.ts';

export type LiteralPattern = { type: 'literal'; value: string };
export type TermPattern = { type: 'term'; attr: 'form'; op: 'eq'; value: string };
export type GapPattern = { type: 'gap'; min: number; max: number };
export type Sequence<T> = { type: 'sequence'; items: (T | GapPattern)[] };
export type Pattern<T> = T | Sequence<T> | { type: 'any_of'; patterns: (T | Sequence<T>)[] };
export type QueryAST = { dsl_version: 'corpus-query/v1'; within: 'sentence'; overlap: 'all'; normalization?: 'none'; sort?: ['document_ordinal', 'start', 'end'] } & (
  { unit: 'character'; pattern: Pattern<LiteralPattern> } | { unit: 'token'; pattern: Pattern<TermPattern> }
);
export type QueryInput = { snapshot_id: string; query: QueryAST; page_size?: number; context_codepoints?: number };
export type ResearchProgress = { processed_bytes: number; total_bytes: number | null; processed_records: number; total_records: number | null; file_name: string | null };
export type ResearchError = { code: string; message: string; retryable: boolean };
export type Recipe = { id: string; sha256: string };
export type SnapshotInput = { mount_ids: string[]; material_revision_ids: string[] };
export type DocumentUnits = { source_records: number; private_files: number };
export type SnapshotCounts = IndexCounts & { documents: number; document_units: DocumentUnits };
export type SnapshotMember = { kind: 'whole_source_mount'; mount_id: string; source_id: string; source_snapshot_id: string; release_id: string; index_id: string; index_identity_sha256: string; ordered_members_sha256: string; recipe: Recipe } | { kind: 'private_revision'; material_id: string; material_revision_id: string; revision: number; language: 'cmn' | 'eng'; manifest_sha256: string; canonical_sha256: string; recipe: Recipe };
export type SnapshotView = {
  id: string; project_id: string; name: string; job_id: string; created_by: string; created_at: string; updated_at: string;
  state: 'PREPARING' | 'READY' | 'FAILED'; available: boolean; unavailable_reason: string | null; manifest_sha256: string;
  members: SnapshotMember[]; index_kind: 'source_reuse' | 'project';
  counts: SnapshotCounts | null; query_capabilities: { character: true; token_form: true; lemma: false; upos: false; regex: false; within: ['sentence']; context_unit: 'codepoint' };
  progress: ResearchProgress; error: ResearchError | null; allowed_actions: { retry: boolean };
};
export type SnapshotList = { items: SnapshotView[]; total: number; next_cursor: string | null; allowed_actions: { create: boolean } };
export type SnapshotAction = { action_id: string; existing: boolean; job_id: string; snapshot: SnapshotView };
export type QueryCounts = { count_state: 'pending' | 'complete' | 'failed'; total_hits: number | null; matched_segments: number | null; matched_documents: number | null; document_count_unit: 'imported_sentence_record' | 'uploaded_file' | 'mixed_document_units'; matched_document_units: DocumentUnits | null };
export type QueryRunView = QueryCounts & {
  id: string; project_id: string; snapshot_id: string; result_set_id: string; actor_id: string; name: string; query: QueryAST; query_sha256: string; recipe: Recipe;
  sort: ['document_ordinal', 'start', 'end']; context_codepoints: number; page_size: number;
  state: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED'; stage: 'QUEUED' | 'FIRST_PAGE' | 'FULL_RESULT' | 'PREPARING_CACHE' | 'COMPLETE' | 'FAILED' | 'CANCELLED';
  attempt: number; created_at: string; updated_at: string; first_page_state: 'pending' | 'ready' | 'failed'; prepare_state: 'idle' | 'pending' | 'ready' | 'failed';
  progress: ResearchProgress; error: ResearchError | null; allowed_actions: { cancel: boolean; retry: boolean; prepare: boolean };
};
export type QueryAction = { action_id: string; job_id: string; query_run_id: string; result_set_id: string; state: QueryRunView['state']; run: QueryRunView };
export type QueryList = { items: QueryRunView[]; total: number; next_cursor: string | null };
export type HitRef = { result_set_id: string; ordinal: number };
export type HitOrigin = { origin_kind: 'source'; source_id: string; source_sentence_id: string; source_url: string; material_id: null; material_revision_id: null } | { origin_kind: 'private'; source_id: null; source_sentence_id: null; source_url: null; material_id: string; material_revision_id: string };
export type HitCoordinates = HitOrigin & {
  hit_ref: HitRef; revision_id: string; segment_id: string; document_id: string; document_name: string; context_start_cp: number; start_cp: number; end_cp: number;
  token_start: number | null; token_end: number | null; global_token_start: number | null; global_token_end: number | null;
  evidence_id: null;
};
export type HitView = HitCoordinates & { left: string; match: string; right: string };
export type HitPage = QueryCounts & {
  project_id: string; snapshot_id: string; result_set_id: string; query_run_id: string; hits: HitView[]; next_cursor: string | null; has_more: boolean;
  page_state: 'pending' | 'ready'; completeness: 'preview' | 'complete'; sort: ['document_ordinal', 'start', 'end']; context: { unit: 'codepoint'; before: number; after: number };
};
export type ContextView = HitCoordinates & { project_id: string; snapshot_id: string; result_set_id: string; text: string };

/** Explicit allowlists: no AST, text, names derived from a query, or material counts. */
export function snapshotMetadata(value: SnapshotView) {
  return { snapshot_id: value.id, project_id: value.project_id, job_id: value.job_id, state: value.state,
    next_action: value.available ? 'manual_query' : 'wait' };
}
export function resultMetadata(value: QueryRunView) {
  return { id: value.id, project_id: value.project_id, snapshot_id: value.snapshot_id, result_set_id: value.result_set_id,
    state: value.state, first_page_state: value.first_page_state, count_state: value.count_state,
    next_action: 'manual_result_view' };
}
