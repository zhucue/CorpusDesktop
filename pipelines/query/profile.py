"""Small diagnostic experiment after capacity runs; never replaces their evidence."""
import argparse
import cProfile
import hashlib
import json
import pstats
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pipelines.query.benchmark import queries, revisions
from pipelines.query.engine import PositionIndex

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True,help='New report path; existing evidence is never overwritten')
    args = parser.parse_args()
    if args.output.exists(): parser.error('Output already exists')
    index = PositionIndex(revisions('character',1000000,20261016))
    query = next(queries('character',20))
    index.execute(query)
    def once(_=None):
        started = time.perf_counter()
        result = index.execute(query)
        return {'seconds':time.perf_counter()-started,'total_hits':result['total_hits']}
    stamp = time.perf_counter()
    serial = [once() for _ in range(5)]
    serial_wall = time.perf_counter()-stamp
    stamp = time.perf_counter()
    with ThreadPoolExecutor(max_workers=5) as pool:
        concurrent = list(pool.map(once,range(5)))
    concurrent_wall = time.perf_counter()-stamp
    profiler = cProfile.Profile()
    profiler.enable()
    profiled = index.execute(query)
    profiler.disable()
    stats = pstats.Stats(profiler)
    top = []
    for (filename,line,function),(primitive,calls,self_seconds,cumulative,callers) in sorted(stats.stats.items(),key=lambda item:item[1][3],reverse=True)[:20]:
        top.append({'file':filename,'line':line,'function':function,'calls':calls,'self_seconds':self_seconds,'cumulative_seconds':cumulative})
    report = {'formal_acceptance':False,'purpose':'Small profile after full workload; no capacity result is replaced',
        'engine':'Python PositionIndex','unit':'character','size':1000000,'seed':20261016,
        'engine_sha256':hashlib.sha256((ROOT/'pipelines/query/engine.py').read_bytes()).hexdigest(),
        'query':query,'serial_runs':serial,'serial_wall_seconds':serial_wall,
        'five_thread_runs':concurrent,'five_thread_wall_seconds':concurrent_wall,
        'profiled_total_hits':profiled['total_hits'],'hotspots':top}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'serial_wall_seconds':serial_wall,'five_thread_wall_seconds':concurrent_wall,'top':top[:8]}),flush=True)


if __name__ == '__main__': main()
