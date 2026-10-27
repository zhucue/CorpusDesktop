"""Independent brute-force count check for the synthetic benchmark's 20 templates.

Uses persisted raw text/token values, never imports or invokes PositionIndex.
This validates benchmark counts under the recorded repeated-template recipe;
the independent hand-enumerated golden spans remain the coordinate oracle.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def count(query, revision):
    if query.get('condition') or query.get('filters'):
        raise ValueError('Reference benchmark checker only handles its fixed positive workload')
    character = query['unit'] == 'character'
    values = revision['text'] if character else [token['attrs']['form'] for token in revision['tokens']]
    def literal(atom):
        if character:
            if atom['type'] != 'literal': raise ValueError('Unexpected character workload')
            return atom['value']
        if atom['type'] != 'term' or atom['attr'] != 'form' or atom['op'] != 'eq':
            raise ValueError('Unexpected token workload')
        return [atom['value']]
    pattern = query['pattern']
    if pattern['type'] != 'sequence':
        needle = literal(pattern)
        return sum(values[start:start+len(needle)] == needle for start in range(len(values)))
    items = pattern['items']
    if len(items) == 2:
        first,last = map(literal,items)
        distances = [0]
    elif len(items) == 3 and items[1]['type'] == 'gap':
        first,last = literal(items[0]),literal(items[2])
        distances = range(items[1]['min'],items[1]['max']+1)
    else:
        raise ValueError('Unexpected benchmark sequence')
    result = 0
    for start in range(len(values)):
        if values[start:start+len(first)] != first: continue
        for distance in distances:
            following = start+len(first)+distance
            if values[following:following+len(last)] == last:
                result += 1
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reports',type=Path,nargs='+')
    parser.add_argument('--output',type=Path,default=ROOT/'pipelines/query/results/2026-10-16-reference-counts.json')
    args = parser.parse_args()
    results = []
    paths = args.reports or [ROOT/'tmp/query-s0'/name/'report.json' for name in ('character-10m','token-10m','token-1m')]
    for path in paths:
        report = json.loads(path.read_text(encoding='utf-8'))
        if report['status'] != 'completed': raise ValueError('Wait for all active benchmarks to complete')
        if report['generator']['version'] != 's0-synthetic-v1': raise ValueError('Unknown sampling recipe')
        template_count = report['generator']['template_count']
        if report['actual']['revisions'] % template_count:
            raise ValueError('Partial template cycle needs a different weighted reference')
        data = path.parent/'index/revisions.jsonl'
        digest = hashlib.sha256()
        with data.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''): digest.update(chunk)
        if digest.hexdigest() != report['index']['files']['revisions.jsonl']['sha256']:
            raise ValueError('Persisted benchmark input checksum changed')
        with data.open(encoding='utf-8') as stream:
            templates = [json.loads(next(stream)) for _ in range(template_count)]
        multiplier = report['actual']['revisions']//template_count
        checked = []
        for qid,query in enumerate(report['queries']):
            expected = sum(count(query,r) for r in templates)*multiplier
            actual = {run['total_hits'] for run in report['query_runs'] if run['query_id'] == qid}
            if actual != {expected}: raise AssertionError((path.parent.name,qid,expected,actual))
            checked.append({'query_id':qid,'expected':expected,'observed':expected,'matched':True})
        high = report['high_frequency_gap']
        high_expected = sum(count(high['query'],r) for r in templates)*multiplier
        if high_expected != high['total_hits']: raise AssertionError('High-frequency gap count mismatch')
        results.append({'experiment':path.parent.name,'all_matched':True,'template_count':template_count,
            'repeat_multiplier':multiplier,'input_sha256':digest.hexdigest(),'query_counts':checked,
            'high_frequency_gap':{'expected':high_expected,'observed':high['total_hits']}})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({
        'method':'Brute-force raw template enumeration and documented template repetition arithmetic; no PositionIndex calls',
        'checker_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope':'Counts for the fixed 20-query benchmark and high-frequency pair; coordinate semantics independently checked by 23 hand-written golden cases',
        'experiments':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'experiments':len(results),'ordinary_queries_checked':sum(len(r['query_counts']) for r in results),'high_frequency_queries_checked':len(results),'all_matched':True}))


if __name__ == '__main__': main()
