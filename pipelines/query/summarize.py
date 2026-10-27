"""Derive per-query latency summaries without changing the raw benchmark evidence."""
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def summarize(report):
    if report['status'] != 'completed':
        raise ValueError('Only completed experiments can be summarized')
    if not report['queries'] or type(report['repeats']) is not int or report['repeats'] < 1:
        raise ValueError('Queries and positive integer repetition count are required')
    for run in report['query_runs']:
        if type(run['query_id']) is not int or not 0 <= run['query_id'] < len(report['queries']):
            raise ValueError('Unknown query ID in measured runs')
        if type(run['seconds']) not in (int,float) or not math.isfinite(run['seconds']) or run['seconds'] < 0:
            raise ValueError('Timing must be finite and nonnegative')
        if type(run['total_hits']) is not int or run['total_hits'] < 0:
            raise ValueError('Complete counts must be nonnegative integers')
    per_query = []
    for qid in range(len(report['queries'])):
        runs = [row for row in report['query_runs'] if row['query_id'] == qid]
        if len(runs) != report['repeats']:
            raise ValueError('Missing repetitions')
        if len({row['total_hits'] for row in runs}) != 1:
            raise ValueError('Complete counts changed between identical query repetitions')
        timings = sorted(row['seconds'] for row in runs)
        per_query.append({'query_id':qid,'query':report['queries'][qid],'repetitions':len(runs),'total_hits':runs[0]['total_hits'],
            'p95_seconds':timings[math.ceil(len(timings)*0.95)-1],'max_seconds':max(timings)})
    return {'status':'completed','formal_acceptance':False,'engine':report['engine'],
        'actual':report['actual'],'per_query':per_query,
        'all_repeated_counts_consistent':True,
        'hardware':report['hardware'],'generator':report['generator'],
        'code_sha256':report['code_sha256'],'sample_and_index_files':report['index']['files'],
        'concurrency':report['concurrency'],'repeats':report['repeats'],
        'max_query_p95_seconds':max(row['p95_seconds'] for row in per_query),
        'max_complete_count_seconds':max(row['max_seconds'] for row in per_query),
        'total_build_seconds':report['index']['total_build_seconds'],
        'index_and_mapping_bytes':report['index']['disk_bytes'],
        'peak_process_memory_bytes':report['peak_process_memory_bytes'],
        'high_frequency_gap_seconds':report['high_frequency_gap']['seconds'],
        'measured_p95_within_3_seconds':all(row['p95_seconds'] <= 3 for row in per_query),
        'query_ids_exceeding_3_seconds_p95':[row['query_id'] for row in per_query if row['p95_seconds'] > 3],
        'interpretation':'Exploratory shared-host repeated-template measurements only; full counts precede first page. Cold process reopening, real-material memory and disk peak are not measured.'}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--publish',action='store_true',help='Write durable compact summary only after all three experiments finish')
    parser.add_argument('--compare',type=Path,nargs=2,metavar=('BASELINE','CANDIDATE'))
    parser.add_argument('--output',type=Path,help='New durable comparison report')
    args = parser.parse_args()
    if args.compare:
        if not args.output or args.output.exists(): parser.error('Comparison needs a new --output path')
        reports = [json.loads(path.read_text(encoding='utf-8')) for path in args.compare]
        before,after = reports
        if before['index']['files'] != after['index']['files'] or before['queries'] != after['queries']:
            raise ValueError('Input manifests or queries differ')
        for field in ('concurrency','repeats','actual','generator'):
            if before[field] != after[field]: raise ValueError('Comparison differs in '+field)
        baseline,candidate = map(summarize,reports)
        if [q['total_hits'] for q in baseline['per_query']] != [q['total_hits'] for q in candidate['per_query']]:
            raise ValueError('Candidate count differs from baseline')
        if before['high_frequency_gap']['total_hits'] != after['high_frequency_gap']['total_hits']:
            raise ValueError('Candidate high-frequency count differs from baseline')
        result = {'formal_acceptance':False,'identical_input_and_index_manifest':True,'identical_queries_and_counts':True,
            'raw_report_sha256':{name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in zip(('baseline','candidate'),args.compare)},
            'baseline':baseline,'candidate':candidate,
            'per_query_p95_ratio_after_over_before':[b['p95_seconds']/a['p95_seconds'] for a,b in zip(baseline['per_query'],candidate['per_query'])],
            'interpretation':'Sequential shared-host experiments; exact corpus/index manifest and workload match. No causal hardware control or formal capacity acceptance.'}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({name:summary['max_query_p95_seconds'] for name,summary in [('baseline',baseline),('candidate',candidate)]}))
        raise SystemExit(0)
    summaries = []
    for path in [ROOT/'tmp/query-s0'/name/'report.json' for name in ('character-10m','token-10m','token-1m')]:
        report = json.loads(path.read_text(encoding='utf-8'))
        if report['status'] != 'completed': continue
        result = summarize(report)
        result['experiment'] = path.parent.name
        result['raw_report_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        summaries.append(result)
        path.with_name('summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(path.parent.name,json.dumps({key:result[key] for key in ('max_query_p95_seconds','max_complete_count_seconds','total_build_seconds','peak_process_memory_bytes')}))
    if args.publish:
        expected = {('token',1000000),('token',10000000),('character',10000000)}
        actual = {(s['generator']['requested_unit'],s['generator']['requested_size']) for s in summaries}
        if not expected <= actual: raise ValueError('All three required scales must finish before publishing the compact summary')
        output = ROOT/'pipelines/query/results'
        output.mkdir(exist_ok=True)
        (output/'2026-10-16.json').write_text(json.dumps({
            'formal_acceptance':False,'experiments':summaries,
            'golden_sha256':hashlib.sha256((ROOT/'tests/golden/query-v1.json').read_bytes()).hexdigest(),
            'unverified':['Dedicated 8 vCPU/32 GiB/200 GiB SSD hardware', 'Real source heterogeneity and memory',
                'CWB capacity', 'Cold process/index reopening', 'Disk/temp-file peak', 'Index reuse and subset quota'],
            'interpretation':'Synthetic repeated templates share text/token Python objects. Full-size postings are built; object memory is not representative. First-page timing equals complete counting. First execution after memory build is not cold restart.',
        },ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
