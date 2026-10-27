"""Real CWB capacity probe: full dump, deduplication, coordinate mapping and KWIC.

Shared-host measurements are exploratory, never formal S0 acceptance. Corpus
generation and query workload reuse the same fixed recipe as benchmark.py.
"""

import argparse
import hashlib
import heapq
import json
import math
import mmap
import os
import platform
import struct
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pipelines.query.benchmark import queries, read_if_exists, revisions
from pipelines.query.cwb import cqp_spans
from pipelines.query.reference_counts import count as independent_count

ROOT = Path(__file__).resolve().parents[2]
TOKEN = struct.Struct('<III')
OFFSET = struct.Struct('<Q')


def digest(path):
    with path.open('rb') as data:
        return hashlib.file_digest(data, 'sha256').hexdigest()


def percentile95(values):
    return sorted(values)[max(0, math.ceil(len(values) * .95) - 1)]


def build_input(target, size, seed):
    """Persist every actual token coordinate; no formula substitutes for lookup."""
    counts = {'tokens': 0, 'characters': 0, 'revisions': 0, 'sentences': 0}
    templates = []
    with (target / 'input.vrt').open('w', encoding='utf-8', newline='\n') as vrt, (target / 'tokens.map').open('wb') as mapping, (target / 'revisions.jsonl').open('wb') as texts, (target / 'revision-offsets.map').open('wb') as offsets:
        for ordinal, revision in enumerate(revisions('token', size, seed)):
            vrt.write('<p>\n<s>\n')
            for token in revision.tokens:
                vrt.write(token['attrs']['form'] + '\n')
                mapping.write(TOKEN.pack(ordinal, token['start'], token['end']))
                counts['tokens'] += 1
            vrt.write('</s>\n</p>\n')
            offsets.write(OFFSET.pack(texts.tell()))
            texts.write((json.dumps({'revision_id': revision.revision_id, 'text': revision.text}, ensure_ascii=False) + '\n').encode('utf-8'))
            counts['characters'] += len(revision.text)
            counts['revisions'] += 1
            counts['sentences'] += 1
            if ordinal < 20:
                templates.append({'text': revision.text, 'tokens': revision.tokens})
    return counts, templates


def expected_count(query, templates, size):
    full, tail = divmod(size, 100)
    cycle, remaining = divmod(full, 20)
    result = sum(independent_count(query, item) for item in templates) * cycle
    result += sum(independent_count(query, templates[i]) for i in range(remaining))
    if tail:
        template = templates[full % 20]
        partial = {**template, 'tokens': template['tokens'][:tail], 'text': template['text'][:tail * 4 - 1]}
        result += independent_count(query, partial)
    return result


class Coordinates:
    def __init__(self, target):
        self.handles = [(target / name).open('rb') for name in ('tokens.map', 'revisions.jsonl', 'revision-offsets.map')]
        self.tokens, self.texts, self.offsets = [mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) for handle in self.handles]

    def close(self):
        for mapping in (self.tokens, self.texts, self.offsets):
            mapping.close()
        for handle in self.handles:
            handle.close()

    def page_and_counts(self, spans):
        documents = set()

        def mapped():
            for start, end in spans:
                document, left, _ = TOKEN.unpack_from(self.tokens, start * TOKEN.size)
                last_document, _, right = TOKEN.unpack_from(self.tokens, (end - 1) * TOKEN.size)
                if document != last_document:
                    raise AssertionError('CQP span crossed a sentence/document boundary')
                documents.add(document)
                yield document, left, right

        first = heapq.nsmallest(50, mapped())  # consumes and maps all complete spans
        page = []
        for document, left, right in first:
            offset = OFFSET.unpack_from(self.offsets, document * OFFSET.size)[0]
            end = self.texts.find(b'\n', offset)
            revision = json.loads(self.texts[offset:end])
            text = revision['text']
            page.append({'revision_id': revision['revision_id'], 'start': left, 'end': right, 'left': text[max(0, left - 40):left], 'match': text[left:right], 'right': text[right:right + 40]})
        return {'total_hits': len(spans), 'matched_documents': len(documents), 'matched_segments': len(documents), 'page': page}


def create_measured_executable(target, name, deadline):
    """Stdlib wrapper measures the actual CQP child and enforces its whole-run bound."""
    log = target / f'{name}.json'
    wrapper = target / f'{name}.py'
    wrapper.write_text(f'''#!{sys.executable}
import json, resource, subprocess, sys, time
started = time.perf_counter()
code = 124
try:
    code = subprocess.run(['cqp', *sys.argv[1:]], timeout={deadline!r}, check=False).returncode
finally:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    with open({str(log)!r}, 'w') as output:
        json.dump({{'wall_seconds': time.perf_counter()-started, 'user_cpu_seconds': usage.ru_utime, 'system_cpu_seconds': usage.ru_stime, 'max_rss_bytes': usage.ru_maxrss*1024, 'exit_code': code}}, output)
sys.exit(code)
''', encoding='utf-8')
    wrapper.chmod(0o700)
    return wrapper, log


class DiskSampler:
    def __init__(self, directory):
        self.directory = directory
        self.peak = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        while not self.stop.is_set():
            total = 0
            for path in self.directory.rglob('*'):
                try:
                    if path.is_file():
                        total += path.stat().st_size
                except FileNotFoundError:
                    pass  # Atomic report replacement can remove a sampled path.
            self.peak = max(self.peak, total)
            self.stop.wait(.25)


def main():
    import resource  # Linux-only runner; pure mapping/oracle tests also run on Windows.

    parser = argparse.ArgumentParser()
    parser.add_argument('--size', type=int, required=True)
    parser.add_argument('--repeats', type=int, default=20)
    parser.add_argument('--concurrency', type=int, default=5)
    parser.add_argument('--seed', type=int, default=20261016)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    target = args.output.resolve()
    if not target.is_relative_to((ROOT / 'tmp').resolve()) or min(args.size, args.repeats, args.concurrency) < 1:
        parser.error('Positive counts and a new output directory under repository tmp/ are required')
    target.mkdir(parents=True, exist_ok=False)
    source_directory = target / 'source'
    source_directory.mkdir()
    for name in ('cwb.py', 'cwb_benchmark.py', 'benchmark.py', 'reference_counts.py'):
        (source_directory / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    sampler = DiskSampler(target)
    sampler.thread.start()
    started = time.perf_counter()
    report = {'status': 'building', 'formal_acceptance': False, 'reason': 'Synthetic repeated-template data; shared host with explicit container limits, not the dedicated 8-vCPU/32-GiB acceptance machine.', 'engine': 'CWB/CQP 3.5.0 via production-candidate cqp_spans adapter', 'generator': {'version': 's0-synthetic-v1', 'seed': args.seed, 'tokens_requested': args.size, 'templates': 20, 'one_sentence_per_revision': True}, 'queries': list(queries('token', 20)), 'repeats': args.repeats, 'concurrency': args.concurrency, 'runs': [], 'cold_runs': [], 'warmup_runs': [], 'measurement': 'Whole CQP dump, Python deduplication, mapping every hit to persisted Unicode coordinates, exact hit/document/sentence counts, first 50 KWIC rows. Raw CQP child timing separately measured; end-to-end includes instrumentation wrapper startup.', 'hardware': {'platform': platform.platform(), 'python': platform.python_version(), 'cpu_count': os.cpu_count(), 'cpu_model': next((line.split(':', 1)[1].strip() for line in (read_if_exists('/proc/cpuinfo') or '').splitlines() if line.startswith('model name')), None), 'cpu_max': read_if_exists('/sys/fs/cgroup/cpu.max'), 'memory_max': read_if_exists('/sys/fs/cgroup/memory.max'), 'disk_type': 'not_verified', 'independent_host': False}, 'code_sha256': {name: digest(Path(__file__).with_name(name)) for name in ('cwb.py', 'cwb_benchmark.py', 'benchmark.py', 'reference_counts.py')}}

    def save():
        report['wall_seconds'] = time.perf_counter() - started
        report['memory'] = {'parent_max_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024, 'child_max_rss_bytes': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024, 'cgroup_peak_bytes_including_file_cache': read_if_exists('/sys/fs/cgroup/memory.peak')}
        report['sampled_peak_disk_bytes'] = sampler.peak
        report['disk_sampling_interval_seconds'] = .25
        report['disk_peak_is_exact'] = False
        report['cold_measurement'] = 'First query execution after index build; OS file cache was not cleared.'
        pending = target / 'report.next.json'
        pending.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        pending.replace(target / 'report.json')

    coordinates = None
    try:
        report['actual'], templates = build_input(target, args.size, args.seed)
        report['input_build_seconds'] = time.perf_counter() - started
        registry, data, timing = (target / name for name in ('registry', 'data', 'timing'))
        for directory in (registry, data, timing):
            directory.mkdir()
        report['build_commands'] = []
        for name, command in [('encode', ['cwb-encode', '-d', str(data), '-c', 'utf8', '-f', str(target / 'input.vrt'), '-R', str(registry / 's0'), '-S', 's', '-S', 'p']), ('makeall', ['cwb-makeall', '-r', str(registry), '-V', 'S0'])]:
            stamp = time.perf_counter()
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            process = subprocess.run(command, capture_output=True, text=True, check=True, timeout=1800)
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            (target / f'{name}.log').write_text(process.stdout + process.stderr, encoding='utf-8')
            report['build_commands'].append({'name': name, 'seconds': time.perf_counter() - stamp, 'user_cpu_seconds': after.ru_utime - before.ru_utime, 'system_cpu_seconds': after.ru_stime - before.ru_stime, 'cumulative_child_max_rss_bytes': after.ru_maxrss * 1024})
        report['total_build_seconds'] = time.perf_counter() - started
        version = subprocess.run(['cqp', '-v'], capture_output=True, text=True, check=False)
        report['cqp_version'] = (version.stdout + version.stderr).strip()
        report['files'] = {str(path.relative_to(target)): {'bytes': path.stat().st_size, 'sha256': digest(path)} for path in target.rglob('*') if path.is_file() and path.name != 'report.json'}
        report['built_disk_bytes'] = sum(item['bytes'] for item in report['files'].values())
        report['independent_expected_counts'] = [expected_count(query, templates, args.size) for query in report['queries']]
        report['count_oracle'] = 'Independent brute-force matching of raw template values, weighted by exact full/partial template repetition; no CQP or PositionIndex query calls.'
        coordinates = Coordinates(target)
        report['status'] = 'running'
        save()

        def run(query, name, expected, deadline=30):
            wrapper, log = create_measured_executable(timing, name, deadline)
            stamp = time.perf_counter()
            spans = cqp_spans(query, registry, executable=str(wrapper), timeout=deadline + 5)
            dumped = time.perf_counter()
            result = coordinates.page_and_counts(spans)
            ended = time.perf_counter()
            if result['total_hits'] != expected:
                raise AssertionError(f'{name} complete count differs: expected {expected}, observed {result["total_hits"]}')
            return {'name': name, 'total_hits': result['total_hits'], 'matched_segments': result['matched_segments'], 'matched_documents': result['matched_documents'], 'first_page_rows': len(result['page']), 'first_page_sha256': hashlib.sha256(json.dumps(result['page'], sort_keys=True).encode()).hexdigest(), 'first_page_sample': result['page'][:2], 'raw_cqp': json.loads(log.read_text()), 'adapter_dump_parse_dedup_seconds': dumped - stamp, 'full_coordinate_map_and_kwic_seconds': ended - dumped, 'first_page_and_complete_count_seconds': ended - stamp, 'count_matches_independent_reference': True}

        for qid, query in enumerate(report['queries']):
            report['cold_runs'].append(run(query, f'cold-{qid}', report['independent_expected_counts'][qid]))
            report['warmup_runs'].append(run(query, f'warm-{qid}', report['independent_expected_counts'][qid]))
        high = {'dsl_version': 'corpus-query/v1', 'unit': 'token', 'within': 'sentence', 'overlap': 'all', 'pattern': {'type': 'sequence', 'items': [report['queries'][0]['pattern'], {'type': 'gap', 'min': 0, 'max': 8}, report['queries'][1]['pattern']]}}
        report['high_frequency_gap'] = {'query': high, 'unit': 'token_gap_not_character_gap', 'run': run(high, 'high-frequency', expected_count(high, templates, args.size), 120)}
        save()
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {pool.submit(run, query, f'repeat-{repeat}-query-{qid}', report['independent_expected_counts'][qid]): qid for repeat in range(args.repeats) for qid, query in enumerate(report['queries'])}
            for future in as_completed(futures):
                report['runs'].append({'query_id': futures[future], **future.result()})
                save()
                if len(report['runs']) % 20 == 0:
                    print(json.dumps({'stage': 'queries', 'completed': len(report['runs']), 'requested': args.repeats * 20}), flush=True)
        report['p95_seconds'] = percentile95([row['first_page_and_complete_count_seconds'] for row in report['runs']])
        report['per_query'] = [{'query_id': qid, 'count': report['independent_expected_counts'][qid], 'p95_seconds': percentile95([row['first_page_and_complete_count_seconds'] for row in report['runs'] if row['query_id'] == qid]), 'raw_cqp_p95_seconds': percentile95([row['raw_cqp']['wall_seconds'] for row in report['runs'] if row['query_id'] == qid])} for qid in range(20)]
        report['status'] = 'completed'
    except BaseException as error:
        report['status'] = 'failed'
        report['error'] = str(error)
        raise
    finally:
        if coordinates:
            coordinates.close()
        sampler.stop.set()
        sampler.thread.join()
        save()
    print(json.dumps({'report': str(target / 'report.json'), 'status': report['status'], 'p95_seconds': report.get('p95_seconds')}), flush=True)


if __name__ == '__main__':
    main()
