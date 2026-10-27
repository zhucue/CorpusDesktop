import type { ReleaseView } from './source-release.ts';
export type EntryKind = 'publisher' | 'aggregator' | 'dataset';
export type IntegrationStatus = 'catalog_only' | 'verification_pending' | 'experimental_evidence';
export type SourceCapability = 'discover' | 'remote_query' | 'fulltext_analysis' | 'export' | 'model_egress';
export type CatalogMetadata = {
  name: string; publisher: string; entry_kind: EntryKind; categories: string[]; languages: string[];
  official_url: string; materials: string; access_route: string; boundary: string;
};
export type CatalogCreate = CatalogMetadata & { source_id: string };
export type CatalogUpdate = CatalogMetadata & { expected_revision: number };
export type SourceView = CatalogMetadata & {
  source_id: string; license_status: 'pending_review'; integration_status: IntegrationStatus;
  capabilities: { discover: true; remote_query: false; fulltext_analysis: false; export: false; model_egress: false };
  evidence_refs: string[]; revision: number; created_at: string; updated_at: string;
};
export type CatalogWriteView = SourceView & { action_id: string };
export type SourceFilters = { q?: string; language?: string; category?: string; status?: IntegrationStatus; capability?: SourceCapability; cursor?: string; page_size?: number };
export type SourceList = { items: SourceView[]; total: number; next_cursor: string | null };
export type SourceVersion = ReleaseView;
export type SourceVersionList = { items: SourceVersion[]; total: number; next_cursor: string | null };
