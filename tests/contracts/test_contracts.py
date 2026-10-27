import copy
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from contracts.semantics import (scope_digest, validate_query_semantics, validate_snapshot_members,
    validate_tool_result_semantics, validate_continuation_semantics)


def read(name):
    return json.loads((ROOT / 'contracts' / name).read_text(encoding='utf-8'))


class ContractSemanticsTests(unittest.TestCase):
    def test_invocation_action_and_unknown_reconciliation(self):
        result = {'invocation_id':'i1','action_id':'a1','status':'unknown',
                  'reconcile':{'tool_name':'invocations.get','invocation_id':'i1'}}
        validate_tool_result_semantics(result,'i1','a1','write')
        for value,invocation,action,kind in [
            ({**result,'action_id':None},'i1',None,'write'),
            (result,'i1','a1','read'),(result,'i2','a1','write'),
            ({**result,'reconcile':{'invocation_id':'i2'}},'i1','a1','write')]:
            with self.assertRaises(ValueError): validate_tool_result_semantics(value,invocation,action,kind)

    def test_continuation_does_not_execute_planned_or_wrong_scope(self):
        action = {'capability_id':'corpus.search','availability':{'status':'planned'},'scope_kind':['project']}
        intent = {'target_scope':{'scope_kind':'project','snapshot_ids':['s1']},
                  'steps':[{'capability_id':'corpus.search','parameters':{'snapshot_id':'s1'}}]}
        with self.assertRaisesRegex(ValueError,'CAPABILITY_UNAVAILABLE'):
            validate_continuation_semantics(intent,[action])
        action['availability']['status'] = 'available'
        validate_continuation_semantics(intent,[action])
        intent['steps'][0]['parameters']['snapshot_id'] = 's2'
        with self.assertRaisesRegex(ValueError,'ENDPOINT_OUT_OF_SCOPE'):
            validate_continuation_semantics(intent,[action])

    def test_registry_covers_documented_actions(self):
        document = (ROOT / 'doc/assistant-capabilities.md').read_text(encoding='utf-8')
        expected = set()
        # Expand documented sources.list/get/versions, including nested tool families.
        for match in re.finditer(r'\b([a-z][A-Za-z]*(?:\.[A-Za-z]+)+)((?:/[A-Za-z]+)*)', document):
            tool, suffix = match.groups()
            if tool.startswith(('assistant.', 'schema.')) or tool.endswith(('.json', '.ts', '.py', '.md', '.docx', '.csv')):
                continue
            expected.add(tool)
            expected.update(tool.rsplit('.', 1)[0] + '.' + part for part in suffix.split('/') if part)
        registry = read('capabilities.json')['capabilities']
        self.assertEqual(read('status.json')['documented_action_inventory_count'],len(registry))
        actual = {entry['tool_name'] for entry in registry}
        self.assertFalse(expected - actual, f'Missing documented actions: {expected - actual}')
        self.assertEqual(len(registry), len(actual))
        self.assertEqual({entry['module_id'] for entry in registry}, {f'M{i:02}' for i in range(1,15)})
        for entry in registry:
            self.assertEqual(entry['availability']['status'], 'planned')
            for field in ('input_schema','output_schema'):
                self.assertTrue((ROOT/'contracts'/entry[field]).is_file())
            self.assertEqual(entry['idempotency']['action_id'], 'not_applicable' if entry['operation_kind'] == 'read' else 'required')

    def test_feature_ids_are_first_stage_features_and_specific_actions(self):
        product = (ROOT/'doc/product-design.md').read_text(encoding='utf-8')
        stages = {fid:stage for fid,stage in re.findall(r'^\| (F\d{3}) \|.*?\| (A(?:/[A-D])*|[BCD]) \|$',product,re.M)}
        entries = {e['tool_name']:e for e in read('capabilities.json')['capabilities']}
        for entry in entries.values():
            for fid in entry['feature_ids']:
                self.assertIn('A',stages[fid],(entry['tool_name'],fid))
        for tool,features,stage in [
            ('sources.list',['F012','F016'],'S1'),('uploads.create',['F009','F010'],'S1'),
            ('imports.start',['F009','F010'],'S3'),('parallel.search',['F031','F052'],'S3'),
            ('analysis.keywords',['F036','F037'],'S5'),('analysis.ngrams',['F035'],'S5')]:
            self.assertEqual(entries[tool]['feature_ids'],features)
            self.assertEqual(entries[tool]['availability']['stage'],stage)

    def test_scope_digest_excludes_derived_results_but_binds_identity(self):
        scope = {'scope_kind':'project','project_id':'p1','snapshot_ids':['s1'],
                 'material_revision_ids':[],'alignment_overlay_revision':None}
        baseline = scope_digest(scope)
        self.assertEqual(baseline, scope_digest({**scope,'result_refs':['new-result']}))
        for field, value in [('project_id','p2'),('snapshot_ids',['s2']),
                             ('material_revision_ids',['r1']),('alignment_overlay_revision',{'layer_id':'l1','revision':1})]:
            self.assertNotEqual(baseline, scope_digest({**scope,field:value}))

    def test_gap_semantics(self):
        a = {'type':'literal','value':'把'}
        b = {'type':'literal','value':'给'}
        for items in ([{'type':'gap','min':0,'max':8}, a], [a, {'type':'gap','min':0,'max':8}],
                      [a, {'type':'gap','min':8,'max':0}, b],
                      [a, {'type':'gap','min':0,'max':1}, {'type':'gap','min':0,'max':1}, b]):
            with self.assertRaises(ValueError):
                validate_query_semantics({'pattern':{'type':'sequence','items':items}})
        validate_query_semantics({'pattern':{'type':'sequence','items':[a,{'type':'gap','min':0,'max':8},b]}})

    def test_mixed_snapshot_bridge_and_project_isolation(self):
        revisions = {'shared':{'origin':{'kind':'source','release_id':'release'}},
                     'private':{'origin':{'kind':'private','project_id':'p1'}}}
        mounts = {'m1':{'project_id':'p1','release_id':'release'}}
        snapshot = {'project_id':'p1','members':[{'material_revision_id':'shared','mount_id':'m1','ordinal':0},
                                                {'material_revision_id':'private','mount_id':None,'ordinal':1}]}
        validate_snapshot_members(snapshot,revisions,mounts)
        for mutate in ('duplicate','private_project','mount_release'):
            s,r,m = copy.deepcopy((snapshot,revisions,mounts))
            if mutate == 'duplicate': s['members'][1]['material_revision_id'] = 'shared'
            if mutate == 'private_project': r['private']['origin']['project_id'] = 'p2'
            if mutate == 'mount_release': m['m1']['release_id'] = 'wrong'
            with self.assertRaises(ValueError): validate_snapshot_members(s,r,m)


try:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
except ImportError:
    Draft202012Validator = None


@unittest.skipIf(Draft202012Validator is None, 'Install jsonschema==4.26.0 for structural schema tests')
class JsonSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = {path.stem.removesuffix('.schema'):json.loads(path.read_text(encoding='utf-8'))
                       for path in (ROOT/'contracts/schemas').glob('*.json')}
        resources = []
        for name,schema in cls.schemas.items():
            if isinstance(schema,dict):
                resources.append((schema['$id'],Resource.from_contents(schema)))
        cls.registry = Registry().with_resources(resources)

    def validator(self,name):
        return Draft202012Validator(self.schemas[name],registry=self.registry)

    def assert_valid(self,name,value):
        self.validator(name).validate(value)

    def assert_invalid(self,name,value):
        self.assertFalse(self.validator(name).is_valid(value), value)

    def test_all_schemas_are_valid(self):
        for schema in self.schemas.values():
            Draft202012Validator.check_schema(schema)
        self.assert_valid('capability-registry', read('capabilities.json'))

    def test_scope_isolation_and_authority_fields(self):
        for scope in ('account','platform'):
            self.assert_valid('scope',{'scope_kind':scope})
            self.assert_invalid('scope',{'scope_kind':scope,'project_id':'p1'})
        self.assert_invalid('scope',{'scope_kind':'project'})
        self.assert_invalid('scope',{'scope_kind':'account','actor_id':'other'})
        self.assert_invalid('scope',{'scope_kind':'account','result_refs':['private']})

    def test_four_result_states_are_disjoint_and_required(self):
        common = {'invocation_id':'i1','action_id':None,'scope_ref':{'scope_kind':'account'},
                  'scope_effect':{'kind':'none'},'version_refs':[]}
        cases = [
            {'status':'succeeded','result_ref':'r1','evidence_refs':[],'method_summary':'fixture',
             'result_view':{'kind':'fixture','resource_id':'r1'}},
            {'status':'accepted','job_id':'j1'},
            {'status':'failed','error':{'code':'CAPABILITY_UNAVAILABLE','message':'Not implemented',
                'request_id':'req1','field_errors':[],'retryable':False}},
            {'status':'unknown','reconcile':{'tool_name':'invocations.get','invocation_id':'i1'}},
        ]
        for case in cases:
            self.assert_valid('tool-result',{**common,**case})
            self.assert_invalid('tool-result',{**common,**case,'actor_id':'other'})
            key = next(k for k in case if k != 'status')
            self.assert_invalid('tool-result',{**common,**{k:v for k,v in case.items() if k != key}})
        self.assert_invalid('tool-result',{**common,'status':'accepted','job_id':'j1','result_ref':'r1'})

    def test_query_ast_examples_and_boolean_anchors(self):
        for unit, atom in [('character',{'type':'literal','value':'汉字'}),
                           ('token',{'type':'term','attr':'form','op':'eq','value':'language'})]:
            query = {'dsl_version':'corpus-query/v1','unit':unit,'pattern':atom,'within':'sentence','overlap':'all'}
            self.assert_valid('corpus-query',query)
            self.assert_valid('corpus-query',{**query,'pattern':{'type':'sequence','items':[atom,{'type':'gap','min':0,'max':8},atom]}})
            for operator in ('and','not'):
                self.assert_valid('corpus-query',{**query,'condition':{'operator':operator,'pattern':atom,'within':'paragraph'}})
                self.assert_invalid('corpus-query',{**query,'condition':{'operator':operator,'pattern':{'type':'any_of','patterns':[atom,atom]},'within':'sentence'}})
            self.assert_valid('corpus-query',{**query,'pattern':{'type':'any_of','patterns':[atom,atom]}})
            self.assert_invalid('corpus-query',{**query,'pattern':{'type':'not','pattern':atom}})
            self.assert_invalid('corpus-query',{**query,'unit':'token' if unit == 'character' else 'character'})
            self.assert_invalid('corpus-query',{**query,'cqp':'arbitrary command'})

    def test_continuation_rejects_history_and_freeform_steps(self):
        value = {'continuation_id':'c1','source_run_id':'r1','target_scope':{'scope_kind':'project','project_id':'p1',
                 'snapshot_ids':['s1'],'material_revision_ids':[],'alignment_overlay_revision':None},
                 'authorization_ref':'message:1','steps':[{'capability_id':'corpus.search','parameters':{
                   'snapshot_id':'s1','context_tokens':8,'query':{'dsl_version':'corpus-query/v1','unit':'character',
                    'pattern':{'type':'literal','value':'汉字'},'within':'sentence','overlap':'all'}}}]}
        self.assert_valid('continuation-intent',value)
        for key in ('messages','body','summary','reasoning','actor_id'):
            self.assert_invalid('continuation-intent',{**value,key:'old context'})
        bad = copy.deepcopy(value)
        bad['steps'][0]['parameters']['messages'] = ['old context']
        self.assert_invalid('continuation-intent',bad)

    def test_planned_inputs_never_validate(self):
        for value in ({},None,{'route':'/admin'},[]):
            self.assert_invalid('planned',value)


if __name__ == '__main__':
    unittest.main()
