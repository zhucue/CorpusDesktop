"""Fresh-process full-source checks with a direct SQLite/text/token oracle.

No sample substitution: every source row and persisted token coordinate is read.
The small set of literal/phrase queries is explicit; not a 200-gold acceptance.
"""
import argparse
import json
import platform
import shutil
import sqlite3
import time
from pathlib import Path

from pipelines.query.source_index import TOKEN, digest
from pipelines.query.source_reader import SourceIndexReader

CHARACTERS = ["I", "the", "love", "北京", "哈哈", "😀", "e\u0301", "é", "s3-no-such-phrase-20261016", "endstart"]
TOKENS = [("I",), ("the",), ("love",), ("北京",), ("。",), ("😀",), ("e\u0301",), ("é",), ("I", "am"), ("我", "爱")]


def request(unit, values):
    if unit == "character":
        pattern = {"type": "literal", "value": values}
    else:
        terms = [{"type": "term", "attr": "form", "op": "eq", "value": value} for value in values]
        pattern = terms[0] if len(terms) == 1 else {"type": "sequence", "items": terms}
    return {"dsl_version": "corpus-query/v1", "unit": unit, "within": "sentence", "pattern": pattern,
            "normalization": "none", "overlap": "all"}


def verify(database, directory, output):
    output.mkdir(parents=True, exist_ok=False)
    snapshots = output / 'source'
    snapshots.mkdir()
    source_hashes = {}
    for name in ('source_index_verify.py', 'source_reader.py'):
        path = Path(__file__).with_name(name)
        shutil.copyfile(path, snapshots / name)
        source_hashes[name] = digest(path)
    started = time.monotonic()
    oracle = [{"query": request("character", v), "hits": 0, "sentences": 0, "first50": []} for v in CHARACTERS]
    oracle += [{"query": request("token", v), "hits": 0, "sentences": 0, "first50": []} for v in TOKENS]
    db = sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    report = {"status": "failed", "formal_acceptance": False, "input_sha256": digest(database),
              "reader_manifest_sha256": digest(directory / "manifest.json"), "source_sha256": digest(Path(__file__)),
              "measured_source_sha256": source_hashes,
              "environment": {"platform": platform.platform(), "python": platform.python_version(),
                              "cpu_max": Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
                              "memory_max": Path('/sys/fs/cgroup/memory.max').read_text().strip(),
                              "shared_host": True, "cold_disk": False},
              "scope": "All source rows and all stored token coordinates; 20 explicit exact queries. No sampled index or full S3 acceptance.", "runs": []}
    try:
        with SourceIndexReader(directory, output / "runtime") as reader:
            report['index_identity_sha256'] = reader.manifest['identity_sha256']
            report['recipe_sha256'] = reader.manifest['recipe_sha256']
            observed_tokens, observed_characters = 0, 0
            for ordinal, (sid, language, text) in enumerate(db.execute("SELECT id,language,text FROM sentences ORDER BY id")):
                record = reader.record(ordinal)
                assert record[0] == sid and reader.text(ordinal) == text
                next_token = reader.record(ordinal + 1)[5] if ordinal + 1 < reader.count else reader.manifest["counts"]["tokens"]
                forms, positions, cursor = [], [], 0
                for at in range(record[5], next_token):
                    doc, start, end = TOKEN.unpack_from(reader.maps["tokens.map"], at * TOKEN.size)
                    assert doc == ordinal and cursor <= start < end <= len(text) and not text[cursor:start].strip()
                    forms.append(text[start:end])
                    positions.append((start, end))
                    cursor = end
                assert not text[cursor:].strip()
                observed_tokens += len(forms)
                observed_characters += len(text)
                for index, value in enumerate(CHARACTERS):
                    spans, at = [], 0
                    while (at := text.find(value, at)) != -1:
                        spans.append((at, at + len(value)))
                        at += 1
                    _add(oracle[index], sid, spans)
                for index, words in enumerate(TOKENS, len(CHARACTERS)):
                    spans = [(positions[i][0], positions[i + len(words) - 1][1])
                             for i in range(len(forms) - len(words) + 1) if tuple(forms[i:i + len(words)]) == words]
                    _add(oracle[index], sid, spans)
                if ordinal % 100000 == 0:
                    print(json.dumps({"stage": "independent_full_scan", "sentences": ordinal + 1}), flush=True)
            assert ordinal + 1 == reader.count
            assert observed_tokens == reader.manifest["counts"]["tokens"]
            assert observed_characters == reader.manifest["counts"]["characters"]
            report["full_mapping_check"] = {"sentences": reader.count, "tokens": observed_tokens, "characters": observed_characters}
            for expected in oracle:
                q = expected["query"]
                stamp = time.monotonic()
                page = reader.character_page(q) if q["unit"] == "character" else reader.token_page(q)
                first_page_seconds = time.monotonic() - stamp
                stamp = time.monotonic()
                counts = reader.character_counts(q) if q["unit"] == "character" else reader.token_counts(q)
                count_seconds = time.monotonic() - stamp
                assert page["total_hits"] is None and page["count_state"] == "pending"
                assert counts["total_hits"] == expected["hits"]
                assert counts["matched_segments"] == counts["matched_documents"] == expected["sentences"]
                assert [(h['source_sentence_id'], h['start'], h['end']) for h in page['page']] == expected['first50']
                for hit in page['page']:
                    text = db.execute("SELECT text FROM sentences WHERE id=?", (hit['source_sentence_id'],)).fetchone()[0]
                    assert hit['match'] == text[hit['start']:hit['end']]
                    assert hit['left'] == text[max(0,hit['start']-40):hit['start']]
                    assert hit['right'] == text[hit['end']:hit['end']+40]
                report["runs"].append({**expected, "page_seconds": first_page_seconds, "count_seconds": count_seconds,
                                       "all_counts_spans_kwic_equal": True})
                print(json.dumps({"stage": "query_checked", "unit": q["unit"], "hits": expected["hits"], "page_seconds": first_page_seconds, "count_seconds": count_seconds}), flush=True)
            report["status"] = "passed"
    finally:
        db.close()
        report["wall_seconds"] = time.monotonic() - started
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _add(entry, sid, spans):
    entry["hits"] += len(spans)
    entry["sentences"] += bool(spans)
    entry["first50"].extend((sid, left, right) for left, right in spans[:50 - len(entry["first50"])])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.database, args.index, args.output)
