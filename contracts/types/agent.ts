/** Safe browser projection; never SDK archives, execution credentials or tool payloads. */
export type AgentScope = { scope_kind: 'account' | 'platform' } | {
  scope_kind: 'project'; project_id: string; snapshot_ids: []; material_revision_ids: [];
  alignment_overlay_revision: null; result_refs: [];
};
export type AgentState = 'QUEUED' | 'RUNNING' | 'WAITING_JOB' | 'WAITING_REVIEW' | 'CANCELLED' | 'SUCCEEDED' | 'FAILED';
export type AgentConfigID = 'local-fixture-v1' | `openai-${string}`;
type ManifestBase = { sdk_package: '@earendil-works/pi-coding-agent'; sdk_version: '1.3.0'; session_version: 3; tool_schema: 's3-outcomes-tools-v1' };
export type FixtureManifest = ManifestBase & { host_policy: 'corpus-k09-linear-v1'; provider: 'corpus-s1-fixed'; model: 'fixed-project-v1'; resource_config: 'corpus-empty-resources-v1' };
export type OpenAIManifest = ManifestBase & { host_policy: 'corpus-k09-openai-v1'; provider: 'corpus-openai-compatible'; model: string; resource_config: 'corpus-explicit-resources-v1'; model_api: 'openai-completions' | 'openai-responses'; model_config_sha256: string };
export type AgentRuntime = { production_ready: false } & (
  { mode: 'unconfigured'; fixture_enabled: false; can_submit: false; config_id: null; reason: 'MODEL_NOT_CONFIGURED'; runtime_manifest: null } |
  { mode: 'fixture'; fixture_enabled: true; can_submit: true; config_id: 'local-fixture-v1'; reason: null; runtime_manifest: FixtureManifest } |
  { mode: 'openai-compatible'; fixture_enabled: false; can_submit: false; config_id: null; reason: 'MODEL_CONFIGURATION_INVALID'; runtime_manifest: null } |
  { mode: 'openai-compatible'; fixture_enabled: false; can_submit: true; config_id: `openai-${string}`; reason: null; runtime_manifest: OpenAIManifest }
);
export type AgentSession = {
  session_id: string; scope: AgentScope; scope_digest: string; config_id: AgentConfigID;
  active_run_id: string | null; latest_checkpoint_id: string | null; lease_epoch: number; created_at: string;
};
export type AgentRun = {
  run_id: string; session_id: string; state: AgentState; reason: string | null;
  scope_digest: string; config_id: AgentConfigID; lease_epoch: number; lease_expires_at: string | null;
  event_sequence: number; allowed_tools: string[]; base_checkpoint_id: string | null;
  final_checkpoint_id: string | null; resume_checkpoint_id: string | null;
  waiting_jobs: { invocation_id: string; job_id: string; kind: 'job' | 'sync' | 'index' | 'research'; report_tool: string; report_arguments: Record<string, unknown>; state: string }[];
  active_deadline_at: string | null; wait_deadline_at: string | null; created_at: string; updated_at: string;
};
export type AgentResultView = { kind: 'project' | 'material' | 'snapshot' | 'query' | 'evidence' | 'note' | 'export' | 'job'; resource_id: string };
export type AgentTurn = {
  run_id: string; user_message: string; assistant_messages: { id: string; text: string }[];
  tools: { invocation_id: string; tool_name: string; status: string; result_view: AgentResultView | null }[];
  state: AgentState; created_at: string;
};
export type AgentEvent = { event_id: string; sequence: number; kind: string; payload: Record<string, unknown>; created_at: string };
export type AgentPage<T> = { items: T[]; next_before: string | null };
export type AgentRunInput = { request_key: string; message: string; scope_digest: string };
