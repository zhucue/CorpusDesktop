"""Independent small gold plus persisted-index restart and actual CWB checks."""
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pipelines.query.source_index import IndexBuildError, build
from pipelines.query.source_recipe import encoded
from pipelines.sources.tatoeba import RECIPE as SOURCE_RECIPE

ROOT = Path(__file__).resolve().parents[2]
HAS_ENGINE = bool(shutil.which("cwb-encode") and importlib.util.find_spec("jieba") and importlib.util.find_spec("nltk"))


def fixture(path, *, corrupt=False):
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
      CREATE TABLE sentences(id INTEGER PRIMARY KEY,language TEXT,text TEXT,owner TEXT,added TEXT,modified TEXT,record_hash TEXT,text_hash TEXT,source_line INTEGER);
      CREATE TABLE edges(cmn_id INTEGER,eng_id INTEGER,PRIMARY KEY(cmn_id,eng_id));""")
    db.execute("INSERT INTO metadata VALUES('recipe',?)", (SOURCE_RECIPE,))
    for sid, lang, text in [(1,"cmn","我爱北京。哈哈哈😀"),(2,"eng","I can't go. A A A."),(3,"eng","end"),(4,"eng","startendstart"),(5,"eng","<x> &amp; e\u0301 😀"),(6,"eng","🙂"),(7,"eng","🙂🙂")]:
        values = (sid,lang,text,'tester',None,None)
        db.execute("INSERT INTO sentences VALUES(?,?,?,?,?,?,?,?,?)", (*values,hashlib.sha256(encoded(values)).hexdigest(),hashlib.sha256(text.encode()).hexdigest() if not corrupt else '0'*64,sid))
    db.execute("INSERT INTO edges VALUES(1,2)")
    db.commit()
    db.close()


def query(unit, pattern):
    return {"dsl_version":"corpus-query/v1","unit":unit,"within":"sentence","pattern":pattern,"normalization":"none","overlap":"all"}


class MonotoneSeekTests(unittest.TestCase):
    def test_local_far_duplicate_and_end_seeks(self):
        from bisect import bisect_left, bisect_right

        from pipelines.query.source_reader import _monotone_bisect
        values = [0, 1, 1, 3, 8, 100, 1000, 10000]
        for value, lower in [(-1,0),(0,0),(1,0),(1,2),(7,3),(1000,1),(20000,6),(20000,8)]:
            for right in (False, True):
                with self.subTest(value=value,lower=lower,right=right):
                    expected = lower + sum(x <= value if right else x < value for x in values[lower:])
                    self.assertEqual(_monotone_bisect(values,value,lower,right=right),expected)
        for values, value, lower in [([],0,0),([0]*128+[100]*256+[1_000_000],100,128),
                                     ([0]*128+[100]*256+[1_000_000],100,257),
                                     ([1,1_000_000,2_000_000],2_000_000,1)]:
            for right in (False, True):
                expected = (bisect_right if right else bisect_left)(values,value,lower)
                self.assertEqual(_monotone_bisect(values,value,lower,right=right),expected)


@unittest.skipUnless(HAS_ENGINE, "Isolated pinned tokenizers and Linux CWB required")
class SourceIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT/'tmp', prefix='index-test-')
        cls.root = Path(cls.temp.name)
        cls.source = cls.root/'source.sqlite3'
        fixture(cls.source)
        cls.result = build(cls.source,cls.root/'built','a'*64,lambda _:None)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def reader(self, name):
        from pipelines.query.source_reader import SourceIndexReader
        return SourceIndexReader(self.root/'built/bundle',self.root/name)

    def test_independent_tokenization_gold(self):
        from pipelines.query.source_recipe import SurfaceTokenizer
        tokenizer = SurfaceTokenizer(self.root/'built/temporary')
        self.assertEqual(tokenizer.spans('我爱北京。', 'cmn'),[(0,1,'我'),(1,2,'爱'),(2,4,'北京'),(4,5,'。')])
        self.assertEqual(tokenizer.spans("I can't go.", 'eng'),[(0,1,'I'),(2,4,'ca'),(4,7,"n't"),(8,10,'go'),(10,11,'.')])
        self.assertEqual(tokenizer.spans('e\u0301 😀','eng'),[(0,2,'e\u0301'),(3,4,'😀')])

    def test_character_overlap_unicode_sentence_boundary(self):
        with self.reader('char-runtime') as reader:
            for value, expected in [('哈哈',[(1,5,7),(1,6,8)]),('😀',[(1,8,9),(5,13,14)]),('e\u0301',[(5,10,12)]),('é',[]),('endstart',[(4,5,13)]),('absent',[])]:
                result=reader.character_query(query('character',{'type':'literal','value':value}))
                self.assertEqual([(h['source_sentence_id'],h['start'],h['end']) for h in result['page']],expected)
                self.assertEqual(result['total_hits'],len(expected))

    def test_native_literal_cross_sentence_rejection_then_valid_match(self):
        with self.reader('native-runtime') as reader:
            for value, expected in [('endstart',[(4,5,13)]),('🙂🙂',[(7,0,2)]),('start<',[]),('\ud800',[])]:
                with self.subTest(value=repr(value)):
                    result=reader.character_query(query('character',{'type':'literal','value':value}))
                    self.assertEqual([(h['source_sentence_id'],h['start'],h['end']) for h in result['page']],expected)
                    self.assertEqual(result['total_hits'],len(expected))

    def test_character_candidate_selection_preserves_composite_spans(self):
        def literal(value):
            return {'type':'literal','value':value}
        cases = [
            (literal('北京'), [(1,2,4)]),
            (literal('哈哈'), [(1,5,7),(1,6,8)]),
            ({'type':'any_of','patterns':[literal('missing'),literal('哈哈')]}, [(1,5,7),(1,6,8)]),
            ({'type':'sequence','items':[literal('我'),{'type':'gap','min':0,'max':3},literal('北京')]}, [(1,0,4)]),
            ({'type':'sequence','items':[literal('A'),{'type':'gap','min':1,'max':3},literal('A')]}, [(2,12,15),(2,12,17),(2,14,17)]),
        ]
        with self.reader('candidate-runtime') as reader:
            for pattern, expected in cases:
                with self.subTest(pattern=pattern):
                    result = reader.character_query(query('character',pattern))
                    self.assertEqual([(h['source_sentence_id'],h['start'],h['end']) for h in result['page']],expected)
                    self.assertEqual(result['total_hits'],len(expected))
                    self.assertEqual(reader.character_page(query('character',pattern),offset=1,limit=1)['page'],result['page'][1:2])

    def test_cwb_counts_kwic_and_missing_attribute(self):
        with self.reader('token-runtime') as reader:
            q=query('token',{'type':'term','attr':'form','op':'eq','value':'A'})
            self.assertEqual(reader.token_counts(q)['total_hits'],3)
            page=reader.token_page(q)
            self.assertIsNone(page['total_hits'])
            self.assertEqual([(h['start'],h['end']) for h in page['page']],[(12,13),(14,15),(16,17)])
            # CWB implicit NFC must not merge canonically equivalent original forms.
            for form, expected in [('e\u0301',1),('é',0)]:
                exact=query('token',{'type':'term','attr':'form','op':'eq','value':form})
                self.assertEqual(reader.token_counts(exact)['total_hits'],expected)
                self.assertEqual(exact['pattern']['value'],form)
                rows=reader.token_page(exact)['page']
                self.assertEqual([(h['start'],h['end']) for h in rows],[(10,12)] if expected else [])
            q['pattern']['attr']='lemma'
            with self.assertRaisesRegex(ValueError,'ATTRIBUTE_UNAVAILABLE'):
                reader.token_counts(q)

    def test_fresh_process_reopens_saved_bytes(self):
        code='''import json,sys
from pipelines.query.source_reader import SourceIndexReader
from tests.query.test_source_index import query
with SourceIndexReader(sys.argv[1],sys.argv[2]) as r:
 print(json.dumps(r.character_query(query("character",{"type":"literal","value":"哈哈"}))))
'''
        result=subprocess.run([sys.executable,'-c',code,str(self.root/'built/bundle'),str(self.root/'fresh-runtime')],capture_output=True,text=True,check=True,timeout=30)
        self.assertEqual(json.loads(result.stdout)['total_hits'],2)

    def test_corrupt_input_not_indexed(self):
        source=self.root/'corrupt.sqlite3'
        fixture(source,corrupt=True)
        with self.assertRaisesRegex(IndexBuildError,'INPUT_HASH_MISMATCH'):
            build(source,self.root/'corrupt','b'*64,lambda _:None)
        self.assertFalse((self.root/'corrupt/manifest.json').exists())

    def test_callback_cancel_propagates(self):
        def cancel(event):
            if event['stage']=='TOKENIZING':
                raise RuntimeError('fenced')
        with self.assertRaisesRegex(RuntimeError,'fenced'):
            build(self.source,self.root/'cancel','b'*64,cancel)
        self.assertFalse((self.root/'cancel/manifest.json').exists())

    def test_small_quota_rejects_before_success(self):
        with self.assertRaisesRegex(IndexBuildError,'QUOTA_EXCEEDED'):
            build(self.source,self.root/'quota','b'*64,lambda _:None,max_temporary_bytes=1)
        self.assertFalse((self.root/'quota/manifest.json').exists())

    def test_payload_corruption_rejected(self):
        from pipelines.query.source_reader import SourceIndexReader
        damaged=self.root/'damaged'
        shutil.copytree(self.root/'built/bundle',damaged)
        with (damaged/'characters.bin').open('r+b') as stream:
            stream.write(b'\xff'*8)
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):
            SourceIndexReader(damaged,self.root/'damaged-runtime')
