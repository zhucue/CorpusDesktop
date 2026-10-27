import { evidenceMetadata, noteMetadata, exportMetadata } from '../../../contracts/types/outcomes.ts';
import { importMetadata, materialMetadata } from '../../../contracts/types/materials.ts';
/** Explicit contract adapters. Production delegated Pi authorization is not accepted.
 * Every operation goes through the same authenticated HTTP routes as the browser.
 * No credential, URL, actor, SQL or arbitrary method is accepted from model arguments.
 */
import { Type, type Static, type TSchema } from 'typebox';
import { Check } from 'typebox/value';
import { CorpusApiClient, type JobView } from '../../../contracts/types/s1.ts';
import { snapshotMetadata, resultMetadata } from '../../../contracts/types/research.ts';

const id = () => Type.String({ minLength: 1, maxLength: 200 });
const empty = Type.Object({}, { additionalProperties: false });
const exactObject = <T extends Record<string, TSchema>>(fields: T) => Type.Object(fields, { additionalProperties: false });
function researchQuerySchema() {
  const gap = exactObject({ type: Type.Literal('gap'), min: Type.Integer({ minimum: 0 }), max: Type.Integer({ minimum: 0 }) });
  const character = exactObject({ type: Type.Literal('literal'), value: Type.String({ minLength: 1 }) });
  const token = exactObject({ type: Type.Literal('term'), attr: Type.Literal('form'), op: Type.Literal('eq'), value: Type.String({ minLength: 1, maxLength: 1024 }) });
  function branch(unit: 'character' | 'token', atom: TSchema) {
    const sequence = exactObject({ type: Type.Literal('sequence'), items: Type.Array(Type.Union([atom, gap]), { minItems: 2 }) });
    return exactObject({ dsl_version: Type.Literal('corpus-query/v1'), unit: Type.Literal(unit), within: Type.Literal('sentence'), overlap: Type.Literal('all'),
      normalization: Type.Optional(Type.Literal('none')), sort: Type.Optional(Type.Tuple([Type.Literal('document_ordinal'), Type.Literal('start'), Type.Literal('end')])),
      pattern: Type.Union([atom, sequence, exactObject({ type: Type.Literal('any_of'), patterns: Type.Array(Type.Union([atom, sequence]), { minItems: 2 }) })]) });
  }
  return Type.Union([branch('character', character), branch('token', token)]);
}
export type TrustedToolContext = {
  scope: { kind: 'account' } | { kind: 'platform' } | { kind: 'project'; projectId: string };
  /** Must return the same key for retries of the same trusted invocation and operation. */
  idempotencyKey: (invocationId: string, capability: string) => string;
};

export function createS1ContractTools(client: CorpusApiClient, context: TrustedToolContext) {
  function projectId() {
    if (context.scope.kind !== 'project') throw new Error('PROJECT_SCOPE_REQUIRED');
    return context.scope.projectId;
  }
  async function scopedJob(jobId: string): Promise<JobView> {
    const job = await client.job(jobId);
    if (job.project_id !== projectId()) throw new Error('JOB_OUT_OF_SCOPE');
    return job;
  }
  function jobMetadata(job: JobView) {
    if (job.kind === 'EXPORT') return { job_id: job.job_id, export_id: job.job_id, project_id: job.project_id, kind: job.kind, state: job.state, next_action: 'exports.get' };
    if (job.kind !== 'TXT_IMPORT') return job;
    return { job_id: job.job_id, import_id: job.job_id, project_id: job.project_id, kind: job.kind, state: job.state,
      material_revision_id: job.result?.state === 'READY' && 'material_revision_id' in job.result ? job.result.material_revision_id : null, next_action: 'imports.get' };
  }
  function tool<T extends TSchema>(capability: string, parameters: T, handler: (input: Static<T>, invocation: string) => Promise<unknown>) {
    return {
      name: capability.replaceAll('.', '_'), label: capability, description: `S1 explicit ${capability} adapter. Contract tests only; production delegation unavailable.`,
      capability_id: capability, production_available: false, parameters,
      async execute(invocationId: string, input: unknown) {
        if (!Check(parameters, input)) throw new Error('INVALID_TOOL_INPUT');
        const result = await handler(input as Static<T>, invocationId);
        return { content: [{ type: 'text' as const, text: JSON.stringify(result ?? null) }], details: result };
      },
    };
  }
  const account = [
    tool('account.get', empty, async () => (await client.session()).actor),
    tool('projects.list', empty, async () => client.projects()),
    tool('projects.create', Type.Object({ name: Type.String({ minLength: 1, maxLength: 160 }) }, { additionalProperties: false }), async args => client.createProject(args.name)),
  ];
  const sourceId = Type.String({ pattern: '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$' });
  const sourceInput = Type.Object({ source_id: sourceId }, { additionalProperties: false });
  const releaseUuid = Type.String({ pattern: '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$' });
  const pagination = { cursor: Type.Optional(Type.String({ maxLength: 512 })), page_size: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })) };
  const sourceTools = [
    tool('releases.get', Type.Object({ source_id: sourceId, release_id: releaseUuid }, { additionalProperties: false }), async args => client.release(args.source_id, args.release_id)),
    tool('sources.list', Type.Object({ q: Type.Optional(Type.String({ maxLength: 160 })), language: Type.Optional(Type.String({ maxLength: 48 })), category: Type.Optional(Type.String({ maxLength: 48 })), status: Type.Optional(Type.Union(['catalog_only', 'verification_pending', 'experimental_evidence'].map(value => Type.Literal(value)))), capability: Type.Optional(Type.Union(['discover', 'remote_query', 'fulltext_analysis', 'export', 'model_egress'].map(value => Type.Literal(value)))), cursor: Type.Optional(Type.String({ maxLength: 512 })), page_size: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })) }, { additionalProperties: false }), async args => client.sources(args)),
    tool('sources.get', sourceInput, async args => client.source(args.source_id)),
    tool('sources.versions', Type.Object({ source_id: sourceId, cursor: Type.Optional(Type.String({ maxLength: 512 })), page_size: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })) }, { additionalProperties: false }), async args => client.sourceVersions(args.source_id, args.cursor, args.page_size)),
  ];
  if (context.scope.kind === 'account') return [...account, ...sourceTools];
  if (context.scope.kind === 'platform') {
    const syncRef = Type.Object({ sync_run_id: Type.String({ pattern: '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$' }) }, { additionalProperties: false });
    const uuid = Type.String({ pattern: '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$' });
    const indexRef = Type.Object({ index_run_id: uuid }, { additionalProperties: false });
    const taskRef = Type.Union([syncRef, indexRef]);
    const syncSource = { source_id: Type.Literal('D12') };
    const pagination = { cursor: Type.Optional(Type.String({ maxLength: 512 })), page_size: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })) };
    const taskList = Type.Union([
      Type.Object({ ...syncSource, ...pagination }, { additionalProperties: false }),
      Type.Object({ ...syncSource, ...pagination, task_kind: Type.Literal('source_index') }, { additionalProperties: false }),
    ]);
    const metadata = {
      name: Type.String({ minLength: 1, maxLength: 160 }), publisher: Type.String({ minLength: 1, maxLength: 200 }),
      entry_kind: Type.Union(['publisher', 'aggregator', 'dataset'].map(value => Type.Literal(value))),
      categories: Type.Array(Type.String({ minLength: 1, maxLength: 48 }), { minItems: 1, maxItems: 12, uniqueItems: true }),
      languages: Type.Array(Type.String({ minLength: 1, maxLength: 48 }), { minItems: 1, maxItems: 12, uniqueItems: true }),
      // This is stored source metadata, never an HTTP destination for the client.
      official_url: Type.String({ minLength: 1, maxLength: 2048, pattern: '^https?://' }),
      materials: Type.String({ minLength: 1, maxLength: 2000 }), access_route: Type.String({ minLength: 1, maxLength: 2000 }), boundary: Type.String({ minLength: 1, maxLength: 4000 }),
    };
    return [account[0], ...sourceTools,
      tool('policies.get', Type.Object({ policy_kind: Type.Literal('source'), source_id: sourceId, acquisition_id: uuid }, { additionalProperties: false }), async args => client.sourcePolicy(args.source_id, args.acquisition_id)),
      tool('policies.update', Type.Object({ policy_kind: Type.Literal('source'), source_id: sourceId, acquisition_id: uuid, expected_revision: Type.Integer({ minimum: 0 }), decision: Type.Union([Type.Literal('allow'), Type.Literal('deny')]), review_note: Type.String({ minLength: 1, maxLength: 4000 }), evidence_urls: Type.Array(Type.String({ pattern: '^https?://', maxLength: 2048 }), { minItems: 1, maxItems: 12 }) }, { additionalProperties: false }), async () => { throw new Error('HUMAN_AUTHORIZATION_REQUIRED'); }),
      tool('releases.publish', Type.Object({ source_id: sourceId, index_id: uuid, expected_policy_revision: Type.Integer({ minimum: 1 }) }, { additionalProperties: false }), async (args, invocation) => client.publishRelease(args.source_id, args.index_id, args.expected_policy_revision, context.idempotencyKey(invocation, 'releases.publish'))),
      tool('sync.start', Type.Object(syncSource, { additionalProperties: false }), async (args, invocation) => client.startSync(args.source_id, context.idempotencyKey(invocation, 'sync.start'))),
      tool('sync.report', syncRef, async args => client.syncRun(args.sync_run_id)),
      tool('indexes.build', Type.Object({ ...syncSource, acquisition_id: uuid }, { additionalProperties: false }), async (args, invocation) => client.buildIndex(args.source_id, args.acquisition_id, context.idempotencyKey(invocation, 'indexes.build'))),
      tool('indexes.report', indexRef, async args => client.indexRun(args.index_run_id)),
      tool('jobs.list', taskList, async args => 'task_kind' in args ? client.indexRuns(args.source_id, args.cursor, args.page_size) : client.syncRuns(args.source_id, args.cursor, args.page_size)),
      tool('jobs.get', taskRef, async args => 'index_run_id' in args ? client.indexRun(args.index_run_id) : client.syncRun(args.sync_run_id)),
      tool('jobs.cancel', taskRef, async (args, invocation) => 'index_run_id' in args ? client.cancelIndex(args.index_run_id, context.idempotencyKey(invocation, 'jobs.cancel')) : client.cancelSync(args.sync_run_id, context.idempotencyKey(invocation, 'jobs.cancel'))),
      tool('jobs.retry', taskRef, async (args, invocation) => 'index_run_id' in args ? client.retryIndex(args.index_run_id, context.idempotencyKey(invocation, 'jobs.retry')) : client.retrySync(args.sync_run_id, context.idempotencyKey(invocation, 'jobs.retry'))),
      tool('catalog.create', Type.Object({ ...metadata, source_id: sourceId }, { additionalProperties: false }), async (args, invocation) => client.createCatalog(args, context.idempotencyKey(invocation, 'catalog.create'))),
      tool('catalog.update', Type.Object({ ...metadata, source_id: sourceId, expected_revision: Type.Integer({ minimum: 1 }) }, { additionalProperties: false }), async ({ source_id, ...args }, invocation) => client.updateCatalog(source_id, args, context.idempotencyKey(invocation, 'catalog.update'))),
    ];
  }
  const noteFields = { title: Type.String({ minLength: 1, maxLength: 160 }), body: Type.String({ minLength: 1, maxLength: 100000 }), evidence_ids: Type.Optional(Type.Array(releaseUuid, { maxItems: 100, uniqueItems: true })), query_run_ids: Type.Optional(Type.Array(releaseUuid, { maxItems: 16, uniqueItems: true })) };
  const exportTarget = Type.Union([
    exactObject({ kind: Type.Literal('query_runs'), query_run_ids: Type.Array(releaseUuid, { minItems: 1, maxItems: 16, uniqueItems: true }) }),
    exactObject({ kind: Type.Literal('note_revision'), note_id: releaseUuid, revision: Type.Integer({ minimum: 1 }) }),
  ]);
  return [
    account[0], ...sourceTools,
    tool('evidence.create', exactObject({ result_set_id: releaseUuid, ordinal: Type.Integer({ minimum: 0 }) }), async (args, invocation) => { const value = await client.createEvidence(projectId(), args.result_set_id, args.ordinal, context.idempotencyKey(invocation, 'evidence.create')); return { action_id: value.action_id, existing: value.existing, ...evidenceMetadata(value.evidence) }; }),
    tool('evidence.list', exactObject(pagination), async args => { const value = await client.evidenceList(projectId(), args.cursor, args.page_size); return { project_id: projectId(), items: value.items.map(evidenceMetadata), next_cursor: value.next_cursor, total: value.total }; }),
    tool('evidence.get', exactObject({ evidence_id: releaseUuid }), async () => { throw new Error('MODEL_EGRESS_DENIED'); }),
    tool('notes.list', exactObject(pagination), async args => { const value = await client.notes(projectId(), args.cursor, args.page_size); return { project_id: projectId(), items: value.items.map(noteMetadata), next_cursor: value.next_cursor, total: value.total }; }),
    tool('notes.get', exactObject({ note_id: releaseUuid, revision: Type.Optional(Type.Integer({ minimum: 1 })) }), async () => { throw new Error('MODEL_EGRESS_DENIED'); }),
    tool('notes.create', exactObject(noteFields), async () => { throw new Error('MODEL_EGRESS_DENIED'); }),
    tool('notes.update', exactObject({ ...noteFields, note_id: releaseUuid, expected_revision: Type.Integer({ minimum: 1 }) }), async () => { throw new Error('MODEL_EGRESS_DENIED'); }),
    tool('notes.accept', exactObject({ note_id: releaseUuid, expected_revision: Type.Integer({ minimum: 1 }) }), async () => { throw new Error('HUMAN_AUTHORIZATION_REQUIRED'); }),
    tool('exports.create', exactObject({ target: exportTarget, format: Type.Union([Type.Literal('csv'), Type.Literal('json')]) }), async (args, invocation) => { const value = await client.createExport(projectId(), args, context.idempotencyKey(invocation, 'exports.create')); return { action_id: value.action_id, ...exportMetadata(value.run) }; }),
    tool('exports.list', exactObject(pagination), async args => { const value = await client.exports(projectId(), args.cursor, args.page_size); return { project_id: projectId(), items: value.items.map(exportMetadata), next_cursor: value.next_cursor, total: value.total }; }),
    tool('exports.get', exactObject({ export_id: releaseUuid }), async args => exportMetadata(await client.export(projectId(), args.export_id))),
    tool('snapshots.create', Type.Object({ mount_ids: Type.Optional(Type.Array(releaseUuid, { maxItems: 16, uniqueItems: true })), material_revision_ids: Type.Optional(Type.Array(releaseUuid, { maxItems: 16, uniqueItems: true })) }, { additionalProperties: false }), async (args, invocation) => {
      const members = { mount_ids: args.mount_ids ?? [], material_revision_ids: args.material_revision_ids ?? [] };
      if (members.mount_ids.length + members.material_revision_ids.length < 1 || members.mount_ids.length + members.material_revision_ids.length > 16) throw new Error('INVALID_TOOL_INPUT');
      const value = await client.createSnapshot(projectId(), members, context.idempotencyKey(invocation, 'snapshots.create'));
      return { action_id: value.action_id, ...snapshotMetadata(value.snapshot), next_action: 'snapshots.get' };
    }),
    tool('imports.start', Type.Object({ upload_id: releaseUuid, language: Type.Union([Type.Literal('cmn'), Type.Literal('eng')]) }, { additionalProperties: false }), async (args, invocation) => { const value = await client.startImport(projectId(), args, context.idempotencyKey(invocation, 'imports.start')); return { action_id: value.action_id, ...importMetadata(value.run) }; }),
    tool('imports.get', Type.Object({ import_id: releaseUuid }, { additionalProperties: false }), async args => importMetadata(await client.import(projectId(), args.import_id))),
    tool('materials.list', Type.Object(pagination, { additionalProperties: false }), async args => { const value = await client.materials(projectId(), args.cursor, args.page_size); return { items: value.items.map(materialMetadata), next_cursor: value.next_cursor }; }),
    tool('materials.get', Type.Object({ material_id: releaseUuid }, { additionalProperties: false }), async args => materialMetadata(await client.material(projectId(), args.material_id))),
    tool('snapshots.get', Type.Object({ snapshot_id: releaseUuid }, { additionalProperties: false }), async args => snapshotMetadata(await client.snapshot(projectId(), args.snapshot_id))),
    tool('corpus.describe', Type.Object({ snapshot_id: releaseUuid }, { additionalProperties: false }), async args => snapshotMetadata(await client.snapshot(projectId(), args.snapshot_id))),
    tool('results.get', Type.Object({ result_set_id: releaseUuid }, { additionalProperties: false }), async args => resultMetadata(await client.result(projectId(), args.result_set_id))),
    // These registered boundaries deliberately perform no HTTP/material read.
    tool('corpus.search', Type.Object({ snapshot_id: releaseUuid, query: researchQuerySchema(), page_size: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })), context_codepoints: Type.Optional(Type.Integer({ minimum: 0, maximum: 200 })) }, { additionalProperties: false }), async () => { throw new Error('SNAPSHOT_SCOPE_UNAVAILABLE'); }),
    tool('results.context', Type.Object({ result_set_id: releaseUuid, ordinal: Type.Integer({ minimum: 0 }) }, { additionalProperties: false }), async () => { throw new Error('MODEL_EGRESS_DENIED'); }),
    tool('mounts.list', Type.Object(pagination, { additionalProperties: false }), async args => client.mounts(projectId(), args.cursor, args.page_size)),
    tool('mounts.get', Type.Object({ mount_id: releaseUuid }, { additionalProperties: false }), async args => client.mount(projectId(), args.mount_id)),
    tool('mounts.manifest', Type.Object({ mount_id: releaseUuid }, { additionalProperties: false }), async args => client.mountManifest(projectId(), args.mount_id)),
    tool('mounts.create', Type.Object({ source_snapshot_id: releaseUuid }, { additionalProperties: false }), async (args, invocation) => client.createMount(projectId(), args.source_snapshot_id, context.idempotencyKey(invocation, 'mounts.create'))),
    tool('mounts.remove', Type.Object({ mount_id: releaseUuid }, { additionalProperties: false }), async (args, invocation) => client.removeMount(projectId(), args.mount_id, context.idempotencyKey(invocation, 'mounts.remove'))),
    tool('projects.get', empty, async () => client.project(projectId())),
    tool('members.list', empty, async () => client.members(projectId())),
    tool('members.update', Type.Object({ user_id: id(), role: Type.Union([Type.Literal('editor'), Type.Literal('viewer')]) }, { additionalProperties: false }), async args => client.setMember(projectId(), args.user_id, args.role)),
    tool('members.remove', Type.Object({ user_id: id() }, { additionalProperties: false }), async args => { await client.removeMember(projectId(), args.user_id); return { removed: true }; }),
    tool('uploads.create', Type.Object({ filename: Type.String({ minLength: 1, maxLength: 255 }), size: Type.Integer({ minimum: 1, maximum: 100000000 }), media_type: Type.Union(['text/plain', 'text/csv', 'text/tab-separated-values', 'application/json', 'application/x-ndjson'].map(value => Type.Literal(value))), sha256: Type.String({ pattern: '^[a-f0-9]{64}$' }) }, { additionalProperties: false }), async (args, invocation) => {
      const response = await client.createUpload(projectId(), args, context.idempotencyKey(invocation, 'uploads.create'));
      // Transport URLs and headers stay with the browser/host, outside model results.
      return { upload_id: response.upload_id, action_id: response.action_id, project_id: response.project_id, state: response.state, next_action: 'browser_file_transfer' };
    }),
    tool('uploads.complete', Type.Object({ upload_id: id() }, { additionalProperties: false }), async (args, invocation) => {
      const upload = await client.upload(args.upload_id);
      if (upload.project_id !== projectId()) throw new Error('UPLOAD_OUT_OF_SCOPE');
      return client.completeUpload(args.upload_id, context.idempotencyKey(invocation, 'uploads.complete'));
    }),
    tool('jobs.list', Type.Object({ cursor: Type.Optional(id()) }, { additionalProperties: false }), async args => { const value = await client.jobs(projectId(), args.cursor); return { ...value, items: value.items.map(jobMetadata) }; }),
    tool('jobs.get', Type.Object({ job_id: id() }, { additionalProperties: false }), async args => jobMetadata(await scopedJob(args.job_id))),
    tool('jobs.cancel', Type.Object({ job_id: id() }, { additionalProperties: false }), async (args, invocation) => {
      await scopedJob(args.job_id); return jobMetadata(await client.cancelJob(args.job_id, context.idempotencyKey(invocation, 'jobs.cancel')));
    }),
    tool('jobs.retry', Type.Object({ job_id: id() }, { additionalProperties: false }), async (args, invocation) => {
      await scopedJob(args.job_id); return jobMetadata(await client.retryJob(args.job_id, context.idempotencyKey(invocation, 'jobs.retry')));
    }),
  ];
}
