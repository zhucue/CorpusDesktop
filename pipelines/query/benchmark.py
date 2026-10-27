"""Reproducible synthetic exploration; never labels shared-host timings as S0 acceptance.

Run as python -m pipelines.query.benchmark --unit token --size 1000000
The plan's full workload uses --queries 20 --repeats 20 --concurrency 5.
Use separate output directories per size, unit and engine run.
"""
import argparse
import hashlib
import json
import math
import os
import platform
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pipelines.query.engine import PositionIndex, Revision

ROOT = Path(__file__).resolve().parents[2]
ALPHABET = '一二三四五六七八九十甲乙丙丁戊己庚辛壬癸'


def read_if_exists(path):
    p = Path(path)
    return p.read_text().strip() if p.exists() else None


def peak_memory_bytes():
    if os.name != 'nt':
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if platform.system() == 'Darwin' else 1024)
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in (
            'PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
            'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    value = Counters()
    value.cb = ctypes.sizeof(value)
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    if not ctypes.windll.psapi.GetProcessMemoryInfo(handle,ctypes.byref(value),value.cb):
        raise OSError('Cannot measure process peak memory')
    return value.PeakWorkingSetSize


def revisions(unit,size,seed):
    rng = random.Random(seed)
    templates = []
    block = 100 if unit == 'token' else 1000
    for i in range(20):
        values = rng.choices(range(20),weights=range(20,0,-1),k=block)
        if unit == 'token':
            words = [f'w{value:02d}' for value in values]
            text = ' '.join(words)
            tokens = [{'start':j*4,'end':j*4+3,'attrs':{'form':word}} for j,word in enumerate(words)]
        else:
            text = ''.join(ALPHABET[value] for value in values)
            tokens = []
        templates.append((text,tokens))
    for ordinal,start in enumerate(range(0,size,block)):
        text,tokens = templates[ordinal%len(templates)]
        take = min(block,size-start)
        if take != block:
            text = text[:take*4-1] if unit == 'token' else text[:take]
            tokens = tokens[:take]
        yield Revision(str(ordinal),text,[(0,len(text))],[(0,len(text))],tokens,{})


def queries(unit,count):
    values = [f'w{i:02d}' for i in range(20)] if unit == 'token' else list(ALPHABET)
    for i in range(count):
        def atom(n):
            return {'type':'term','attr':'form','op':'eq','value':values[n%20]} if unit == 'token' else {'type':'literal','value':values[n%20]}
        pattern = atom(i)
        if i%20 >= 10:
            items = [atom(i)]
            if i%20 >= 15: items.append({'type':'gap','min':0,'max':2})
            items.append(atom(i+1))
            pattern = {'type':'sequence','items':items}
        yield {'dsl_version':'corpus-query/v1','unit':unit,'within':'sentence','overlap':'all','pattern':pattern}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--unit',choices=['character','token'],required=True)
    parser.add_argument('--size',type=int,required=True)
    parser.add_argument('--queries',type=int,default=20)
    parser.add_argument('--repeats',type=int,default=20)
    parser.add_argument('--concurrency',type=int,default=5)
    parser.add_argument('--seed',type=int,default=20261016)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-report',type=Path,help='Require identical input manifest, queries and workload before comparison')
    args = parser.parse_args()
    target = args.output.resolve()
    if not target.is_relative_to((ROOT/'tmp').resolve()): parser.error('All experiment artifacts must be under repository tmp/')
    if min(args.size,args.queries,args.repeats,args.concurrency) < 1: parser.error('Counts must be positive')
    target.mkdir(parents=True,exist_ok=False)
    for name in ('engine.py','benchmark.py'):
        (target/name).write_bytes((Path(__file__).parent/name).read_bytes())
    started = time.perf_counter()
    index = PositionIndex(revisions(args.unit,args.size,args.seed))
    build_seconds = time.perf_counter()-started
    print(json.dumps({'stage':'indexed','unit':args.unit,'size':args.size,'seconds':build_seconds}),flush=True)
    index.save(target/'index')
    checksums = {}
    for path in (target/'index').iterdir():
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''): digest.update(chunk)
        checksums[path.name] = {'sha256':digest.hexdigest(),'bytes':path.stat().st_size}
    query_list = list(queries(args.unit,args.queries))
    baseline = None
    if args.baseline_report:
        baseline_bytes = args.baseline_report.read_bytes()
        previous = json.loads(baseline_bytes)
        if previous['status'] != 'completed' or previous['index']['files'] != checksums:
            raise ValueError('Comparison requires a completed baseline with identical corpus and index manifest')
        if previous['queries'] != query_list or (previous['concurrency'],previous['repeats']) != (args.concurrency,args.repeats):
            raise ValueError('Comparison workload differs from baseline')
        baseline = {'report':str(args.baseline_report),'sha256':hashlib.sha256(baseline_bytes).hexdigest(),
                    'identical_input_and_index_manifest':True,'identical_query_workload':True}
    report = {'status':'running','formal_acceptance':False,'reason':'Synthetic repeated-template corpus on shared hardware; exploratory only.',
        'engine':'Python PositionIndex S0 prototype (not CWB)',
        'baseline_comparison':baseline,
        'recipe':'supplied whitespace tokens / synthetic character blocks; normalization=none; unicode codepoints',
        'code_sha256':{name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in ('engine.py','benchmark.py')},
        'generator':{'version':'s0-synthetic-v1','seed':args.seed,'requested_unit':args.unit,'requested_size':args.size,'template_count':20},
        'workload':'20-query cycles: 10 atoms, 5 adjacent phrases, 5 gaps 0..2; separate high-frequency gap 0..8',
        'actual':{'characters':index.character_count,'tokens':index.token_count,'revisions':len(index.revisions)},
        'hardware':{'platform':platform.platform(),'python':platform.python_version(),'cpu_count':os.cpu_count(),
            'cpu_model':next((line.split(':',1)[1].strip() for line in (read_if_exists('/proc/cpuinfo') or '').splitlines() if line.startswith('model name')),platform.processor()),
            'cgroup_cpu_max':read_if_exists('/sys/fs/cgroup/cpu.max'),'cgroup_memory_max':read_if_exists('/sys/fs/cgroup/memory.max'),
            'disk_type':None,'independent_host':False},
        'index':{'build_seconds':build_seconds,'persist_and_hash_seconds':time.perf_counter()-started-build_seconds,
                 'total_build_seconds':time.perf_counter()-started,
                 'files':checksums,'disk_bytes':sum(v['bytes'] for v in checksums.values())},
        'queries':query_list,'query_runs':[],'concurrency':args.concurrency,'repeats':args.repeats,
        'first_page_measurement':'Conservative: execute returns first 50 only after complete counting; page and total latency are equal.',
        'cold_measurement':'First execution after in-memory build, not cold process/index reopening.',
        'cold_query_seconds':[],'warmup_seconds':[]}
    report_path = target/'report.json'
    def save():
        report['peak_process_memory_bytes'] = peak_memory_bytes()
        report['wall_seconds'] = time.perf_counter()-started
        temporary = report_path.with_suffix('.next.json')
        temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        temporary.replace(report_path)
    save()
    for query in query_list:
        stamp = time.perf_counter()
        index.execute(query)
        report['cold_query_seconds'].append(time.perf_counter()-stamp)
        stamp = time.perf_counter()
        index.execute(query)
        report['warmup_seconds'].append(time.perf_counter()-stamp)
    high = {'dsl_version':'corpus-query/v1','unit':args.unit,'within':'sentence','overlap':'all','pattern':{
        'type':'sequence','items':[query_list[0]['pattern'],{'type':'gap','min':0,'max':8},query_list[1 if len(query_list)>1 else 0]['pattern']]}}
    stamp = time.perf_counter()
    high_result = index.execute(high)
    report['high_frequency_gap'] = {'query':high,'seconds':time.perf_counter()-stamp,'total_hits':high_result['total_hits']}
    save()
    def run(qid):
        stamp = time.perf_counter()
        result = index.execute(query_list[qid])
        return {'query_id':qid,'seconds':time.perf_counter()-stamp,'total_hits':result['total_hits']}
    try:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [pool.submit(run,qid) for repeat in range(args.repeats) for qid in range(len(query_list))]
            for future in as_completed(futures):
                report['query_runs'].append(future.result())
                save()
                if len(report['query_runs'])%20 == 0: print(json.dumps({'stage':'queries','completed':len(report['query_runs'])}),flush=True)
        durations = sorted(row['seconds'] for row in report['query_runs'])
        report['p95_seconds'] = durations[max(0,math.ceil(len(durations)*0.95)-1)]
        report['status'] = 'completed'
    except BaseException as error:
        report['status'] = 'failed'
        report['error'] = str(error)
        raise
    finally:
        save()
    print(json.dumps({'report':str(report_path),'p95_seconds':report['p95_seconds'],'peak_bytes':report['peak_process_memory_bytes']}),flush=True)


if __name__ == '__main__': main()
