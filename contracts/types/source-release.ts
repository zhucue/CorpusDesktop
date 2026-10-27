export type PolicyInput = { expected_revision: number; decision: 'allow' | 'deny'; export_decision?: 'allow' | 'deny'; review_note: string; evidence_urls: string[] };
export type PolicyView = {
  source_id: string; acquisition_id: string; revision: number; decision: 'unknown' | 'allow' | 'deny'; policy_id: string | null;
  source_identity: Record<string, unknown>; source_identity_revision: number; identity_current: boolean;
  acquisition_manifest_sha256: string; license_sha256: string; license: Record<string, unknown>; quality: Record<string, unknown>;
  review_note: string | null; evidence_urls: string[]; reviewed_by: string | null; reviewed_at: string | null;
  scope: 'internal_research'; export_decision: 'allow' | 'deny'; export: boolean; model_egress: false;
};
export type IndexCounts = { sentences: number; cmn_sentences: number; eng_sentences: number; characters: number; tokens: number; direct_edges: number; unknown_owner: number };
export type IndexQuality = { all_source_sentences_indexed: boolean; rejected_sentences: number; token_roundtrip_verified: boolean; attributes: 'form'[]; document_count_unit: 'imported_sentence_record'; normalization: 'none' };
export type ReleaseView = {
  release_id: string; source_id: string; source_snapshot_id: string; index_id: string; acquisition_id: string;
  version: string; published_at: string; manifest_sha256: string; index_identity_sha256: string;
  recipe: { id: string; sha256: string }; counts: IndexCounts; quality: IndexQuality;
  policy_revision: number; current_policy_revision: number; state: 'PUBLISHED'; searchable: boolean;
  available: boolean; unavailable_reason: string | null;
};
export type MountView = {
  id: string; project_id: string; created_at: string; removed_at: string | null; state: 'ACTIVE' | 'REMOVED'; release: ReleaseView;
  allowed_actions: { read_manifest: boolean; remove: boolean };
};
export type MountList = { items: MountView[]; total: number; next_cursor: string | null; allowed_actions: { create: boolean } };
export type MountAction = { action_id: string; existing: boolean; mount: MountView };
export type ReleaseAction = { action_id: string; existing: boolean; release: ReleaseView };
export type MountManifest = { mount_id: string; source_snapshot_id: string; manifest_sha256: string; manifest: Record<string, unknown> };
