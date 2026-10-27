"""Real private/mixed CWB corpus, whole-document coordinates and counts."""
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pipelines.materials.txt import parse_txt
from pipelines.query.project_index import build_project
from pipelines.query.source_cache import open_cached, prepare_index
from pipelines.query.source_index import build
from pipelines.query.source_reader import SourceIndexReader
from pipelines.query.source_results import first_page, read_page, write_spans
from tests.query.test_source_index import HAS_ENGINE, ROOT, fixture, query


@unittest.skipUnless(HAS_ENGINE and os.name=='posix','Linux CWB/tokenizers required')
class ProjectIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp',prefix='project-index-test-');cls.root=Path(cls.temp.name)
        cls.text='\r\nDr. Smith said Hello.\r\nHello e\u0301😀!\nLast Hello line.\n'
        raw=cls.root/'raw.txt';raw.write_bytes(b'\xef\xbb\xbf'+cls.text.encode())
        cls.doc=str(uuid4());cls.rev=str(uuid4())
        cls.private=parse_txt(raw,cls.root/'parsed',document_id=cls.doc,revision_id=cls.rev,language='eng',
                              expected_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),expected_bytes=raw.stat().st_size,
                              progress_callback=lambda _:None)
        cls.member={'kind':'private','directory':cls.root/'parsed','manifest_sha256':hashlib.sha256(cls.private['manifest_path'].read_bytes()).hexdigest()}
        cls.pure=build_project([cls.member,cls.member],cls.root/'pure','a'*64,lambda _:None)
        database=cls.root/'source.sqlite3';fixture(database)
        cls.source=build(database,cls.root/'source','b'*64,lambda _:None)
        inner=cls.root/'source/bundle/manifest.json'
        cls.source_member={'kind':'source','source_id':'TEST','directory':inner.parent,'manifest_sha256':hashlib.sha256(inner.read_bytes()).hexdigest(),'identity_sha256':cls.source['manifest']['identity_sha256']}
        cls.mixed=build_project([cls.member,cls.source_member,cls.member],cls.root/'mixed','c'*64,lambda _:None)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_private_file_is_one_document_with_full_revision_offsets(self):
        self.assertEqual(self.pure['counts']['documents'],1)
        self.assertEqual(self.pure['counts']['sentences'],3)
        self.assertEqual(self.pure['counts']['characters'],len(self.text))
        for unit in ['character','token']:
            pattern={'type':'literal','value':'Hello'} if unit=='character' else {'type':'term','attr':'form','op':'eq','value':'Hello'}
            with SourceIndexReader(self.root/'pure/bundle',self.root/('run-'+unit)) as reader:
                result=write_spans(reader,query(unit,pattern),self.root/(unit+'.spans'),lambda _:None)
                self.assertEqual(result['counts'],{'total_hits':3,'matched_segments':3,'matched_documents':1,'document_count_unit':'document','matched_source_documents':0,'matched_private_documents':1})
                hits=read_page(reader,result['path'],0,expected_sha256=result['sha256'],expected_records=3)['hits']
                expected=[];at=0
                while (at:=self.text.find('Hello',at))>=0:expected.append(at);at+=1
                self.assertEqual([h['start_cp'] for h in hits],expected)
                for h in hits:
                    self.assertEqual(h['revision_id'],self.rev);self.assertEqual(h['document_id'],self.doc)
                    self.assertIsNone(h['source_url']);self.assertIsNone(h['source_sentence_id'])
                    self.assertEqual(self.text[h['start_cp']:h['end_cp']],h['match'])
                    self.assertEqual(reader.text(h['sentence_ordinal'])[h['start_cp']-h['context_start_cp']:h['end_cp']-h['context_start_cp']],'Hello')
                    self.assertEqual(h['origin_kind'],'private')
                self.assertEqual(reader.character_counts(query('character',{'type':'literal','value':'Hello'}))['matched_documents'],1)

    def test_mixed_preserves_source_identity_and_document_units(self):
        self.assertEqual(self.mixed['counts']['documents'],self.source['counts']['sentences']+1)
        self.assertEqual(self.mixed['counts']['source_documents'],self.source['counts']['sentences'])
        self.assertEqual(self.mixed['counts']['private_documents'],1)
        with SourceIndexReader(self.root/'mixed/bundle',self.root/'mixed-runtime') as reader:
            q=query('character',{'type':'any_of','patterns':[{'type':'literal','value':'Hello'},{'type':'literal','value':'北京'}]})
            result=write_spans(reader,q,self.root/'mixed.spans',lambda _:None)
            self.assertEqual(result['counts']['matched_private_documents'],1)
            self.assertGreater(result['counts']['matched_source_documents'],0)
            self.assertEqual(result['counts']['matched_documents'],result['counts']['matched_source_documents']+1)
            self.assertEqual(first_page(reader,q)['hits'][0]['origin_kind'],'source')

    def test_cache_and_fresh_process_read_only_mapping(self):
        raw=self.pure['manifest_path'].read_bytes();package=self.root/'pure/index.tar'
        cache=self.root/'cache'
        prepared=prepare_index(cache,raw,hashlib.sha256(raw).hexdigest(),lambda:package.open('rb'),lambda _:None)
        with open_cached(cache,prepared['cache_key'],self.pure['manifest']['identity_sha256']) as reader:
            self.assertEqual(reader.metadata(1)['document_id'],self.doc)
            self.assertIsNone(reader.runtime)
        code='''import sys;from pipelines.query.source_reader import SourceIndexReader
with SourceIndexReader(sys.argv[1]) as r:
 assert r.metadata(2)['document_id']==sys.argv[2]
 assert r.text(2)=='Last Hello line.\\n'
 print('fresh process verified')'''
        process=subprocess.run([sys.executable,'-c',code,str(prepared['directory']),self.doc],capture_output=True,text=True,check=True,timeout=30)
        self.assertIn('verified',process.stdout)

    def test_reject_two_revisions_same_private_file_and_tampered_manifest(self):
        raw=self.root/'raw.txt';other=parse_txt(raw,self.root/'other',document_id=self.doc,revision_id=str(uuid4()),language='eng',expected_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),expected_bytes=raw.stat().st_size,progress_callback=lambda _:None)
        member={'kind':'private','directory':self.root/'other','manifest_sha256':hashlib.sha256(other['manifest_path'].read_bytes()).hexdigest()}
        with self.assertRaisesRegex(ValueError,'DOCUMENT_REVISION_CONFLICT'):
            build_project([self.member,member],self.root/'conflict','d'*64,lambda _:None)
        with self.assertRaisesRegex(ValueError,'INDEX_INPUT_HASH_MISMATCH'):
            build_project([{**self.member,'manifest_sha256':'0'*64}],self.root/'bad','e'*64,lambda _:None)

    def test_equal_text_different_documents_remain_distinct(self):
        raw=self.root/'raw.txt';new_doc=str(uuid4());new_rev=str(uuid4())
        other=parse_txt(raw,self.root/'equal-text',document_id=new_doc,revision_id=new_rev,language='eng',
                        expected_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),expected_bytes=raw.stat().st_size,progress_callback=lambda _:None)
        member={'kind':'private','directory':other['manifest_path'].parent,'manifest_sha256':hashlib.sha256(other['manifest_path'].read_bytes()).hexdigest()}
        built=build_project([self.member,member,self.member],self.root/'two-documents','f'*64,lambda _:None)
        self.assertEqual(built['counts']['documents'],2)
        self.assertEqual(built['counts']['sentences'],6)
        with SourceIndexReader(self.root/'two-documents/bundle') as reader:
            result=write_spans(reader,query('character',{'type':'literal','value':'Hello'}),self.root/'two-documents.spans',lambda _:None)
            self.assertEqual(result['counts']['total_hits'],6)
            self.assertEqual(result['counts']['matched_documents'],2)
            self.assertEqual(result['counts']['matched_segments'],6)
            hits=read_page(reader,result['path'],0,expected_sha256=result['sha256'],expected_records=6)['hits']
            self.assertEqual({h['material_id'] for h in hits},{self.doc,new_doc})

    def test_chinese_private_multisentence_exact_jieba_and_document_coordinates(self):
        text='“北京，北京。”\r\n北京😀！\n末句北京？'
        raw=self.root/'chinese.txt';raw.write_bytes(text.encode('utf-8'))
        parsed=parse_txt(raw,self.root/'chinese',document_id=str(uuid4()),revision_id=str(uuid4()),language='cmn',
                         expected_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),expected_bytes=raw.stat().st_size,progress_callback=lambda _:None)
        member={'kind':'private','directory':parsed['manifest_path'].parent,'manifest_sha256':hashlib.sha256(parsed['manifest_path'].read_bytes()).hexdigest()}
        built=build_project([member],self.root/'chinese-built','7'*64,lambda _:None)
        self.assertEqual(built['counts']['documents'],1)
        self.assertEqual(built['counts']['sentences'],3)
        with SourceIndexReader(self.root/'chinese-built/bundle',self.root/'chinese-runtime') as reader:
            self.assertEqual([reader.text(i) for i in range(3)],['“北京，北京。”\r\n','北京😀！\n','末句北京？'])
            expected=[];at=0
            while (at:=text.find('北京',at))>=0:expected.append(at);at+=1
            for unit in ['character','token']:
                pattern={'type':'literal','value':'北京'} if unit=='character' else {'type':'term','attr':'form','op':'eq','value':'北京'}
                result=write_spans(reader,query(unit,pattern),self.root/('chinese-'+unit+'.spans'),lambda _:None)
                self.assertEqual((result['counts']['total_hits'],result['counts']['matched_segments'],result['counts']['matched_documents']),(4,3,1))
                hits=read_page(reader,result['path'],0,expected_sha256=result['sha256'],expected_records=4)['hits']
                self.assertEqual([h['start_cp'] for h in hits],expected)
                for h in hits:self.assertEqual(text[h['start_cp']:h['end_cp']],'北京')
