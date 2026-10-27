"""Generate the static S0 contract artifacts; no runtime handlers are registered here."""
import json
from pathlib import Path

ROOT = Path(__file__).parent
DIALECT = 'https://json-schema.org/draft/2020-12/schema'
BASE = 'https://corpus.invalid/contracts/'
ID = {'type': 'string', 'minLength': 1, 'maxLength': 200}
TEXT = {'type': 'string', 'minLength': 1}
INT = {'type': 'integer', 'minimum': 0}


def obj(properties, required=None):
    return {'type': 'object', 'properties': properties,
            'required': list(properties) if required is None else required,
            'additionalProperties': False}


def arr(items, minimum=0):
    return {'type': 'array', 'items': items, 'minItems': minimum}


def ref(name):
    return {'$ref': name + '.schema.json'}


def save(name, schema):
    if isinstance(schema, dict):
        schema = {'$schema': DIALECT, '$id': BASE + name + '.schema.json', **schema}
    (ROOT / 'schemas').mkdir(exist_ok=True)
    (ROOT / 'schemas' / (name + '.schema.json')).write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


# Explicit action inventory. No arbitrary HTTP route, SQL, shell, or file access tool.
GROUPS = [
 ('M01','S1','F012 F016', 'sources.list sources.get sources.versions catalog.create catalog.update'),
 ('M02','S2','F013 F016 F070', 'sync.check sync.start sync.report releases.publish sync.schedule.get sync.schedule.update'),
 ('M02','S3','F013 F016 F070', 'indexes.build indexes.report releases.get'),
 ('M03','S1','F081 F084', 'account.get members.list members.invite members.update members.remove'),
 ('M03','S1','F001 F084', 'projects.list projects.get projects.create projects.update projects.archive'),
 ('M03','S3','F006 F013 F084', 'mounts.list mounts.get mounts.manifest mounts.create mounts.remove'),
 ('M04','S1','F009 F010', 'uploads.create uploads.complete'),
 ('M04','S3','F009 F010', 'imports.start imports.get materials.list materials.get'),
 ('M04','S3','F014 F015 F017', 'processing.preview processing.run'),
 ('M04','S3','F007 F014 F015', 'quality.get'),
 ('M05','S5','F003 F005', 'subcorpora.list subcorpora.create subcorpora.update'),
 ('M05','S3','F006 F007', 'snapshots.preview snapshots.create snapshots.get'),
 ('M06','S3','F025 F026 F028', 'queries.validate corpus.describe corpus.search'),
 ('M07','S3','F029', 'results.get results.context'),
 ('M07','S3','F029 F074', 'evidence.get evidence.create evidence.list'),
 ('M07','S5','F028 F029', 'results.filter'),
 ('M07','S5','F030', 'results.sample bookmarks.list bookmarks.create bookmarks.remove savedQueries.list savedQueries.create savedQueries.update savedQueries.run'),
 ('M08','S5','F033 F034', 'analysis.frequency'),
 ('M08','S5','F035', 'analysis.ngrams'),
 ('M08','S5','F041 F042', 'analysis.collocations'),
 ('M09','S5','F036 F037', 'analysis.keywords'),
 ('M09','S5','F046', 'analysis.distribution analysis.compare'),
 ('M09','S5','F036 F037 F046', 'charts.get'),
 ('M10','S3','F031 F052', 'parallel.search'),
 ('M10','S6','F049 F067', 'alignment.start alignment.get alignment.candidates alignment.candidates.review alignment.layers.create alignment.commits.create'),
 ('M11','S3','F069 F073 F074', 'notes.list notes.get notes.create notes.update notes.accept'),
 ('M11','S7','F001 F065', 'research.plan'),
 ('M12','S3','F076 F078', 'exports.create exports.get exports.list artifacts.list artifacts.get'),
 ('M13','S1','F070 F089 F093', 'jobs.list jobs.get jobs.cancel jobs.retry invocations.get'),
 ('M13','S4','F013 F087', 'sources.impact sources.withdraw'),
 ('M14','S1','F090 F093', 'system.status system.versions'),
 ('M14','S1','F084 F091 F094', 'account.capabilities'),
 ('M14','S1','F093', 'account.quota'),
 ('M11','S3','F001 F065', 'research.questions.list research.questions.create research.questions.update research.plans.get research.plans.save'),
 ('M04','S4','F002', 'metadata.schemas.get metadata.schemas.update metadata.validate metadata.commit'),
 ('M05','S5','F005', 'selection.records.list selection.records.commit'),
 ('M04','S4','F017', 'processing.recipes.get processing.recipes.create dictionaries.get dictionaries.update'),
 ('M07','S5','F032', 'discovery.search'),
 ('M11','S7','F071', 'models.list policies.get policies.update usage.get audit.list'),
 ('M11','S6','F073 F074', 'references.list references.create references.update claims.list claims.create claims.update'),
 ('M12','S6','F079', 'projectBackups.create projectBackups.get projectBackups.validate backupUploads.create backupUploads.complete projectRestores.preview projectRestores.start'),
 ('M14','S7','F087 F093', 'quotas.get quotas.update'),
 ('M03','S4','F087', 'projects.deletionImpact projects.delete projects.restore'),
 ('M04','S4','F087', 'materials.deletionImpact materials.delete materials.restore'),
 ('M02','S2','F013', 'connectors.get connectors.update'),
 ('M03','S4','F016', 'mounts.previewUpgrade mounts.upgrade'),
]
READ_VERBS = {'list','get','versions','report','preview','describe','validate','context',
              'manifest','sample','candidates','status','capabilities','quota','impact','deletionImpact','previewUpgrade'}
TASKS = set('uploads.complete sync.check sync.start imports.start processing.run snapshots.create corpus.search results.filter savedQueries.run analysis.frequency analysis.ngrams analysis.collocations analysis.keywords analysis.distribution analysis.compare parallel.search alignment.start exports.create jobs.retry projectBackups.create projectBackups.validate projectRestores.start discovery.search'.split())
PLATFORM = set('catalog.create catalog.update sync.check sync.start sync.report releases.publish sync.schedule.get sync.schedule.update sources.impact sources.withdraw connectors.get connectors.update policies.get policies.update quotas.get quotas.update'.split())
ACCOUNT = set('account.get projects.list projects.create system.status system.versions account.capabilities account.quota models.list usage.get backupUploads.create backupUploads.complete projectRestores.preview projectRestores.start'.split())
MULTI = set('sources.list sources.get sources.versions jobs.list jobs.get jobs.cancel jobs.retry invocations.get audit.list'.split())
PRODUCES = set('projects.create mounts.create mounts.remove mounts.upgrade imports.start processing.run snapshots.create alignment.commits.create metadata.commit projectRestores.start materials.delete materials.restore'.split())
DESTRUCTIVE = set('projects.archive projects.delete materials.delete sources.withdraw members.remove mounts.remove'.split())
ERRORS = {
 'AUTH_REQUIRED':401, 'FORBIDDEN':403, 'ACCESS_DENIED':403, 'MODEL_EGRESS_DENIED':403,
 'EXPORT_NOT_ALLOWED':403, 'SOURCE_RESTRICTED':403, 'RESOURCE_NOT_FOUND':404, 'NOT_FOUND':404,
 'SESSION_SCOPE_CHANGED':409, 'SESSION_BUSY':409, 'EDIT_CONFLICT':409,
 'CAPABILITY_UNAVAILABLE':409, 'IDEMPOTENCY_CONFLICT':409, 'RUN_FINISHED':409,
 'MESSAGE_ALREADY_STARTED':409, 'JOB_NOT_RETRYABLE':409, 'EXPORT_NOT_READY':409,
 'INVALID_INPUT':422, 'VALIDATION_ERROR':422, 'SCOPE_INVALID':422,
 'ENDPOINT_OUT_OF_SCOPE':422, 'QUERY_UNSUPPORTED':422, 'ATTRIBUTE_UNAVAILABLE':422,
 'FORMAT_UNSUPPORTED':422, 'EVIDENCE_INVALID':422, 'LANGUAGE_PAIR_UNAVAILABLE':422,
 'QUOTA_EXCEEDED':429, 'RATE_LIMITED':429, 'SERVICE_UNAVAILABLE':503,
}


def registry():
    from contracts.materials import MATERIAL_INPUTS
    from contracts.outcomes import OUTCOME_INPUTS
    from contracts.releases import RELEASE_INPUTS
    from contracts.research import RESEARCH_INPUTS
    from contracts.s1 import S1_INPUTS
    from contracts.s2 import S2_INPUTS
    from contracts.s3 import S3_INPUTS
    TASKS.add('indexes.build')
    PLATFORM.update({'indexes.build', 'indexes.report'})
    entries = []
    for module, stage, features, tools in GROUPS:
        for tool in tools.split():
            kind = 'task' if tool in TASKS else 'read' if tool.split('.')[-1] in READ_VERBS else 'write'
            scopes = ['account','platform','project'] if tool in MULTI else ['platform'] if tool in PLATFORM else ['account'] if tool in ACCOUNT else ['project']
            permission = ('manage_platform' if scopes == ['platform'] else
                          'manage_members' if tool.startswith('members.') and kind != 'read' else
                          'write_note' if tool.startswith('notes.') and kind != 'read' else
                          'export' if tool.startswith(('exports.','projectBackups.')) else
                          'create_analysis_run' if tool in TASKS and tool.startswith(('corpus.','parallel.','analysis.','results.','savedQueries.','discovery.')) else
                          'read_scope' if kind == 'read' else 'manage_account' if scopes == ['account'] else 'write_project_material')
            entries.append({
                'capability_id':tool, 'feature_ids':features.split(), 'module_id':module,
                'tool_name':tool, 'schema_version':'v1',
                'availability':{'status':'planned','stage':stage,'reason':'Backend action and joint manual/tool acceptance are not implemented.'},
                'handler':('queries.' if kind == 'read' else 'commands.') + tool,
                'operation_kind':kind, 'input_schema':'schemas/query-request.schema.json' if tool == 'corpus.search' else 'schemas/planned.schema.json',
                'output_schema':'schemas/tool-result.schema.json', 'permission':permission,
                'scope_kind':scopes, 'version_inputs':['snapshot_id','alignment_overlay_revision'] if scopes == ['project'] else [],
                'scope_effect':'produces_scope' if tool in PRODUCES else 'none',
                'authorization_policy':'explicit_user_confirmation' if tool == 'notes.accept' else 'destructive_target_authorization' if tool in DESTRUCTIVE else 'existing_authorization',
                'execution':'job' if tool in TASKS else 'synchronous',
                'idempotency':{'invocation_id':'host_assigned','action_id':'required' if kind != 'read' else 'not_applicable'},
                'result_view':{'kind':module,'reference_field':'result_ref'},
                'common_errors':['FORBIDDEN','RESOURCE_NOT_FOUND','CAPABILITY_UNAVAILABLE','INVALID_INPUT'],
            })
            if tool in S1_INPUTS:
                entries[-1]['input_schema'] = f'schemas/s1-{S1_INPUTS[tool]}.schema.json'
                entries[-1]['version_inputs'] = []
                entries[-1]['availability']['reason'] = 'Explicit HTTP adapter exists for contract tests; production Pi delegated authorization is not accepted.'
                if tool == 'account.get' or tool.startswith('sources.'):
                    entries[-1]['scope_kind'] = ['account', 'platform', 'project']
            if tool in S2_INPUTS:
                entries[-1]['input_schema'] = f'schemas/s2-{S2_INPUTS[tool]}.schema.json'
                entries[-1]['availability']['reason'] = 'S2 D12 admin acquisition adapter exists; production Pi delegation remains unaccepted and acquisitions are not public searchable releases.'
                if tool.startswith('jobs.'):
                    entries[-1]['scope_kind'] = ['project', 'platform']
                    entries[-1]['permission'] = 'current_scope_job_permission'
            if tool in S3_INPUTS:
                entries[-1]['input_schema'] = f'schemas/s3-{S3_INPUTS[tool]}.schema.json'
                entries[-1]['availability']['reason'] = 'Private index build adapter; HTTP acceptance pending. No publication, research access or production Pi authorization is conferred.'
            if tool in RELEASE_INPUTS:
                entries[-1]['input_schema'] = f'schemas/s3-release-{RELEASE_INPUTS[tool]}.schema.json'
                entries[-1]['availability'] = {'status': 'planned', 'stage': 'S3', 'reason': 'Fixed acquisition policy/publication and whole-source mounts accepted with synthetic-fixture HTTP/browser evidence; real D12 permission unapproved and production Pi unavailable.'}
                entries[-1]['version_inputs'] = []
                entries[-1]['scope_effect'] = 'none'
                if tool == 'releases.get':
                    entries[-1]['scope_kind'] = ['account', 'platform', 'project']
                if tool in {'policies.get', 'policies.update'}:
                    entries[-1]['module_id'] = 'M02'
                    entries[-1]['feature_ids'] = ['F016', 'F084']
            if tool in RESEARCH_INPUTS:
                entries[-1]['input_schema'] = f'schemas/s3-research-{RESEARCH_INPUTS[tool]}.schema.json'
                entries[-1]['version_inputs'] = ['mount_ids','material_revision_ids'] if tool == 'snapshots.create' else ['result_set_id'] if tool.startswith('results.') else ['snapshot_id']
                entries[-1]['availability']['reason'] = 'Manual fixed-snapshot query HTTP and browser slice accepted; metadata adapters preserve empty material scope. Pi material search/context denied and production delegation unaccepted.'
            if tool in MATERIAL_INPUTS:
                entries[-1]['input_schema'] = f'schemas/s3-private-{MATERIAL_INPUTS[tool]}.schema.json'
                entries[-1]['version_inputs'] = ['upload_id'] if tool == 'imports.start' else ['import_id'] if tool == 'imports.get' else ['material_id'] if tool == 'materials.get' else []
                entries[-1]['availability']['reason'] = 'Private TXT import and revision metadata adapter; scoped HTTP and browser acceptance passed. No model text, filenames or derived counts; production delegation remains unaccepted.'
            if tool in OUTCOME_INPUTS:
                entries[-1]['input_schema'] = f'schemas/s3-outcomes-{OUTCOME_INPUTS[tool]}.schema.json'
                entries[-1]['version_inputs'] = ['result_set_id'] if tool == 'evidence.create' else []
                entries[-1]['availability']['reason'] = 'Fixed evidence, immutable notes and complete authorized export manual HTTP/browser slice accepted. Material-bearing Pi operations and model-forged human acceptance remain denied; production tools stay planned.'
    (ROOT / 'capabilities.json').write_text(json.dumps({'schema_version':'v1','capabilities':entries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return entries


def build():
    from contracts.materials import MATERIAL_INPUTS, build_materials
    from contracts.outcomes import OUTCOME_INPUTS, build_outcomes
    from contracts.releases import RELEASE_INPUTS, build_releases
    from contracts.research import RESEARCH_INPUTS, build_research
    from contracts.s1 import S1_INPUTS, build_s1
    from contracts.s2 import S2_INPUTS, build_s2
    from contracts.s3 import S3_INPUTS, build_s3
    ERRORS.update({
        'HUMAN_AUTHORIZATION_REQUIRED':403, 'EXPORT_POLICY_DENIED':403, 'NOTE_REVISION_CONFLICT':409, 'EVIDENCE_UNAVAILABLE':404,
        'AUTH_INVALID':401, 'ORIGIN_FORBIDDEN':403, 'CSRF_INVALID':403,
        'PROJECT_NOT_FOUND':404, 'PROJECT_FORBIDDEN':403, 'OWNER_REQUIRED':409,
        'UPLOAD_TOO_LARGE':413, 'PROJECT_UPLOAD_QUOTA_EXCEEDED':413,
        'UNSUPPORTED_FORMAT':422, 'CHECKSUM_MISMATCH':422, 'SIZE_MISMATCH':422,
        'IDEMPOTENCY_KEY_REQUIRED':422, 'JOB_FINISHED':409, 'UPLOAD_NOT_READY':409,
        'UPLOAD_EXPIRED':410, 'UPLOAD_STATE_CONFLICT':409, 'DELIVERY_FAILED':503,
        'INVALID_TEXT_ENCODING':422, 'BINARY_CONTENT':422, 'STORAGE_UNAVAILABLE':503,
        'ORIGIN_REJECTED':403, 'CSRF_REJECTED':403, 'AUTH_RATE_LIMITED':429,
        'JSON_REQUIRED':415, 'OWNER_IMMUTABLE':409, 'ACCOUNT_NOT_FOUND':404, 'MEMBER_NOT_FOUND':404,
        'INVALID_CURSOR':422, 'UPLOAD_ALREADY_USED':409, 'UPLOAD_NOT_COMPLETE':409,
        'AUTHORIZATION_REVOKED':403, 'WORKER_LEASE_EXPIRED':409, 'UNSUPPORTED_CONTENT':422,
        'VALIDATION_TIMEOUT':504, 'UPLOAD_FAILED':503, 'STORAGE_VERSIONING_REQUIRED':503,
        'ADMIN_REQUIRED':403, 'SOURCE_NOT_FOUND':404, 'SOURCE_EXISTS':409, 'REVISION_CONFLICT':409,
        'CONNECTOR_UNAVAILABLE':422, 'SOURCE_IDENTITY_CHANGED':409, 'SYNC_RUN_NOT_FOUND':404,
        'SYNC_ALREADY_ACTIVE':409, 'SYNC_NOT_RETRYABLE':409, 'SYNC_ACTOR_REVOKED':403,
        'INDEX_RUN_NOT_FOUND':404, 'ACQUISITION_NOT_FOUND':404, 'INDEX_ALREADY_ACTIVE':409,
        'INDEX_QUOTA_EXCEEDED':409, 'INDEX_ALREADY_BUILT':409, 'INDEX_CLEANUP_REQUIRED':409,
        'INDEX_NOT_RETRYABLE':409, 'INDEX_ACTOR_REVOKED':403, 'INDEX_RECIPE_CHANGED':409,
        'SOURCE_POLICY_DENIED':403, 'SOURCE_POLICY_MISMATCH':403, 'POLICY_REVISION_CONFLICT':409,
        'POLICY_REPLAY_STALE':409, 'RELEASE_OBJECT_UNAVAILABLE':503, 'INDEX_NOT_FOUND':404,
        'INDEX_NOT_PUBLISHABLE':409, 'RELEASE_NOT_FOUND':404, 'MOUNT_NOT_FOUND':404,
        'MOUNT_REMOVED':403, 'INDEX_NOT_AVAILABLE':403,
        'SNAPSHOT_NOT_FOUND':404, 'SNAPSHOT_INVALID':409, 'SNAPSHOT_IDENTITY_CHANGED':403,
        'SNAPSHOT_NOT_READY':409, 'QUERY_NOT_FOUND':404, 'QUERY_QUOTA_EXCEEDED':409,
        'QUERY_CONTROL_DENIED':403, 'RETRY_NOT_ALLOWED':409, 'RESULT_NOT_COMPLETE':409,
        'CACHE_NOT_READY':503, 'HIT_NOT_FOUND':404, 'QUERY_FAILED':409, 'QUERY_CANCELLED':409,
        'SNAPSHOT_SCOPE_UNAVAILABLE':403,
        'UPLOAD_NOT_VALIDATED':409, 'TXT_REQUIRED':422, 'MATERIAL_REVISION_NOT_FOUND':404,
        'MATERIAL_IDENTITY_MISMATCH':409, 'MATERIAL_REVISION_CONFLICT':409,
    })
    entries = registry()
    (ROOT/'status.json').write_text(json.dumps({
        'stage':'S3', 'status':'implemented_http_slice_with_experimental_tool_adapters',
        'available_business_capabilities':0,
        'availability_scope':'production Pi tools; manual HTTP implementation is tracked separately',
        'manual_http':{'status':'implemented', 'capability_count':len(S1_INPUTS), 'coverage':'s1-capabilities.json',
                       'acceptance':'results/2026-10-16-s1-http-slice.json and results/2026-10-16-s1-catalog.json record separate scoped browser acceptance; not whole S1 acceptance'},
        'source_sync':{'status':'scoped_http_acquisition_accepted', 'coverage':'s2-capabilities.json',
                       'acceptance':'results/2026-10-16-s2-http-contracts-final.json validates captured HTTP; full acquisition evidence is in tests/integration/results/2026-10-16-source-sync.json',
                       'scope':'D12 platform-only acquisition; no public release or searchable index'},
        'source_index':{'status':'scoped_http_private_index_accepted', 'coverage':'s3-capabilities.json',
                        'acceptance':'results/2026-10-16-s3-index-contracts.json records scoped HTTP/browser and separate functional engine evidence; formal query performance remains unaccepted',
                        'scope':'D12 fixed acquisition to private INDEXED artifacts; no release, policy approval, mount or research access'},
        'tool_adapters':{'status':'contract_test_only','capability_count':len(set(S1_INPUTS) | set(S2_INPUTS) | set(S3_INPUTS) | set(RELEASE_INPUTS) | set(RESEARCH_INPUTS) | set(MATERIAL_INPUTS) | set(OUTCOME_INPUTS)),
                         'production_authorization':'not_accepted'},
        'source_publication':{'status':'scoped_fixture_http_mounts_accepted','coverage':'s3-release-capabilities.json',
                              'acceptance':'results/2026-10-17-s3-release-contracts.json and tests/integration/results/2026-10-17-source-releases.json',
                              'scope':'Explicit fixed-acquisition internal-research policy, fixed release and whole-source project mounts; real D12 not approved, no public query or model egress'},
        'project_research':{'status':'scoped_http_and_browser_accepted','coverage':'s3-research-capabilities.json',
                            'acceptance':'results/2026-10-17-s3-research-contracts.json and results/2026-10-17-s3-research-http-contracts.json; 8 response families, 12 captured responses; not whole S3 or production Pi acceptance',
                            'scope':'One fixed whole-source snapshot, manual sentence-local query, first page and asynchronous complete counts. Pi metadata only; two material adapters deny; production available remains zero'},
        'private_materials':{'status':'scoped_http_and_browser_accepted','coverage':'s3-private-capabilities.json','scope':'Fixed-language TXT to immutable revision; private/mixed snapshot indexing and exact document-unit counts; model material scope unchanged'},
        'research_outcomes':{'status':'scoped_http_and_browser_accepted','coverage':'s3-outcomes-capabilities.json','acceptance':'results/2026-10-17-s3-outcomes-contracts.json and results/2026-10-17-s3-outcomes-http-contracts-final.json; 11 response families and 30 captured responses; unsaved-leave dialog interaction remains unverified','scope':'Explicit complete-hit evidence, immutable notes and manual revision acceptance, complete CSV/JSON export under independent acquisition permission; no production Pi material scope'},
        'documented_action_inventory_count':len(entries),
        'schema_dialect':DIALECT,
        'validation_dependency':'jsonschema==4.26.0',
        'pending':[
            'Remaining planned actions need concrete schemas, handlers, permission rules and version inputs; S1 has a hand-maintained typed client',
            'Production Pi real-model, material authorization, in-flight recovery and full asynchronous continuation remain unaccepted; completed linear checkpoint restoration has separate passing evidence, all production tools remain planned',
            'Per-feature A/B/C/D and UI/operations acceptance audit; feature_ids are planning associations, not acceptance proof',
            'Continuation currently models corpus.search only; additional typed steps must be added with their business schemas',
            'Production tool model egress and authorization revalidation; S1 manual HTTP already enforces account/project permissions and fenced job cancellation',
            'Production Pi human-authorization credentials for alignment and notes; manual note revision acceptance has separate scoped passing evidence',
            'Production query integration and capacity acceptance; S0 subset engine/golden/measurement evidence does not enable regex or production tools',
            'Explicit permanent purge action contract and retention-policy authorization',
        ],
        'sources':['doc/assistant-capabilities.md','doc/business-architecture.md','doc/frontend-specification.md',
                   'https://json-schema.org/draft/2020-12/json-schema-validation',
                   'https://python-jsonschema.readthedocs.io/en/stable/validate/'],
    },indent=2)+'\n',encoding='utf-8')
    save('planned', False)
    refs = arr(ID)
    scope_project = obj({'scope_kind':{'const':'project'},'project_id':ID,
        'snapshot_ids':{**refs,'uniqueItems':True},'material_revision_ids':{**refs,'uniqueItems':True},
        'alignment_overlay_revision':{'oneOf':[{'type':'null'},obj({'layer_id':ID,'revision':INT})]},
        'result_refs':{**refs,'uniqueItems':True}}, ['scope_kind','project_id','snapshot_ids','material_revision_ids','alignment_overlay_revision'])
    save('scope', {'oneOf':[obj({'scope_kind':{'const':'account'}}),obj({'scope_kind':{'const':'platform'}}),scope_project]})
    save('scope-effect', {'oneOf':[obj({'kind':{'const':'none'}}),obj({'kind':{'const':'produces_scope'},'target_scope':ref('scope')})]})
    error = obj({'code':{'enum':list(ERRORS)},'message':TEXT,'request_id':ID,
                 'field_errors':arr(obj({'field':TEXT,'message':TEXT})), 'retryable':{'type':'boolean'}})
    save('error', error)
    version_ref = obj({'kind':{'enum':['source_release','snapshot','material_revision','alignment_overlay','recipe','engine','metadata_manifest']},'id':ID,'revision':{'type':['string','integer','null']}})
    version_refs = arr(version_ref)
    common = {'invocation_id':ID,'action_id':{'type':['string','null'],'minLength':1},'scope_ref':ref('scope'),
              'scope_effect':ref('scope-effect'),'version_refs':version_refs}
    save('tool-result', {'oneOf':[
        obj({**common,'status':{'const':'succeeded'},'result_ref':ID,'evidence_refs':refs,
             'method_summary':TEXT,'result_view':obj({'kind':ID,'resource_id':ID})}),
        obj({**common,'status':{'const':'accepted'},'job_id':ID}),
        obj({**common,'status':{'const':'failed'},'error':ref('error')}),
        obj({**common,'status':{'const':'unknown'},'reconcile':obj({'tool_name':{'const':'invocations.get'},'invocation_id':ID})})]})
    gap = obj({'type':{'const':'gap'},'min':INT,'max':INT})
    literal = obj({'type':{'const':'literal'},'value':TEXT})
    term = obj({'type':{'const':'term'},'attr':{'type':'string','pattern':'^[A-Za-z_][A-Za-z0-9_]*$'},'op':{'enum':['eq','regex']},'value':{**TEXT,'maxLength':1024}})
    query_variants = []
    for unit, atom in [('character',literal),('token',term)]:
        sequence = obj({'type':{'const':'sequence'},'items':arr({'oneOf':[atom,gap]},2)})
        positive = {'oneOf':[atom,sequence]}
        pattern = {'oneOf':[atom,sequence,obj({'type':{'const':'any_of'},'patterns':arr(positive,2)})]}
        query_variants.append(obj({'dsl_version':{'const':'corpus-query/v1'},'unit':{'const':unit},
            'pattern':pattern,'within':{'enum':['sentence','paragraph']},'overlap':{'const':'all'},
            'normalization':{'const':'none'},
            'filters':{'type':'object','additionalProperties':arr({'type':['string','number','boolean']},1)},
            'sort':{'const':['document_ordinal','start','end']},
            'condition':obj({'operator':{'enum':['and','not']},'pattern':positive,'within':{'enum':['sentence','paragraph']}})},
            ['dsl_version','unit','pattern','within','overlap']))
    save('corpus-query', {'oneOf':query_variants,
        '$comment':'Semantic validation must reject leading/trailing/consecutive gaps and min > max. Runtime must verify attribute availability and the accepted regex subset before execution; regex syntax is not executable permission.'})
    save('query-request', obj({'snapshot_id':ID,'query':ref('corpus-query'),'context_tokens':INT},['snapshot_id','query','context_tokens']))
    # First typed continuation step; additional steps remain unavailable until their input contracts are frozen.
    save('continuation-intent', obj({'continuation_id':ID,'source_run_id':ID,'target_scope':ref('scope'),
        'authorization_ref':ID,'steps':arr(obj({'capability_id':{'const':'corpus.search'},'parameters':ref('query-request')}),1)}))
    states = {'agent_run':['QUEUED','RUNNING','WAITING_JOB','WAITING_REVIEW','CANCEL_REQUESTED','CANCELLED','SUCCEEDED','FAILED'],
        'job':['QUEUED','RUNNING','CANCEL_REQUESTED','CANCELLED','SUCCEEDED','FAILED'],
        'tool_result':['succeeded','accepted','failed','unknown']}
    (ROOT/'states-errors.json').write_text(json.dumps({'states':states,'errors':[{'code':c,'http_status':s} for c,s in ERRORS.items()]},indent=2)+'\n',encoding='utf-8')
    entity_defs = {
      'source_release':obj({'release_id':ID,'source_id':ID,'manifest_ref':ID,'checksum':ID,'license_ref':ID,'immutable':{'const':True}}),
      'material_revision':obj({'revision_id':ID,'origin':{'oneOf':[obj({'kind':{'const':'source'},'release_id':ID,'upstream_id':ID}),obj({'kind':{'const':'private'},'project_id':ID,'upload_id':ID})]},'canonical_text_ref':ID,'token_layer_ref':{'type':['string','null']}}),
      'snapshot':obj({'snapshot_id':ID,'project_id':ID,'members':arr(obj({'material_revision_id':ID,'mount_id':{'type':['string','null']},'ordinal':INT})),'recipe_ref':ID,'metadata_manifest_ref':ID,'immutable':{'const':True}}),
      'evidence':{'oneOf':[
          obj({'evidence_id':ID,'project_id':ID,'kind':{'const':'text'},'snapshot_id':ID,'material_revision_id':ID,'start':INT,'end':INT,'coordinate_unit':{'const':'unicode_codepoint'},'interval':{'const':'half_open'}}),
          obj({'evidence_id':ID,'project_id':ID,'kind':{'const':'result'},'run_id':ID,'result_ref':ID,'row_id':ID})]},
      'session':obj({'session_id':ID,'owner_id':ID,'input_scope':ref('scope'),'scope_digest':ID,'active_run_id':{'type':['string','null']},'lease_epoch':INT,'context_archive_ref':{'type':['string','null']},'pi_version':ID}),
      'run':obj({'run_id':ID,'session_id':ID,'actor_id':ID,'input_scope':ref('scope'),'scope_digest':ID,'state':{'enum':states['agent_run']},'attempt':INT,'lease_epoch':INT,'next_session_id':{'type':['string','null']}}),
      'invocation':obj({'invocation_id':ID,'run_id':ID,'tool_name':{'enum':[e['tool_name'] for e in entries]},'schema_version':{'const':'v1'},'args_hash':ID,'scope_digest':ID,'action_id':{'type':['string','null']},'result':{'oneOf':[{'type':'null'},ref('tool-result')]}}),
      'action':ref('s1-action'),
      'job':ref('s1-job'),
    }
    save('entities', {'$defs':entity_defs,'oneOf':[{'$ref':'#/$defs/'+name} for name in entity_defs]})
    save('event',obj({'event_id':ID,'sequence':{'type':'integer','minimum':1},'run_id':ID,'kind':{'enum':['state_changed','tool_completed','job_linked','text_delta','completed']},'payload_ref':ID}))
    build_s1(save, obj)
    build_s2(save, obj)
    build_s3(save, obj)
    build_releases(save, obj)
    build_research(save, obj)
    build_materials(save, obj)
    build_outcomes(save, obj)
    from contracts.agent import build_agent
    build_agent(save)
    save('capability-registry',obj({'schema_version':{'const':'v1'},'capabilities':arr(obj({
        'capability_id':ID,'feature_ids':arr({'type':'string','pattern':'^F[0-9]{3}$'},1),'module_id':{'type':'string','pattern':'^M(0[1-9]|1[0-4])$'},
        'tool_name':ID,'schema_version':{'const':'v1'},'availability':obj({'status':{'enum':['planned','available']},'stage':{'type':'string','pattern':'^S[0-8]$'},'reason':TEXT}),
        'handler':ID,'operation_kind':{'enum':['read','write','task']},'input_schema':ID,'output_schema':ID,'permission':ID,
        'scope_kind':{**arr({'enum':['account','platform','project']},1),'uniqueItems':True},'version_inputs':refs,
        'scope_effect':{'enum':['none','produces_scope']},'authorization_policy':{'enum':['existing_authorization','explicit_user_confirmation','destructive_target_authorization']},
        'execution':{'enum':['job','synchronous']},'idempotency':obj({'invocation_id':{'const':'host_assigned'},'action_id':{'enum':['required','not_applicable']}}),
        'result_view':obj({'kind':ID,'reference_field':{'const':'result_ref'}}),'common_errors':arr({'enum':list(ERRORS)},1)}),1)}))


if __name__ == '__main__':
    build()
