import type { AgentScope, AgentRuntime, AgentSession, AgentRun, AgentTurn, AgentEvent, AgentPage, AgentRunInput } from './agent.ts';
import type { EvidenceAction, EvidenceList, EvidenceView, NoteInput, NoteUpdate, NoteAction, NoteView, NoteList, ExportInput, ExportAction, ExportView, ExportList } from './outcomes.ts';
import type { ImportInput, ImportAction, ImportView, ImportList, MaterialView, MaterialList, ValidatedUploadList } from './materials.ts';
/** S1 HTTP contract. Authority is supplied by the authenticated backend. */
import type { CatalogCreate, CatalogUpdate, CatalogWriteView, SourceFilters, SourceList, SourceView, SourceVersionList } from './catalog.ts';
import type { SyncActionView, SyncRunList, SyncRunView } from './source-sync.ts';
import type { IndexActionView, IndexRunList, IndexRunView } from './source-index.ts';
import type { PolicyInput, PolicyView, ReleaseView, ReleaseAction, MountView, MountList, MountAction, MountManifest } from './source-release.ts';
import type { SnapshotView, SnapshotList, SnapshotAction, SnapshotInput, QueryInput, QueryRunView, QueryAction, QueryList, HitPage, ContextView } from './research.ts';
export type ApiFailure = { code: string; message: string; request_id: string; field_errors: unknown[]; retryable: boolean };
export type Actor = { id: string; email: string; is_platform_admin: boolean };
export type AuthView = { actor: Actor; csrf_token: string };
export type ProjectView = { id: string; name: string; owner_id: string; role: 'owner' | 'editor' | 'viewer'; created_at: string; permissions: { upload: boolean; manage_members: boolean; read_jobs: boolean } };
export type UploadInput = { filename: string; size: number; media_type: string; sha256: string };
export type UploadView = { upload_id: string; project_id: string; action_id: string; state: string; upload_url: string; method: 'PUT'; expires_at: string; max_bytes: number };
export type AcceptedUpload = { status: 'accepted'; action_id: string; job_id: string; upload_id: string; state: string; result_ref: null };
export type JobState = 'QUEUED' | 'RUNNING' | 'CANCEL_REQUESTED' | 'CANCELLED' | 'SUCCEEDED' | 'FAILED';
export type JobView = {
  job_id: string; project_id: string; upload_id: string | null; filename: string | null; kind: 'UPLOAD_VALIDATE' | 'TXT_IMPORT' | 'EXPORT'; state: JobState; stage: string;
  actor_id: string; action_id: string; attempt: number; lease_epoch: number; lease_expires_at: string | null;
  progress: { processed_bytes: number; total_bytes: number | null };
  error: { code: string; message: string; retryable: boolean } | null;
  result: { state: 'VALIDATED'; size: number; sha256: string; upload_id: string; validation: 'utf8-text-and-integrity/v1' } | { material_id: string; material_revision_id: string; state: 'READY' } | { export_id: string; state: 'READY' } | null;
  result_ref: { upload_id: string; state: 'VALIDATED' } | { material_revision_id: string; state: 'READY' } | { export_id: string; state: 'READY' } | null;
  allowed_actions: ('cancel' | 'retry')[]; created_at: string; updated_at: string;
};
export type JobEvent = { event_id: string; job_id: string; sequence: number; kind: string; state: JobState; attempt: number; payload: Record<string, unknown>; created_at: string };
export type MemberView = { user_id: string; email: string; role: 'owner' | 'editor' | 'viewer' };
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  constructor(status: number, failure: Partial<ApiFailure>) { super(failure.message || `请求失败（${status}）`); this.status = status; this.code = failure.code || 'HTTP_ERROR'; }
}

/** Fixed routes only; transport and CSRF are supplied by trusted callers. */
export class CorpusApiClient {
  private base: string;
  private transport: typeof fetch;
  private csrf: () => string | undefined;
  constructor(options: { base?: string; transport?: typeof fetch; csrf: () => string | undefined }) { this.base = options.base ?? ''; this.transport = options.transport ?? globalThis.fetch.bind(globalThis); this.csrf = options.csrf; }
  private async request<T>(path: string, method = 'GET', body?: unknown, key?: string): Promise<T> {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const csrf = this.csrf(); if (method !== 'GET' && csrf) headers['X-CSRF-Token'] = csrf;
    if (key) headers['Idempotency-Key'] = key;
    const response = await this.transport(`${this.base}/api/v1${path}`, { method, headers, credentials: 'include', redirect: 'error', signal: AbortSignal.timeout(15000), ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
    if (!response.ok) throw new ApiError(response.status, await response.json().catch(() => ({})));
    return response.status === 204 ? undefined as T : await response.json() as T;
  }
  agentRuntime() { return this.request<AgentRuntime>('/agent/runtime'); }
  agentSessions(scopeKind?: AgentScope['scope_kind'], projectId?: string, before?: string) {
    const query = new URLSearchParams({ limit: '20' });
    if (scopeKind) query.set('scope_kind', scopeKind);
    if (projectId) query.set('project_id', projectId);
    if (before) query.set('before', before);
    return this.request<AgentPage<AgentSession>>(`/agent/sessions?${query}`);
  }
  createAgentSession(scope: AgentScope) { return this.request<AgentSession>('/agent/sessions', 'POST', { scope }); }
  agentSession(id: string) { return this.request<AgentSession>(`/agent/sessions/${encodeURIComponent(id)}`); }
  agentRuns(session: string, before?: string) { return this.request<AgentPage<AgentRun>>(`/agent/sessions/${encodeURIComponent(session)}/runs?limit=20${before ? `&before=${encodeURIComponent(before)}` : ''}`); }
  agentMessages(session: string, before?: string) { return this.request<AgentPage<AgentTurn>>(`/agent/sessions/${encodeURIComponent(session)}/messages?limit=20${before ? `&before=${encodeURIComponent(before)}` : ''}`); }
  createAgentRun(session: string, input: AgentRunInput) { return this.request<AgentRun>(`/agent/sessions/${encodeURIComponent(session)}/runs`, 'POST', input); }
  agentRun(id: string) { return this.request<AgentRun>(`/agent/runs/${encodeURIComponent(id)}`); }
  agentEvents(run: string, after = 0) { return this.request<{ items: AgentEvent[]; next_after: number }>(`/agent/runs/${encodeURIComponent(run)}/events?after=${after}`); }
  cancelAgentRun(id: string) { return this.request<AgentRun>(`/agent/runs/${encodeURIComponent(id)}/cancel`, 'POST', {}); }
  login(email: string, password: string) { return this.request<AuthView>('/auth/login', 'POST', { email, password }); }
  session() { return this.request<AuthView>('/auth/session'); }
  logout() { return this.request<void>('/auth/logout', 'POST'); }
  projects() { return this.request<{ items: ProjectView[] }>('/projects'); }
  project(id: string) { return this.request<ProjectView>(`/projects/${encodeURIComponent(id)}`); }
  createProject(name: string) { return this.request<ProjectView>('/projects', 'POST', { name }); }
  members(project: string) { return this.request<{ items: MemberView[] }>(`/projects/${encodeURIComponent(project)}/members`); }
  setMember(project: string, user: string, role: 'editor' | 'viewer') { return this.request<MemberView>(`/projects/${encodeURIComponent(project)}/members/${encodeURIComponent(user)}`, 'PUT', { role }); }
  removeMember(project: string, user: string) { return this.request<void>(`/projects/${encodeURIComponent(project)}/members/${encodeURIComponent(user)}`, 'DELETE'); }
  createUpload(project: string, input: UploadInput, key: string) { return this.request<UploadView>(`/projects/${encodeURIComponent(project)}/uploads`, 'POST', input, key); }
  upload(id: string) { return this.request<{ upload_id: string; project_id: string; state: string; filename: string; size: number; sha256: string; job_id: string | null }>(`/uploads/${encodeURIComponent(id)}`); }
  completeUpload(upload: string, key: string) { return this.request<AcceptedUpload>(`/uploads/${encodeURIComponent(upload)}/complete`, 'POST', {}, key); }
  jobs(project: string, cursor?: string) { return this.request<{ items: JobView[]; next_cursor: string | null }>(`/projects/${encodeURIComponent(project)}/jobs${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`); }
  job(id: string) { return this.request<JobView>(`/jobs/${encodeURIComponent(id)}`); }
  events(id: string, after = 0) { return this.request<{ items: JobEvent[]; next_after: number }>(`/jobs/${encodeURIComponent(id)}/events?after=${after}`); }
  cancelJob(id: string, key: string) { return this.request<JobView>(`/jobs/${encodeURIComponent(id)}/cancel`, 'POST', {}, key); }
  retryJob(id: string, key: string) { return this.request<JobView>(`/jobs/${encodeURIComponent(id)}/retry`, 'POST', {}, key); }
  sources(filters: SourceFilters = {}) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== '') query.set(key, String(value));
    return this.request<SourceList>(`/sources${query.size ? `?${query}` : ''}`);
  }
  source(id: string) { return this.request<SourceView>(`/sources/${encodeURIComponent(id)}`); }
  sourceVersions(id: string, cursor?: string, pageSize?: number) { const query = new URLSearchParams(); if (cursor) query.set('cursor', cursor); if (pageSize !== undefined) query.set('page_size', String(pageSize)); return this.request<SourceVersionList>(`/sources/${encodeURIComponent(id)}/versions${query.size ? `?${query}` : ''}`); }
  createCatalog(input: CatalogCreate, key: string) { return this.request<CatalogWriteView>('/admin/catalog', 'POST', input, key); }
  updateCatalog(id: string, input: CatalogUpdate, key: string) { return this.request<CatalogWriteView>(`/admin/catalog/${encodeURIComponent(id)}`, 'PATCH', input, key); }
  syncRuns(sourceId: 'D12', cursor?: string, pageSize?: number) {
    const query = new URLSearchParams(); if (cursor) query.set('cursor', cursor); if (pageSize !== undefined) query.set('page_size', String(pageSize));
    return this.request<SyncRunList>(`/admin/sources/${encodeURIComponent(sourceId)}/sync-runs${query.size ? `?${query}` : ''}`);
  }
  startSync(sourceId: 'D12', key: string) { return this.request<SyncActionView>(`/admin/sources/${encodeURIComponent(sourceId)}/sync-runs`, 'POST', {}, key); }
  syncRun(id: string) { return this.request<SyncRunView>(`/admin/sync-runs/${encodeURIComponent(id)}`); }
  cancelSync(id: string, key: string) { return this.request<SyncActionView>(`/admin/sync-runs/${encodeURIComponent(id)}/cancel`, 'POST', {}, key); }
  retrySync(id: string, key: string) { return this.request<SyncActionView>(`/admin/sync-runs/${encodeURIComponent(id)}/retry`, 'POST', {}, key); }
  indexRuns(sourceId: string, cursor?: string, pageSize?: number) {
    const query = new URLSearchParams(); if (cursor) query.set('cursor', cursor); if (pageSize !== undefined) query.set('page_size', String(pageSize));
    return this.request<IndexRunList>(`/admin/sources/${encodeURIComponent(sourceId)}/index-builds${query.size ? `?${query}` : ''}`);
  }
  buildIndex(sourceId: 'D12', acquisitionId: string, key: string) { return this.request<IndexActionView>(`/admin/sources/${encodeURIComponent(sourceId)}/index-builds`, 'POST', { acquisition_id: acquisitionId }, key); }
  indexRun(id: string) { return this.request<IndexRunView>(`/admin/index-builds/${encodeURIComponent(id)}`); }
  cancelIndex(id: string, key: string) { return this.request<IndexActionView>(`/admin/index-builds/${encodeURIComponent(id)}/cancel`, 'POST', {}, key); }
  retryIndex(id: string, key: string) { return this.request<IndexActionView>(`/admin/index-builds/${encodeURIComponent(id)}/retry`, 'POST', {}, key); }
  sourcePolicy(source: string, acquisition: string) { return this.request<PolicyView>(`/admin/sources/${encodeURIComponent(source)}/policies/${encodeURIComponent(acquisition)}`); }
  updateSourcePolicy(source: string, acquisition: string, input: PolicyInput, key: string) { return this.request<{ action_id: string; policy: PolicyView }>(`/admin/sources/${encodeURIComponent(source)}/policies/${encodeURIComponent(acquisition)}`, 'POST', input, key); }
  publishRelease(source: string, index: string, revision: number, key: string) { return this.request<ReleaseAction>(`/admin/sources/${encodeURIComponent(source)}/releases`, 'POST', { index_id: index, expected_policy_revision: revision }, key); }
  release(source: string, release: string) { return this.request<ReleaseView>(`/sources/${encodeURIComponent(source)}/releases/${encodeURIComponent(release)}`); }
  mounts(project: string, cursor?: string, pageSize?: number) { const query = new URLSearchParams(); if (cursor) query.set('cursor', cursor); if (pageSize !== undefined) query.set('page_size', String(pageSize)); return this.request<MountList>(`/projects/${encodeURIComponent(project)}/mounts${query.size ? `?${query}` : ''}`); }
  mount(project: string, mount: string) { return this.request<MountView>(`/projects/${encodeURIComponent(project)}/mounts/${encodeURIComponent(mount)}`); }
  createMount(project: string, snapshot: string, key: string) { return this.request<MountAction>(`/projects/${encodeURIComponent(project)}/mounts`, 'POST', { source_snapshot_id: snapshot }, key); }
  removeMount(project: string, mount: string, key: string) { return this.request<MountAction>(`/projects/${encodeURIComponent(project)}/mounts/${encodeURIComponent(mount)}/remove`, 'POST', {}, key); }
  mountManifest(project: string, mount: string) { return this.request<MountManifest>(`/projects/${encodeURIComponent(project)}/mounts/${encodeURIComponent(mount)}/manifest`); }
  validatedUploads(project: string, cursor?: string) { return this.request<ValidatedUploadList>(`/projects/${encodeURIComponent(project)}/uploads?state=VALIDATED${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`); }
  startImport(project: string, input: ImportInput, key: string) { return this.request<ImportAction>(`/projects/${encodeURIComponent(project)}/imports`, 'POST', input, key); }
  imports(project: string, cursor?: string) { return this.request<ImportList>(`/projects/${encodeURIComponent(project)}/imports${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`); }
  import(project: string, id: string) { return this.request<ImportView>(`/projects/${encodeURIComponent(project)}/imports/${encodeURIComponent(id)}`); }
  materials(project: string, cursor?: string, pageSize?: number) { const params = new URLSearchParams(); if (cursor) params.set('cursor', cursor); if (pageSize) params.set('page_size', String(pageSize)); return this.request<MaterialList>(`/projects/${encodeURIComponent(project)}/materials${params.size ? `?${params}` : ''}`); }
  material(project: string, id: string) { return this.request<MaterialView>(`/projects/${encodeURIComponent(project)}/materials/${encodeURIComponent(id)}`); }
  snapshots(project: string, cursor?: string) { return this.request<SnapshotList>(`/projects/${encodeURIComponent(project)}/snapshots${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`); }
  snapshot(project: string, snapshot: string) { return this.request<SnapshotView>(`/projects/${encodeURIComponent(project)}/snapshots/${encodeURIComponent(snapshot)}`); }
  createSnapshot(project: string, input: SnapshotInput | string, key: string) { return this.request<SnapshotAction>(`/projects/${encodeURIComponent(project)}/snapshots`, 'POST', typeof input === 'string' ? { mount_ids: [input] } : input, key); }
  retrySnapshot(project: string, snapshot: string, key: string) { return this.request<SnapshotAction>(`/projects/${encodeURIComponent(project)}/snapshots/${encodeURIComponent(snapshot)}/retry`, 'POST', {}, key); }
  queries(project: string, cursor?: string) { return this.request<QueryList>(`/projects/${encodeURIComponent(project)}/queries${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`); }
  query(project: string, run: string) { return this.request<QueryRunView>(`/projects/${encodeURIComponent(project)}/queries/${encodeURIComponent(run)}`); }
  createQuery(project: string, input: QueryInput, key: string) { return this.request<QueryAction>(`/projects/${encodeURIComponent(project)}/queries`, 'POST', input, key); }
  cancelQuery(project: string, run: string, key: string) { return this.request<QueryAction>(`/projects/${encodeURIComponent(project)}/queries/${encodeURIComponent(run)}/cancel`, 'POST', {}, key); }
  retryQuery(project: string, run: string, key: string) { return this.request<QueryAction>(`/projects/${encodeURIComponent(project)}/queries/${encodeURIComponent(run)}/retry`, 'POST', {}, key); }
  prepareResult(project: string, result: string, key: string) { return this.request<QueryAction>(`/projects/${encodeURIComponent(project)}/result-sets/${encodeURIComponent(result)}/prepare`, 'POST', {}, key); }
  result(project: string, result: string) { return this.request<QueryRunView>(`/projects/${encodeURIComponent(project)}/result-sets/${encodeURIComponent(result)}`); }
  hits(project: string, result: string, cursor?: string) { return this.request<HitPage>(`/projects/${encodeURIComponent(project)}/result-sets/${encodeURIComponent(result)}/hits${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`); }
  context(project: string, result: string, ordinal: number) { return this.request<ContextView>(`/projects/${encodeURIComponent(project)}/result-sets/${encodeURIComponent(result)}/hits/${ordinal}/context`); }
  evidenceList(project: string, cursor?: string, pageSize?: number) { return this.request<EvidenceList>(`/projects/${encodeURIComponent(project)}/evidence${this.listQuery(cursor, pageSize)}`); }
  evidence(project: string, id: string) { return this.request<EvidenceView>(`/projects/${encodeURIComponent(project)}/evidence/${encodeURIComponent(id)}`); }
  createEvidence(project: string, result: string, ordinal: number, key: string) { return this.request<EvidenceAction>(`/projects/${encodeURIComponent(project)}/evidence`, 'POST', { result_set_id: result, ordinal }, key); }
  notes(project: string, cursor?: string, pageSize?: number) { return this.request<NoteList>(`/projects/${encodeURIComponent(project)}/notes${this.listQuery(cursor, pageSize)}`); }
  note(project: string, id: string, revision?: number) { return this.request<NoteView>(`/projects/${encodeURIComponent(project)}/notes/${encodeURIComponent(id)}${revision === undefined ? '' : `?revision=${revision}`}`); }
  noteRevisions(project: string, id: string, cursor?: string) { return this.request<NoteList>(`/projects/${encodeURIComponent(project)}/notes/${encodeURIComponent(id)}/revisions${this.listQuery(cursor)}`); }
  createNote(project: string, input: NoteInput, key: string) { return this.request<NoteAction>(`/projects/${encodeURIComponent(project)}/notes`, 'POST', input, key); }
  updateNote(project: string, id: string, input: NoteUpdate, key: string) { return this.request<NoteAction>(`/projects/${encodeURIComponent(project)}/notes/${encodeURIComponent(id)}`, 'PATCH', input, key); }
  acceptNote(project: string, id: string, revision: number, key: string) { return this.request<NoteAction>(`/projects/${encodeURIComponent(project)}/notes/${encodeURIComponent(id)}/accept`, 'POST', { expected_revision: revision }, key); }
  exports(project: string, cursor?: string, pageSize?: number) { return this.request<ExportList>(`/projects/${encodeURIComponent(project)}/exports${this.listQuery(cursor, pageSize)}`); }
  export(project: string, id: string) { return this.request<ExportView>(`/projects/${encodeURIComponent(project)}/exports/${encodeURIComponent(id)}`); }
  createExport(project: string, input: ExportInput, key: string) { return this.request<ExportAction>(`/projects/${encodeURIComponent(project)}/exports`, 'POST', input, key); }
  async downloadExport(project: string, id: string) {
    const response = await this.transport(`${this.base}/api/v1/projects/${encodeURIComponent(project)}/exports/${encodeURIComponent(id)}/download`, { credentials: 'include', redirect: 'error', signal: AbortSignal.timeout(120000) });
    if (!response.ok) throw new ApiError(response.status, await response.json().catch(() => ({})));
    return response.blob();
  }
  private listQuery(cursor?: string, pageSize?: number) { const q = new URLSearchParams(); if (cursor) q.set('cursor', cursor); if (pageSize !== undefined) q.set('page_size', String(pageSize)); return q.size ? `?${q}` : ''; }

}
