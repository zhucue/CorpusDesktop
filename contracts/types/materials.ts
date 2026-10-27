import type { Recipe, ResearchError, ResearchProgress } from './research.ts';
export type ImportInput = { upload_id: string; language: 'cmn' | 'eng' };
export type MaterialRevisionView = { id: string; material_id: string; project_id: string; revision: number; upload_id: string; language: 'cmn' | 'eng'; recipe: Recipe; manifest_sha256: string; canonical_sha256: string; counts: { documents: 1; segments: number; characters: number }; quality: { complete_text_preserved: true; rejected_segments: 0; segmentation: 'deterministic_rules_not_linguistic_gold' }; created_at: string };
export type MaterialView = { id: string; project_id: string; name: string; language: 'cmn' | 'eng'; state: 'IMPORTING' | 'READY' | 'FAILED' | 'CANCELLED'; import_id: string; latest_revision: MaterialRevisionView | null; revisions: MaterialRevisionView[]; created_at: string };
export type MaterialList = { items: MaterialView[]; next_cursor: string | null };
export type ImportView = { id: string; job_id: string; project_id: string; actor_id: string; upload_id: string; material_id: string; filename: string; language: 'cmn' | 'eng'; recipe: Recipe; state: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED'; stage: 'QUEUED' | 'FETCHING' | 'PARSING' | 'STORING' | 'COMPLETE' | 'FAILED' | 'CANCELLED'; attempt: number; progress: ResearchProgress; error: ResearchError | null; result: MaterialRevisionView | null; allowed_actions: { cancel: boolean; retry: boolean }; created_at: string; updated_at: string };
export type ImportAction = { action_id: string; job_id: string; import_id: string; state: ImportView['state']; run: ImportView };
export type ImportList = { items: ImportView[]; next_cursor: string | null };
export type ValidatedUploadView = { upload_id: string; project_id: string; state: 'VALIDATED'; filename: string; size: number; sha256: string; media_type: string; expires_at: string; job_id: string | null };
export type ValidatedUploadList = { items: ValidatedUploadView[]; next_cursor: string | null };

/** Strict model-facing projection: no filename, text, segmentation or derived counts. */
export function importMetadata(value: ImportView) {
  return { import_id: value.id, job_id: value.job_id, project_id: value.project_id, material_id: value.material_id, state: value.state,
    material_revision_id: value.result?.id ?? null, next_action: value.state === 'SUCCEEDED' ? 'materials.get' : 'imports.get' };
}
export function materialMetadata(value: MaterialView) {
  return { material_id: value.id, project_id: value.project_id, state: value.state, import_id: value.import_id,
    material_revision_id: value.latest_revision?.id ?? null, revisions: value.revisions.map(item => ({ material_revision_id: item.id, revision: item.revision, language: item.language })), next_action: value.state === 'READY' ? 'snapshots.create' : 'imports.get' };
}
