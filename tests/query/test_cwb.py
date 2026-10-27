import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from pipelines.query.cwb import compile_token_pattern, cqp_spans
from pipelines.query.engine import QueryError


class CompilerTests(unittest.TestCase):
    def test_uses_literal_equality_and_rejects_control_input(self):
        atom = {'type':'term','attr':'form','op':'eq','value':'a.b'}
        self.assertEqual(compile_token_pattern(atom,{'form'}),'[word="a.b" %l]')
        for value in ('"; exit;', '\\x', 'x\ny', '<s>', 'a\x00b'):
            with self.assertRaises(QueryError): compile_token_pattern({**atom,'value':value},{'form'})


@unittest.skipUnless(shutil.which('cqp') and shutil.which('cwb-encode'), 'CWB 3.5 Linux container required')
class CwbIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = ROOT/'tmp/query-s0/cwb-integration'
        # Never reuse partially encoded data; all files stay under repository tmp/.
        import tempfile
        cls.work.mkdir(parents=True,exist_ok=True)
        cls.work = Path(tempfile.mkdtemp(prefix='run-',dir=cls.work))
        cls.registry = cls.work/'registry'
        data = cls.work/'data'
        data.mkdir(parents=True)
        cls.registry.mkdir()
        cls.fixture = json.loads((ROOT/'tests/golden/query-v1.json').read_text(encoding='utf-8'))
        lines = []
        cls.mapping = []
        for r in cls.fixture['revisions']:
            lines.append('<p>')
            for left,right in r['sentences']:
                lines.append('<s>')
                for token in r['tokens']:
                    if left <= token['start'] and token['end'] <= right:
                        lines.append(token['attrs']['form'])
                        cls.mapping.append((r['revision_id'],token['start'],token['end']))
                lines.append('</s>')
            lines.append('</p>')
        vrt = cls.work/'fixture.vrt'
        vrt.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        subprocess.run(['cwb-encode','-d',str(data),'-c','utf8','-f',str(vrt),'-R',str(cls.registry/'s0'),'-S','s','-S','p'],check=True,capture_output=True)
        subprocess.run(['cwb-makeall','-r',str(cls.registry),'-V','S0'],check=True,capture_output=True)

    def test_actual_cqp_matches_independent_token_gold(self):
        checked = 0
        for case in self.fixture['cases']:
            if case['unit'] != 'token' or 'condition' in case: continue
            query = {'dsl_version':'corpus-query/v1','within':'sentence','overlap':'all',
                     **{k:v for k,v in case.items() if k not in ('name','expected','segments')}}
            with self.subTest(case=case['name']):
                actual = sorted([self.mapping[start][0],self.mapping[start][1],self.mapping[end-1][2]]
                                for start,end in cqp_spans(query,self.registry))
                self.assertEqual(actual,case['expected'])
            checked += 1
        self.assertGreaterEqual(checked,5)


if __name__ == '__main__': unittest.main()
