"""Full fixed-source result-file oracle; no query implementation in the oracle.

Token truth is the stored fixed token layer checked against original SQLite text,
not an independent re-tokenization or linguistic quality assessment.
"""
import argparse
import hashlib
import json
import platform
import shutil
import sqlite3
import struct
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path

from pipelines.query.source_index import TOKEN, digest
from pipelines.query.source_index_verify import CHARACTERS, TOKENS, request
from pipelines.query.source_reader import SourceIndexReader
from pipelines.query.source_results import first_page, read_page, write_spans

# Independently encoded reference records, not produced by write_spans/_spans.
REFERENCE = struct.Struct('<QIIQQ')
NO_TOKEN = 2**64 - 1


def check_pages(database, directory, output):
    data = json.loads((output / 'queries.json').read_text('utf-8'))
    db = sqlite3.connect(database.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    checks = []
    with SourceIndexReader(directory, verify=False) as reader:
        assert reader.runtime is None
        for item in data:
            n = item['counts']['total_hits']
            offsets = sorted({0, n // 2, max(0, n - 50), n})
            for offset in offsets:
                for context in (0, 40, 200):
                    page = read_page(reader, output / item['span_file'], offset,
                                     context_codepoints=context,
                                     expected_sha256=item['sha256'], expected_records=n)
                    with (output / item['oracle_file']).open('rb') as stream:
                        stream.seek(offset * REFERENCE.size)
                        expected = [REFERENCE.unpack(stream.read(REFERENCE.size))
                                    for _ in range(min(50, n - offset))]
                    assert len(page['hits']) == len(expected)
                    assert page['has_more'] == (offset + len(expected) < n)
                    for number, (hit, span) in enumerate(zip(page['hits'], expected), offset):
                        sentence, start, end, token_start, token_end = span
                        record = reader.record(sentence)
                        text = db.execute('SELECT text FROM sentences WHERE id=?', (record[0],)).fetchone()[0]
                        assert hit['result_ordinal'] == number
                        assert hit['sentence_ordinal'] == sentence
                        assert hit['source_sentence_id'] == record[0]
                        assert (hit['start_cp'], hit['end_cp']) == (start, end)
                        assert hit['match'] == text[start:end]
                        assert hit['left'] == text[max(0, start-context):start]
                        assert hit['right'] == text[end:end+context]
                        assert hit['revision_id'] == f'tatoeba:{record[0]}:{hashlib.sha256(text.encode()).hexdigest()}'
                        if token_start == NO_TOKEN:
                            assert all(hit[k] is None for k in ('token_start', 'token_end', 'global_token_start', 'global_token_end'))
                        else:
                            assert (hit['global_token_start'], hit['global_token_end']) == (token_start, token_end)
                            assert (hit['token_start'], hit['token_end']) == (token_start-record[5], token_end-record[5])
                    checks.append({'query': item['query'], 'offset': offset, 'context_codepoints': context,
                                   'returned': len(expected)})
    db.close()
    (output / 'fresh-process-pages.json').write_text(json.dumps({'status': 'passed', 'checks': checks}, ensure_ascii=False, indent=2), 'utf-8')


def verify(database, directory, output):
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    snapshots = output / 'source'
    snapshots.mkdir()
    names = ('source_results_verify.py', 'source_index_verify.py', 'source_reader.py',
             'source_results.py', 'source_cache.py', 'cwb.py', 'source_recipe.py')
    source_hashes = {}
    for name in names:
        path = Path(__file__).with_name(name)
        shutil.copyfile(path, snapshots / name)
        source_hashes[name] = digest(path)
    report = {'status': 'failed', 'formal_acceptance': False, 'runs': [],
              'input_sha256': digest(database), 'manifest_sha256': digest(directory / 'manifest.json'),
              'measured_source_sha256': source_hashes,
              'environment': {'platform': platform.platform(), 'python': platform.python_version(),
                              'cpu_max': Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
                              'memory_max': Path('/sys/fs/cgroup/memory.max').read_text().strip(),
                              'shared_host': True, 'cold_disk': False, 'repetitions': 1},
              'oracle_scope': 'All original SQLite sentences and fixed token coordinates; independent literal/phrase enumeration. All ordered span bytes plus first/middle/end pages and context. Not independent tokenization quality.'}
    queries = [request('character', v) for v in CHARACTERS] + [request('token', v) for v in TOKENS]
    expected = [{'query': query, 'hits': 0, 'sentences': 0, 'oracle_file': f'oracle-{i:02}.bin'}
                for i, query in enumerate(queries)]
    db = sqlite3.connect(database.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        with SourceIndexReader(directory, output / 'runtime') as reader, ExitStack() as stack:
            report['index_identity_sha256'] = reader.manifest['identity_sha256']
            report['recipe_sha256'] = reader.manifest['recipe_sha256']
            streams = [stack.enter_context((output / item['oracle_file']).open('xb')) for item in expected]
            observed_tokens, observed_characters = 0, 0
            oracle_started = time.monotonic()
            for ordinal, (sid, language, text) in enumerate(db.execute('SELECT id,language,text FROM sentences ORDER BY id')):
                record = reader.record(ordinal)
                assert record[0] == sid and reader.text(ordinal) == text
                token_end = reader.record(ordinal+1)[5] if ordinal+1 < reader.count else reader.manifest['counts']['tokens']
                positions, forms, cursor = [], [], 0
                for at in range(record[5], token_end):
                    doc, left, right = TOKEN.unpack_from(reader.maps['tokens.map'], at * TOKEN.size)
                    assert doc == ordinal and cursor <= left < right <= len(text) and not text[cursor:left].strip()
                    positions.append((left, right))
                    forms.append(text[left:right])
                    cursor = right
                assert not text[cursor:].strip()
                observed_tokens += len(forms)
                observed_characters += len(text)
                for index, value in enumerate(CHARACTERS):
                    at, count = 0, 0
                    while (at := text.find(value, at)) != -1:
                        streams[index].write(REFERENCE.pack(ordinal, at, at+len(value), NO_TOKEN, NO_TOKEN))
                        count += 1
                        at += 1
                    expected[index]['hits'] += count
                    expected[index]['sentences'] += bool(count)
                for index, words in enumerate(TOKENS, len(CHARACTERS)):
                    count = 0
                    for at in range(len(forms)-len(words)+1):
                        if tuple(forms[at:at+len(words)]) == words:
                            streams[index].write(REFERENCE.pack(ordinal, positions[at][0], positions[at+len(words)-1][1], record[5]+at, record[5]+at+len(words)))
                            count += 1
                    expected[index]['hits'] += count
                    expected[index]['sentences'] += bool(count)
                if ordinal % 100000 == 0:
                    print(json.dumps({'stage': 'independent_full_scan', 'sentences': ordinal+1}), flush=True)
            assert ordinal+1 == reader.count
            assert observed_tokens == reader.manifest['counts']['tokens']
            assert observed_characters == reader.manifest['counts']['characters']
            for stream in streams:
                stream.flush()
            report['full_mapping_check'] = {'sentences': reader.count, 'tokens': observed_tokens, 'characters': observed_characters}
            report['oracle_seconds'] = time.monotonic()-oracle_started
            for i, item in enumerate(expected):
                stamp = time.monotonic()
                preview = first_page(reader, item['query'])
                page_seconds = time.monotonic()-stamp
                stamp = time.monotonic()
                result = write_spans(reader, item['query'], output / f'result-{i:02}.bin', lambda _: None)
                full_seconds = time.monotonic()-stamp
                assert result['counts']['total_hits'] == item['hits']
                assert result['counts']['matched_segments'] == result['counts']['matched_documents'] == item['sentences']
                assert result['sha256'] == digest(output / item['oracle_file'])
                assert result['bytes'] == item['hits'] * REFERENCE.size
                assert preview == read_page(reader, result['path'], expected_sha256=result['sha256'], expected_records=item['hits'])
                report['runs'].append({'query': item['query'], 'counts': result['counts'], 'bytes': result['bytes'],
                                       'sha256': result['sha256'], 'span_file': result['path'].name,
                                       'oracle_file': item['oracle_file'], 'page_seconds': page_seconds,
                                       'full_spans_seconds': full_seconds, 'all_ordered_span_bytes_equal': True})
                print(json.dumps({'stage': 'query_checked', 'query': item['query'], 'hits': item['hits'],
                                  'page_seconds': page_seconds, 'full_spans_seconds': full_seconds, 'bytes': result['bytes']}), flush=True)
        (output / 'queries.json').write_text(json.dumps(report['runs'], ensure_ascii=False, indent=2), 'utf-8')
        subprocess.run([sys.executable, '-m', 'pipelines.query.source_results_verify', '--database', str(database),
                        '--index', str(directory), '--output', str(output), '--pages-only'], check=True, timeout=120)
        report['fresh_process_pages_sha256'] = digest(output / 'fresh-process-pages.json')
        report['status'] = 'passed'
    finally:
        db.close()
        report['wall_seconds'] = time.monotonic()-started
        (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pages-only', action='store_true')
    args = parser.parse_args()
    (check_pages if args.pages_only else verify)(args.database, args.index, args.output)
