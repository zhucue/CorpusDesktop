import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from pipelines.exports.render import NOTE_FIELDS, ExportError, render_export
from pipelines.exports.rows import attribution_for_ordinals, iter_query_rows
from pipelines.query.source_results import ABSENT, SPAN

ROOT = Path(__file__).resolve().parents[2]


class Reader:
    """Small positional test double: renderer must never request query matching."""
    is_project = True
    count = 120

    def __init__(self, directory, private=True):
        self.directory, self.private = directory, private

    def record(self, ordinal):
        return (ordinal+10,)

    def metadata(self, ordinal):
        return {'origin_kind': 'private' if self.private else 'source',
                'revision_id': f'r{ordinal}', 'source_id': None if self.private else 'fixture',
                'source_sentence_id': None if self.private else ordinal+10,
                'source_url': None if self.private else f'https://example.test/{ordinal+10}',
                'owner': 'real-upstream-owner', 'license': 'fixture-license', 'language': 'eng'}

    def span_hit(self, sentence, left, right, first, last, *, context_codepoints):
        return {'document_id': f'd{sentence}', 'revision_id': f'r{sentence}',
                'segment_id': f's{sentence}', 'material_id': f'd{sentence}' if self.private else None,
                'start_cp': left+8, 'end_cp': right+8, 'context_start_cp': 8,
                'token_start': first, 'token_end': last,
                'global_token_start': first, 'global_token_end': last,
                'left': '中😀\r\n"', 'match': '=1+2', 'right': '\t@SUM(1)'}


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tmp', prefix='export-test-')
        self.root = Path(self.temp.name)
        self.span = self.root/'spans.bin'
        self.span.write_bytes(b''.join(SPAN.pack(i, 0, 4, ABSENT, ABSENT) for i in range(120)))
        self.sha = hashlib.sha256(self.span.read_bytes()).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def rows(self, *, reader=None, count=120, run='q', result='result', checkpoint=lambda: None):
        return iter_query_rows(reader or Reader(self.root), self.span,
                               expected_sha256=self.sha, expected_records=count,
                               result_set_id=result, query_run_id=run, snapshot_id='snapshot',
                               single_source_id='actual-snapshot-namespace', checkpoint=checkpoint)

    def render(self, rows, *, format='json', expected=120, queries=None, **kwargs):
        return render_export(self.root/format, format=format, kind='query',
                             methods={'queries':queries or [{'query_run_id':'q','result_set_id':'result', 'counts':{'total_hits':expected}}]},
                             rows=rows if callable(rows) else lambda _:rows,
                             expected_rows=expected, progress_callback=lambda _:None, **kwargs)

    def test_json_exact_full_result_not_page_and_private_provenance(self):
        result = self.render(self.rows())
        content = json.loads(result['path'].read_bytes())
        self.assertEqual(len(content['rows']), 120)
        row = content['rows'][-1]
        self.assertEqual(row['row_number'], 120)
        self.assertEqual(row['hit_ref']['ordinal'], 119)
        self.assertEqual((row['start_cp'],row['end_cp']), (8,12))
        self.assertEqual(row['left'], '中😀\r\n"')
        self.assertEqual(row['match'], '=1+2')
        for key in ('source_id', 'source_url', 'source_sentence_id', 'owner', 'license'):
            self.assertIsNone(row[key])
        self.assertEqual(result['sha256'], hashlib.sha256(result['path'].read_bytes()).hexdigest())

    def test_csv_package_documented_prefix_quotes_crlf_unicode_and_counts(self):
        result = self.render(self.rows(), format='csv')
        with zipfile.ZipFile(result['path']) as package:
            self.assertEqual(set(package.namelist()), {'results.csv','methods.json'})
            methods = json.loads(package.read('methods.json'))
            self.assertEqual(methods['csv_encoding']['recipe'], 'text-prefix/v1')
            raw = package.read('results.csv')
            self.assertIn(b'\r\n', raw)
            rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8'), newline='')))
        self.assertEqual(len(rows), 120)
        self.assertEqual(rows[0]['match'], "'=1+2")
        self.assertEqual(rows[0]['left'][1:], '中😀\r\n"')
        self.assertEqual(rows[0]['right'][1:], '\t@SUM(1)')
        self.assertEqual(rows[0]['start_cp'], '8')
        self.assertEqual(rows[0]['owner'], '')

    def test_source_upstream_attribution_and_legacy_stream_namespace(self):
        reader = Reader(self.root, private=False)
        reader.is_project = False
        (self.root/'members.jsonl').write_text(''.join(json.dumps({
            'ordinal':i, 'id':i+10, 'revision_id':f'r{i}', 'owner':f'owner{i}',
            'license':'CC-BY-2.0-FR', 'language':'eng', 'source_url':f'https://example.test/{i+10}'
        })+'\n' for i in range(120)), 'utf-8')
        rows = list(self.rows(reader=reader))
        self.assertEqual(rows[119]['owner'], 'owner119')
        self.assertEqual(rows[119]['source_sentence_id'], '129')
        self.assertEqual(rows[119]['source_id'], 'actual-snapshot-namespace')
        self.assertEqual(rows[119]['license'], 'CC-BY-2.0-FR')
        authors = attribution_for_ordinals(reader,[119,0,119],single_source_id='actual-snapshot-namespace')
        self.assertEqual(set(authors),{0,119})
        self.assertEqual(authors[119]['owner'],'owner119')
        self.assertEqual(authors[0]['source_id'],'actual-snapshot-namespace')
        self.assertIsNone(attribution_for_ordinals(Reader(self.root),[0])[0]['owner'])

    def test_multiple_runs_restart_display_number_keep_reference(self):
        def rows():
            yield from self.rows(run='q1', result='r1')
            yield from self.rows(run='q2', result='r2')
        queries = [{'query_run_id':f'q{i}', 'result_set_id':f'r{i}', 'counts':{'total_hits':120}} for i in (1,2)]
        result = self.render(rows(), expected=240, queries=queries)
        rows = json.loads(result['path'].read_bytes())['rows']
        self.assertEqual(rows[120]['row_number'], 1)
        self.assertEqual(rows[120]['hit_ref'], {'result_set_id':'r2','ordinal':0})

    def test_note_fixed_revision_draft_and_references(self):
        note = dict.fromkeys(NOTE_FIELDS)
        note.update(record_type='note_revision', note_id='note', revision=2, title='标题',
                    body="'=draft\r\n原文", status='draft', evidence_refs=[{'id':'ev','start_cp':8}],
                    query_run_ids=['zero'], authorization_query_run_ids=['zero'], authorization_evidence_ids=['ev'])
        result = render_export(self.root/'note', format='json', kind='notes', methods={'queries':[{'total_hits':0}]},
                               rows=lambda _:iter([note]), expected_rows=1, progress_callback=lambda _:None)
        self.assertEqual(json.loads(result['path'].read_bytes())['rows'], [note])

    def test_count_mismatch_and_bad_hash_fail_without_artifact(self):
        with self.assertRaisesRegex(ExportError, 'EXPORT_COUNT_MISMATCH'):
            self.render(self.rows(), expected=119)
        self.assertEqual(list((self.root/'json').iterdir()), [])
        self.span.write_bytes(b'X' + self.span.read_bytes()[1:])
        with self.assertRaisesRegex(ExportError, 'EXPORT_RESULT_MISMATCH'):
            list(self.rows())

    def test_hard_byte_limit_and_existing_workspace_are_counted(self):
        with self.assertRaisesRegex(ExportError, 'EXPORT_TOO_LARGE'):
            self.render(self.rows(), format='csv', max_bytes=1024)
        self.assertEqual(list((self.root/'csv').iterdir()), [])
        (self.root/'json').mkdir()
        (self.root/'json'/'other').write_bytes(b'X'*500)
        with self.assertRaisesRegex(ExportError, 'EXPORT_TOO_LARGE'):
            self.render(self.rows(), max_temporary_bytes=501)
        self.assertEqual((self.root/'json'/'other').read_bytes(), b'X'*500)

    def test_cancel_exception_propagates_and_partial_is_removed(self):
        class Cancelled(Exception):
            pass
        def rows():
            for i, row in enumerate(self.rows()):
                if i == 60:
                    raise Cancelled()
                yield row
        with self.assertRaises(Cancelled):
            self.render(rows())
        self.assertEqual(list((self.root/'json').iterdir()), [])

    def test_zero_result_is_valid_empty_export(self):
        result = self.render(iter(()), expected=0)
        self.assertEqual(json.loads(result['path'].read_bytes())['rows'], [])

    def test_per_run_counts_and_order_include_zero_run(self):
        queries = [{'query_run_id':'zero','result_set_id':'z','counts':{'total_hits':0}},
                   {'query_run_id':'q','result_set_id':'result','counts':{'total_hits':120}}]
        self.render(self.rows(), queries=queries)
        queries[0]['counts']['total_hits'] = 1
        queries[1]['counts']['total_hits'] = 119
        with self.assertRaisesRegex(ExportError, 'EXPORT_COUNT_MISMATCH'):
            self.render(self.rows(), format='csv', queries=queries)
        self.assertEqual(list((self.root/'csv').iterdir()), [])

    def test_global_deadline_reaches_row_factory_hash_and_callback_cancellation(self):
        def slow(checkpoint):
            with patch('pipelines.exports.render.time.monotonic', return_value=10**12):
                yield from self.rows(checkpoint=checkpoint)
        with self.assertRaisesRegex(ExportError, 'EXPORT_TIMEOUT'):
            self.render(slow)
        self.assertEqual(list((self.root/'json').iterdir()), [])
        class Cancelled(Exception):
            pass
        def cancel():
            raise Cancelled()
        with self.assertRaises(Cancelled):
            list(self.rows(checkpoint=cancel))


if __name__ == '__main__':
    unittest.main()
