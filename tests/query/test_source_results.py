"""Real tiny CWB, persisted exact spans and private cache failure boundaries."""
import hashlib
import io
import json
import os
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path

from pipelines.query.source_cache import open_cached, prepare_index
from pipelines.query.source_index import build
from pipelines.query.source_reader import SourceIndexReader
from pipelines.query.source_recipe import encoded
from pipelines.query.source_results import (
    SPAN,
    first_page,
    install_result,
    read_page,
    validate_query,
    write_spans,
)
from tests.query.test_source_index import HAS_ENGINE, ROOT, fixture, query


class QueryValidationTests(unittest.TestCase):
    def test_reject_unimplemented_semantics(self):
        for q in [query('token', {'type':'term','attr':'lemma','op':'eq','value':'go'}),
                  query('token', {'type':'term','attr':'form','op':'regex','value':'.*'}),
                  {**query('character', {'type':'literal','value':'a'}), 'within':'paragraph'}]:
            with self.subTest(q=q), self.assertRaisesRegex(ValueError, 'QUERY_UNSUPPORTED'):
                validate_query(q)


@unittest.skipUnless(HAS_ENGINE and os.name == 'posix', 'Linux CWB and isolated tokenizers required')
class SourceResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT/'tmp', prefix='result-test-')
        cls.root = Path(cls.temp.name)
        database = cls.root/'input.sqlite3'
        fixture(database)
        with sqlite3.connect(database) as db:
            for sid in range(8, 71):
                row = (sid, 'eng', 'A A.', 'tester', None, None)
                db.execute('INSERT INTO sentences VALUES(?,?,?,?,?,?,?,?,?)',
                           (*row, hashlib.sha256(encoded(row)).hexdigest(), hashlib.sha256(b'A A.').hexdigest(), sid))
        cls.built = build(database, cls.root/'built', 'a'*64, lambda _: None)
        cls.manifest_bytes = cls.built['manifest_path'].read_bytes()
        cls.manifest_sha = hashlib.sha256(cls.manifest_bytes).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def reader(self, name):
        return SourceIndexReader(self.root/'built/bundle', self.root/name)

    def test_real_page_full_file_context_and_zero(self):
        for unit, pattern in [('character', {'type':'literal','value':'A'}),
                              ('token', {'type':'term','attr':'form','op':'eq','value':'A'})]:
            q = query(unit, pattern)
            with self.reader('runtime-'+unit) as reader:
                first = first_page(reader, q)
                self.assertEqual(len(first['hits']), 50)
                self.assertTrue(first['has_more'])
                result = write_spans(reader, q, self.root/(unit+'.spans'), lambda _:None)
                self.assertEqual(result['record_count'], 129)
                self.assertEqual(result['bytes'], 129*32)
                self.assertEqual(result['counts']['matched_documents'], 64)
                expected = [(2,12,13),(2,14,15),(2,16,17)] + [(sid,a,a+1) for sid in range(8,71) for a in [0,2]]
                pages = []
                for offset in [0,50,100,150]:
                    page = read_page(reader, result['path'], offset, expected_sha256=result['sha256'], expected_records=129)
                    pages.extend(page['hits'])
                    self.assertEqual(page['has_more'], offset+len(page['hits'])<129)
                self.assertEqual([(h['source_sentence_id'],h['start_cp'],h['end_cp']) for h in pages], expected)
                self.assertEqual([h['result_ordinal'] for h in pages], list(range(129)))
                self.assertEqual(first['hits'], pages[:50])
                no_context = read_page(reader, result['path'], 0, limit=1, context_codepoints=0,
                                       expected_sha256=result['sha256'], expected_records=129)['hits'][0]
                self.assertEqual((no_context['left'], no_context['right']), ('',''))
                if unit == 'token':
                    # Treebank keeps the interior "go." as one surface token;
                    # the prefix is I / ca / n't / go. before the first A.
                    self.assertEqual((pages[0]['token_start'],pages[0]['token_end']), (4,5))
                    self.assertEqual(pages[0]['global_token_end']-pages[0]['global_token_start'], 1)
                else:
                    self.assertIsNone(pages[0]['token_start'])
                empty = write_spans(reader, query('character', {'type':'literal','value':'not-in-fixture'}),
                                    self.root/(unit+'-zero.spans'), lambda _:None)
                self.assertEqual(empty['counts']['total_hits'], 0)
                self.assertEqual(read_page(reader, empty['path'], expected_sha256=empty['sha256'], expected_records=0), {'hits':[], 'has_more':False})

    def test_overlap_and_composite_streams(self):
        cases = [query('character', {'type':'literal','value':'哈哈'}),
                 query('character', {'type':'any_of','patterns':[{'type':'literal','value':'哈哈'},{'type':'literal','value':'不存在'}]}),
                 query('token', {'type':'sequence','items':[{'type':'term','attr':'form','op':'eq','value':'A'}, {'type':'gap','min':0,'max':1}, {'type':'term','attr':'form','op':'eq','value':'A'}]})]
        with self.reader('runtime-composite') as reader:
            for i,q in enumerate(cases):
                result = write_spans(reader,q,self.root/f'composite-{i}',lambda _:None)
                page=read_page(reader,result['path'],expected_sha256=result['sha256'],expected_records=result['record_count'])
                spans=[(h['source_sentence_id'],h['start_cp'],h['end_cp']) for h in page['hits']]
                self.assertEqual(spans[:3], [(1,5,7),(1,6,8)] if i<2 else [(2,12,15),(2,12,17),(2,14,17)])
                self.assertEqual(result['record_count'],2 if i<2 else 66)

    def test_quota_and_callback_never_mark_complete(self):
        with self.reader('runtime-quota') as reader:
            path=self.root/'overquota'
            with self.assertRaisesRegex(ValueError,'QUERY_RESULT_TOO_LARGE'):
                write_spans(reader,query('character',{'type':'literal','value':'A'}),path,lambda _:None,max_bytes=32)
            self.assertFalse(path.exists())
            def cancel(_):
                raise RuntimeError('fenced')
            with self.assertRaisesRegex(RuntimeError,'fenced'):
                write_spans(reader,query('token',{'type':'term','attr':'form','op':'eq','value':'A'}),self.root/'cancelled',cancel)
            self.assertFalse((self.root/'cancelled.ready.json').exists())
            self.assertEqual(list(reader.runtime.glob('query-*')), [])

    def test_single_sentence_intermediate_limit_before_cartesian_explosion(self):
        with self.reader('runtime-intermediate') as reader:
            q=query('character',{'type':'sequence','items':[{'type':'literal','value':'A'},
                    {'type':'gap','min':0,'max':100000},{'type':'literal','value':'A'}]})
            # Three literal positions fit; their three pairs exceed the low test cap
            # when combined with a fourth synthetic repeated position.
            original_text=reader.text
            reader.text=lambda ordinal: 'A'*200 if ordinal == 1 else original_text(ordinal)
            with self.assertRaisesRegex(ValueError,'QUERY_RESULT_TOO_LARGE'):
                list(reader._character_matches(q,max_sentence_spans=250))

    def test_restore_hash_and_ready_binding(self):
        data=SPAN.pack(0,5,7,2**64-1,2**64-1)
        sha=hashlib.sha256(data).hexdigest()
        path=self.root/'restored'
        install_result(io.BytesIO(data),len(data),sha,path,lambda _:None)
        with SourceIndexReader(self.root/'built/bundle') as reader:
            page=read_page(reader,path,expected_sha256=sha,expected_records=1)
            self.assertEqual(page['hits'][0]['match'],'哈哈')
            with self.assertRaisesRegex(ValueError,'RESULT_CACHE_INVALID'):
                read_page(reader,path,expected_sha256='0'*64,expected_records=1)
        with self.assertRaisesRegex(ValueError,'RESULT_HASH_MISMATCH'):
            install_result(io.BytesIO(data),len(data),'0'*64,self.root/'bad-result',lambda _:None)
        self.assertFalse((self.root/'bad-result.ready.json').exists())
        path.with_name(path.name+'.ready.json').write_text('{broken',encoding='utf-8')
        with SourceIndexReader(self.root/'built/bundle') as reader, self.assertRaisesRegex(ValueError,'RESULT_CACHE_INVALID'):
            read_page(reader,path,expected_sha256=sha,expected_records=1)
        install_result(io.BytesIO(data),len(data),sha,path,lambda _:None)
        self.assertEqual(path.read_bytes(),data)

    def test_cache_installs_once_and_opens_without_writes(self):
        root=self.root/'cache'
        opened=[]
        def download():
            opened.append(True)
            return (self.root/'built/index.tar').open('rb')
        first=prepare_index(root,self.manifest_bytes,self.manifest_sha,download,lambda _:None)
        again=prepare_index(root,self.manifest_bytes,self.manifest_sha,download,lambda _:None)
        self.assertTrue(first['created'])
        self.assertFalse(again['created'])
        self.assertEqual(len(opened),1)
        before={str(p):p.stat().st_mtime_ns for p in root.rglob('*')}
        with open_cached(root,first['cache_key'],self.built['manifest']['identity_sha256']) as reader:
            self.assertIsNone(reader.runtime)
            self.assertEqual(reader.text(0),'我爱北京。哈哈哈😀')
        self.assertEqual(before,{str(p):p.stat().st_mtime_ns for p in root.rglob('*')})
        (first['directory']/'.ready.json').write_text('{bad',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'INDEX_CACHE_INVALID'):
            open_cached(root,first['cache_key'],self.built['manifest']['identity_sha256'])
        restored=prepare_index(root,self.manifest_bytes,self.manifest_sha,download,lambda _:None)
        self.assertTrue(restored['created'])
        self.assertEqual(len(opened),2)

    def test_cache_rejects_quota_package_damage_and_tar_link(self):
        with self.assertRaisesRegex(ValueError,'INDEX_CACHE_QUOTA_EXCEEDED'):
            prepare_index(self.root/'tiny-cache',self.manifest_bytes,self.manifest_sha,lambda:None,lambda _:None,max_cache_bytes=1)
        with self.assertRaisesRegex(ValueError,'INDEX_PACKAGE_HASH_MISMATCH'):
            prepare_index(self.root/'bad-cache',self.manifest_bytes,self.manifest_sha,lambda:io.BytesIO(b'bad'),lambda _:None)
        data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w') as archive:
            info=tarfile.TarInfo('texts.utf8')
            info.type=tarfile.SYMTYPE
            info.linkname='/etc/passwd'
            archive.addfile(info)
        raw=data.getvalue()
        manifest=json.loads(self.manifest_bytes)
        manifest['package']={'name':'index.tar','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        encoded_manifest=encoded(manifest)
        with self.assertRaisesRegex(ValueError,'INDEX_MEMBER_INVALID'):
            prepare_index(self.root/'link-cache',encoded_manifest,hashlib.sha256(encoded_manifest).hexdigest(),lambda:io.BytesIO(raw),lambda _:None)
        self.assertFalse(list((self.root/'link-cache').glob('.staging-*')))

    def test_callback_and_timeout_reap_actual_child(self):
        for mode in ['cancel','timeout']:
            with self.reader('runtime-child-'+mode) as reader:
                pid_file=reader.runtime/'child.pid'
                reader.executable.write_text('#!/bin/sh\necho $$ > "'+str(pid_file)+'"\nexec sleep 60\n',encoding='utf-8')
                def callback(_, mode=mode, pid_file=pid_file):
                    if mode=='cancel' and pid_file.exists():
                        raise RuntimeError('fenced')
                with self.assertRaisesRegex((ValueError,RuntimeError),'fenced|QUERY_TIMEOUT'):
                    write_spans(reader,query('token',{'type':'term','attr':'form','op':'eq','value':'A'}),
                                self.root/('child-'+mode),callback,timeout=.1 if mode=='timeout' else 5)
                pid=int(pid_file.read_text('utf-8').strip())
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid,0)
                self.assertEqual(list(reader.runtime.glob('query-*')),[])
