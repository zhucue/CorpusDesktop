import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from pipelines.query.engine import PositionIndex, QueryError


def fixture():
    return json.loads((ROOT/'tests/golden/query-v1.json').read_text(encoding='utf-8'))


def query_for(case):
    return {'dsl_version':'corpus-query/v1','within':'sentence','overlap':'all',
            **{key:value for key,value in case.items() if key not in ('name','expected','segments')}}


class ExactQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = fixture()
        cls.index = PositionIndex(cls.fixture['revisions'])

    def test_manual_golden_spans_and_complete_counts(self):
        for case in self.fixture['cases']:
            with self.subTest(case=case['name']):
                result = self.index.execute(query_for(case),page_size=100)
                self.assertEqual([[h['revision_id'],h['start'],h['end']] for h in result['hits']],case['expected'])
                self.assertEqual(result['total_hits'],len(case['expected']))
                self.assertEqual(result['matched_segments'],case['segments'])
                self.assertEqual(result['matched_documents'],len({h[0] for h in case['expected']}))
                self.assertTrue(result['complete'])

    def test_pagination_does_not_change_counts(self):
        query = query_for(self.fixture['cases'][5])
        result = self.index.execute(query,page_size=1)
        self.assertEqual(len(result['hits']),1)
        self.assertEqual(result['total_hits'],6)
        self.assertEqual(result['matched_segments'],2)

    def test_unsupported_queries_are_errors_not_empty_success(self):
        query = query_for(self.fixture['cases'][14])
        for pattern,code in [
            ({'type':'term','attr':'pos','op':'eq','value':'NOUN'},'ATTRIBUTE_UNAVAILABLE'),
            ({'type':'term','attr':'form','op':'regex','value':'.*'},'QUERY_UNSUPPORTED'),
            ({'type':'not','pattern':{'type':'term','attr':'form','op':'eq','value':'A'}},'QUERY_UNSUPPORTED'),
            ({'type':'literal','value':'A'},'QUERY_UNSUPPORTED')]:
            with self.assertRaisesRegex(QueryError,code): self.index.execute({**query,'pattern':pattern})

    def test_private_and_shared_revision_identity_cannot_double_count(self):
        revisions = copy.deepcopy(self.fixture['revisions'])
        revisions.append(revisions[0])
        with self.assertRaisesRegex(ValueError,'Duplicate actual revision'): PositionIndex(revisions)

    def test_invalid_ast_maps_to_query_error(self):
        query = query_for(self.fixture['cases'][0])
        for malformed in ({key:value for key,value in query.items() if key != 'pattern'},
                          {**query,'unknown':True},{**query,'unit':'token'}):
            with self.assertRaisesRegex(QueryError,'QUERY_UNSUPPORTED'): self.index.execute(malformed)

    def test_attribute_capability_applies_to_selected_materials(self):
        revisions = copy.deepcopy(self.fixture['revisions'])
        for token in revisions[1]['tokens']: token['attrs']['pos'] = 'N'
        revisions[1]['metadata']['source'] = 'ud'
        index = PositionIndex(revisions)
        query = {'dsl_version':'corpus-query/v1','unit':'token','within':'sentence','overlap':'all',
                 'pattern':{'type':'term','attr':'pos','op':'eq','value':'N'},'filters':{'source':['ud']}}
        self.assertEqual(index.execute(query)['total_hits'],6)
        query.pop('filters')
        with self.assertRaisesRegex(QueryError,'ATTRIBUTE_UNAVAILABLE'): index.execute(query)

    def test_empty_corpus_returns_complete_zero_for_form(self):
        result = PositionIndex([]).execute(query_for(self.fixture['cases'][14]))
        self.assertEqual(result['total_hits'],0)
        self.assertEqual(result['hits'],[])
        self.assertTrue(result['complete'])

    def test_heterogeneous_multisentence_counts_against_raw_enumeration(self):
        # Independent oracle: enumerate substrings, then scan segment membership.
        # Includes Unicode, uncovered separators, partial sentence coverage, and
        # a paragraph hit intersecting multiple sentences.
        revisions = [
            {'revision_id':'mixed','text':'甲😀乙。甲乙！尾','sentences':[[0,4],[4,7],[7,8]],'paragraphs':[[0,8]],'tokens':[],'metadata':{}},
            {'revision_id':'gaps','text':'乙 甲\n😀甲乙。','sentences':[[0,3],[4,8]],'paragraphs':[[0,8]],'tokens':[],'metadata':{}},
            {'revision_id':'whole','text':'甲乙甲','sentences':[[0,3]],'paragraphs':[[0,3]],'tokens':[],'metadata':{}},
            {'revision_id':'partial','text':'外甲乙外','sentences':[[1,3]],'paragraphs':[[1,3]],'tokens':[],'metadata':{}},
        ]
        index = PositionIndex(revisions)
        for within in ('sentence','paragraph'):
            for mode in ('literal','gap','or','and','not'):
                pattern = {'type':'literal','value':'甲'}
                if mode == 'gap':
                    pattern = {'type':'sequence','items':[pattern,{'type':'gap','min':0,'max':4},{'type':'literal','value':'乙'}]}
                if mode == 'or':
                    pattern = {'type':'any_of','patterns':[pattern,{'type':'literal','value':'甲乙'}]}
                query = {'dsl_version':'corpus-query/v1','unit':'character','within':within,'overlap':'all','pattern':pattern}
                if mode in ('and','not'):
                    query['condition'] = {'operator':mode,'within':'sentence','pattern':{'type':'literal','value':'😀'}}
                expected, touched, docs = [],set(),set()
                for ordinal,r in enumerate(revisions):
                    for start in range(len(r['text'])):
                        for end in range(start+1,len(r['text'])+1):
                            text = r['text'][start:end]
                            matches = (text[0] == '甲' and text[-1] == '乙' and 2 <= len(text) <= 6) if mode == 'gap' else text in (('甲','甲乙') if mode == 'or' else ('甲',))
                            if not matches or not any(left <= start and end <= right for left,right in r[within+'s']): continue
                            if mode in ('and','not'):
                                containing = [r['text'][left:right] for left,right in r['sentences'] if left <= start and end <= right]
                                if not containing or (('😀' in containing[0]) != (mode == 'and')): continue
                            expected.append({'revision_id':r['revision_id'],'document_ordinal':ordinal,'start':start,'end':end})
                            docs.add(ordinal)
                            touched.update((ordinal,i) for i,(left,right) in enumerate(r['sentences']) if left < end and start < right)
                for page_size in (0,1,3,100):
                    with self.subTest(within=within,mode=mode,page_size=page_size):
                        result = index.execute(query,page_size=page_size)
                        self.assertEqual(result['hits'],expected[:page_size])
                        self.assertEqual(result['total_hits'],len(expected))
                        self.assertEqual(result['matched_segments'],len(touched))
                        self.assertEqual(result['matched_documents'],len(docs))


if __name__ == '__main__': unittest.main()
