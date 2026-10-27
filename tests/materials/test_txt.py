"""Independent TXT boundary, lossless mapping and bounded failure cases."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pipelines.materials.txt import ROOT, MaterialError, parse_txt


class TxtTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp',prefix='txt-tests-')
        self.root=Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def parse(self,data,**kwargs):
        raw=self.root/(uuid4().hex+'.txt');raw.write_bytes(data)
        output=self.root/uuid4().hex
        return parse_txt(raw,output,document_id=str(uuid4()),revision_id=str(uuid4()),language='eng',
                         expected_sha256=hashlib.sha256(data).hexdigest(),expected_bytes=len(data),
                         progress_callback=kwargs.pop('progress_callback',lambda _:None),**kwargs)

    def test_bom_unicode_newline_and_full_partition(self):
        text='  Dr. Smith has 3.14 apples.\r\n\r\nHe said "Hi!"  e\u0301😀 end.\rLast\n'
        result=self.parse(b'\xef\xbb\xbf'+text.encode())
        root=result['manifest_path'].parent
        self.assertEqual((root/'canonical.utf8').read_bytes(),text.encode())
        rows=[json.loads(line) for line in (root/'segments.jsonl').read_text().splitlines()]
        pieces=[text[row['start_cp']:row['end_cp']] for row in rows]
        self.assertEqual(pieces,['  Dr. Smith has 3.14 apples.\r\n\r\n','He said "Hi!"  ','e\u0301😀 end.\r','Last\n'])
        self.assertEqual(''.join(pieces),text)
        raw=(root/'canonical.utf8').read_bytes()
        for row,piece in zip(rows,pieces):
            self.assertEqual(raw[row['byte_start']:row['byte_end']].decode(),piece)
        self.assertEqual(result['manifest']['source_mapping']['source_byte_prefix'],3)
        self.assertEqual(result['counts']['characters'],len(text))

    def test_abbreviations_initials_decimal_and_quotes(self):
        text='Mr. A. Smith met Mrs. Jones and Prof. Doe, e.g. at 3.14. "Yes!" Dr. Li left. i.e. done.'
        result=self.parse(text.encode());root=result['manifest_path'].parent
        rows=[json.loads(line) for line in (root/'segments.jsonl').read_text().splitlines()]
        self.assertEqual([text[r['start_cp']:r['end_cp']] for r in rows],
                         ['Mr. A. Smith met Mrs. Jones and Prof. Doe, e.g. at 3.14. ','"Yes!" ','Dr. Li left. ','i.e. done.'])

    def test_bad_utf8_nul_blank_and_long_segment_fail_whole(self):
        for raw,code in [(b'\xff','MATERIAL_ENCODING_INVALID'),(b'a\x00b','MATERIAL_NUL_REJECTED'),
                         (b' \r\n','MATERIAL_EMPTY'),(b'x'*100001,'MATERIAL_SEGMENT_TOO_LARGE')]:
            with self.subTest(code=code),self.assertRaisesRegex(MaterialError,code):
                self.parse(raw)
        self.assertEqual(list(self.root.rglob('manifest.json')),[])

    def test_cancellation_propagates_and_quota_is_explicit(self):
        def cancel(_):raise RuntimeError('cancelled lease')
        with self.assertRaisesRegex(RuntimeError,'cancelled lease'):
            self.parse(b'Text.',progress_callback=cancel)
        with self.assertRaisesRegex(MaterialError,'MATERIAL_QUOTA_EXCEEDED'):
            self.parse(b'Text.',max_temporary_bytes=2)
        self.assertEqual(list(self.root.rglob('manifest.json')),[])

    def test_utf8_and_sentence_boundary_across_read_chunks(self):
        # BOM + 65530 ASCII bytes puts a multibyte character at a decoder boundary.
        prefix = 'a '*32764+'ab'
        text = prefix+'😀!"  \r\nNext e\u0301 line.\n'
        result=self.parse(b'\xef\xbb\xbf'+text.encode())
        root=result['manifest_path'].parent
        self.assertEqual((root/'canonical.utf8').read_bytes(),text.encode())
        rows=[json.loads(line) for line in (root/'segments.jsonl').read_text().splitlines()]
        self.assertEqual([text[r['start_cp']:r['end_cp']] for r in rows],
                         [prefix+'😀!"  \r\n','Next e\u0301 line.\n'])
