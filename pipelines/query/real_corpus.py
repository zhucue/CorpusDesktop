"""Offline, bounded S0 CoNLL-U -> canonical coordinates -> real CWB experiment.

This is a functional probe, not a published source or a production importer.
Each revision retains one exact upstream # text value, never a token join.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from pipelines.query.cwb import cqp_counts, cqp_page_spans, cqp_spans
from pipelines.query.cwb_benchmark import Coordinates
from pipelines.query.cwb_paged import page_result
from pipelines.query.engine import QueryError

ROOT = Path(__file__).resolve().parents[2]
ATTRIBUTES = frozenset({"form", "lemma", "upos"})
PINS = {
    "gum": {
        "path": "tmp/sources-s0/20261016-gum/en_gum-ud-test.conllu",
        "manifest": "tmp/sources-s0/20261016-gum/manifest.json",
        "manifest_key": "gum",
        "repository": "UD_English-GUM",
        "commit": "b58e74bc22d17220c9198864c253a50a897bf27f",
        "sha256": "cd96a285e7339f401f4803dd0f4f61109c51692e3ef6f9186a1f977544080b69",
        "git_blob_sha1": "a47fd4ac175fd3e818568b8c51429712b94ae04f",
        "source_document_boundaries": "explicit_newdoc",
        "matched_documents_unit": "upstream_newdoc_document",
    },
    "gsd": {
        "path": "tmp/sources-s0/20261016-ud/zh_gsd-ud-test.conllu",
        "manifest": "tmp/sources-s0/20261016-ud/manifest.json",
        "manifest_key": "ud",
        "repository": "UD_Chinese-GSD",
        "commit": "e0d85a020182e264d6384be2a59c0f4879a1cc35",
        "sha256": "ff01a3d01d62b623756396085e78bdaeefb7c2b7935a890dde5b18e92712d54f",
        "git_blob_sha1": "3b15be45a96edcb21736f220e73fdccade231ca5",
        "source_document_boundaries": "unavailable",
        "matched_documents_unit": "imported_sentence_record",
    },
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def blocks(raw):
    """Yield raw byte anchors and original lines, including every nonempty block."""
    offset, start, lines = 0, 0, []
    for line in raw.splitlines(keepends=True):
        if line.strip():
            if not lines:
                start = offset
            lines.append(line.decode("utf-8").rstrip("\r\n"))
        elif lines:
            yield start, offset, lines
            lines = []
        offset += len(line)
    if lines:
        yield start, offset, lines


def map_sentence(lines):
    """Accept only complete, unambiguous surface mapping; return structured rejection."""
    metadata = {}
    rows = []
    for line in lines:
        if line.startswith("# "):
            key, sep, value = line[2:].partition(" = ")
            if sep:
                if key in {"sent_id", "text", "newdoc id"} and key in metadata:
                    raise ValueError("duplicate_metadata:" + key)
                metadata[key] = value
        elif not line.startswith("#"):
            row = line.split("\t")
            if len(row) != 10 or any(not field for field in row):
                raise ValueError("invalid_ten_column_row")
            rows.append(row)
    if not metadata.get("sent_id") or not metadata.get("text"):
        raise ValueError("missing_sent_id_or_text")
    words = [row for row in rows if re.fullmatch(r"[1-9]\d*", row[0])]
    ranges = [row for row in rows if re.fullmatch(r"[1-9]\d*-[1-9]\d*", row[0])]
    empty = [row for row in rows if re.fullmatch(r"[0-9]+\.[1-9]\d*", row[0])]
    if len(words) + len(ranges) + len(empty) != len(rows):
        raise ValueError("invalid_row_id")
    if not words or [int(row[0]) for row in words] != list(range(1, len(words) + 1)):
        raise ValueError("nonsequential_word_ids")
    if len({row[0] for row in rows}) != len(rows):
        raise ValueError("duplicate_row_id")
    text = metadata["text"]
    cursor = 0
    tokens = []
    for row in words:
        if row[1] == "_":
            raise ValueError("missing_surface_form")
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if not text.startswith(row[1], cursor):
            raise ValueError("form_text_mismatch:" + row[0])
        end = cursor + len(row[1])
        tokens.append(
            {
                "id": row[0],
                "start": cursor,
                "end": end,
                "attrs": {"form": row[1], "lemma": row[2], "upos": row[3]},
            }
        )
        cursor = end
    if text[cursor:].strip():
        raise ValueError("unmapped_text_suffix")
    covered = set()
    for row in ranges:
        left, right = map(int, row[0].split("-"))
        ids = set(range(left, right + 1))
        if left >= right or right > len(words) or ids & covered:
            raise ValueError("invalid_or_overlapping_mwt:" + row[0])
        if "".join(words[i - 1][1] for i in range(left, right + 1)) != row[1]:
            raise ValueError("nonconcatenative_mwt:" + row[0])
        if text[tokens[left - 1]["start"] : tokens[right - 1]["end"]] != row[1]:
            raise ValueError("mwt_text_mismatch:" + row[0])
        covered.update(ids)
    return {
        "metadata": metadata,
        "text": text,
        "tokens": tokens,
        "multiword_rows": ranges,
        "empty_node_rows": empty,
    }


def import_conllu(raw, source, document_mode):
    if document_mode not in {"explicit_newdoc", "unavailable"}:
        raise ValueError("invalid document mode")
    accepted, ledger, seen_ids, seen_docs = [], [], set(), set()
    current_doc = None
    source_sha = hashlib.sha256(raw).hexdigest()
    for ordinal, (start, end, lines) in enumerate(blocks(raw)):
        sid = next(
            (line[12:] for line in lines if line.startswith("# sent_id = ")), None
        )
        newdoc = [line[14:] for line in lines if line.startswith("# newdoc id = ")]
        entry = {
            "block_ordinal": ordinal,
            "sent_id": sid,
            "raw_byte_start": start,
            "raw_byte_end": end,
            "raw_block_sha256": hashlib.sha256(raw[start:end]).hexdigest(),
            "status": "rejected",
            "reason": None,
        }
        try:
            if newdoc:
                if document_mode == "unavailable" or len(newdoc) != 1:
                    raise ValueError("unexpected_document_boundary")
                current_doc = newdoc[0]
                if not current_doc or current_doc in seen_docs:
                    raise ValueError("duplicate_or_empty_document_id")
                seen_docs.add(current_doc)
            if document_mode == "explicit_newdoc" and not current_doc:
                raise ValueError("missing_document_boundary")
            if sid in seen_ids:
                raise ValueError("duplicate_sentence_id")
            seen_ids.add(sid)
            record = map_sentence(lines)
            if source == "gum" and "reddit" in (current_doc or "").lower():
                raise ValueError("reddit_text_not_qualified")
            record.update(
                {
                    "revision_id": source + ":" + sid,
                    "document_id": current_doc
                    if document_mode == "explicit_newdoc"
                    else source + ":record:" + sid,
                    "source_sha256": source_sha,
                    "raw_byte_start": start,
                    "raw_byte_end": end,
                    "raw_lines": lines,
                    "block_ordinal": ordinal,
                }
            )
            accepted.append(record)
            entry["status"] = "accepted"
        except ValueError as error:
            entry["reason"] = str(error)
        ledger.append(entry)
    stats = {
        "input_blocks": len(ledger),
        "accepted_sentences": len(accepted),
        "rejected_sentences": len(ledger) - len(accepted),
        "syntactic_word_tokens": sum(len(r["tokens"]) for r in accepted),
        "canonical_codepoints": sum(len(r["text"]) for r in accepted),
        "imported_document_units": len({r["document_id"] for r in accepted}),
        "multiword_rows_retained": sum(len(r["multiword_rows"]) for r in accepted),
        "empty_node_rows_retained_not_indexed": sum(
            len(r["empty_node_rows"]) for r in accepted
        ),
        "source_document_boundaries": document_mode,
        "rejections_by_reason": dict(
            Counter(e["reason"] for e in ledger if e["reason"])
        ),
    }
    return accepted, ledger, stats


def write_index_input(target, records, ledger):
    """Numbered VRT (-n) preserves literal XML/entity-like token values unchanged."""
    if not records:
        raise ValueError("NO_MAPPABLE_SENTENCES")
    target.mkdir(parents=True, exist_ok=True)
    missing = {
        attr: sum(
            token["attrs"][attr] == "_"
            for record in records
            for token in record["tokens"]
        )
        for attr in ATTRIBUTES
    }
    save(
        target / "attribute-availability.json",
        {
            "missing_values": missing,
            "available_attributes": sorted(
                attr for attr in ATTRIBUTES if not missing[attr]
            ),
            "policy": "An attribute missing on any selected syntactic word is unavailable for the entire material scope.",
        },
    )
    with (
        (target / "input.vrt").open("w", encoding="utf-8", newline="\n") as vrt,
        (target / "tokens.map").open("wb") as mapping,
        (target / "revisions.jsonl").open("wb") as texts,
        (target / "revision-offsets.map").open("wb") as offsets,
    ):
        previous_doc = None
        for ordinal, record in enumerate(records):
            if record["document_id"] != previous_doc:
                if previous_doc is not None:
                    vrt.write("</doc>\n")
                vrt.write("<doc>\n")
                previous_doc = record["document_id"]
            vrt.write("<s>\n")
            for token in record["tokens"]:
                values = [token["attrs"][key] for key in ("form", "lemma", "upos")]
                if any(any(c in value for c in "\t\r\n\x00") for value in values):
                    raise ValueError("invalid_vrt_attribute_control_character")
                vrt.write(token["id"] + "\t" + "\t".join(values) + "\n")
                mapping.write(
                    struct.pack("<III", ordinal, token["start"], token["end"])
                )
            vrt.write("</s>\n")
            offsets.write(struct.pack("<Q", texts.tell()))
            texts.write((json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
        vrt.write("</doc>\n")
    with (target / "import-ledger.jsonl").open("w", encoding="utf-8") as output:
        for entry in ledger:
            output.write(json.dumps(entry, ensure_ascii=False) + "\n")


def build_index(target):
    data, registry = target / "data", target / "registry"
    data.mkdir()
    registry.mkdir()
    commands = [
        [
            "cwb-encode",
            "-n",
            "-d",
            str(data),
            "-c",
            "utf8",
            "-f",
            str(target / "input.vrt"),
            "-R",
            str(registry / "s0"),
            "-P",
            "lemma",
            "-P",
            "upos",
            "-S",
            "s",
            "-S",
            "doc",
        ],
        ["cwb-makeall", "-r", str(registry), "-V", "S0"],
    ]
    observations = []
    for number, command in enumerate(commands):
        started = time.perf_counter()
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
        (target / f"build-{number}.log").write_text(
            result.stdout + result.stderr, encoding="utf-8"
        )
        observations.append(
            {
                "command": command,
                "seconds": time.perf_counter() - started,
                "exit_code": result.returncode,
            }
        )
        result.check_returncode()
    return observations


def verify_roundtrip(target, raw_path, selected_blocks):
    from pipelines.query.real_reference import raw_attributes

    command = [
        "cwb-decode",
        "-C",
        "-n",
        "-r",
        str(target / "registry"),
        "S0",
        "-P",
        "word",
        "-P",
        "lemma",
        "-P",
        "upos",
    ]
    decoded = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=30,
    )
    actual = [
        line.split("\t") for line in decoded.stdout.removesuffix("\n").split("\n")
    ]
    expected = raw_attributes(raw_path, selected_blocks)
    assert len(actual) == len(expected), (
        "CWB token count differs from raw selected words"
    )
    for position, (got, want) in enumerate(zip(actual, expected, strict=True)):
        assert got == [str(position), *want], (
            f"CWB attribute roundtrip mismatch at {position}"
        )
    artifact = target / "decoded-attributes.tsv"
    artifact.write_text(decoded.stdout, encoding="utf-8", newline="\n")
    return {
        "command": command,
        "decoded_tokens": len(actual),
        "expected_raw_tokens": len(expected),
        "all_word_lemma_upos_equal": True,
        "continuous_global_positions": True,
        "decoded_sha256": digest(artifact),
        "underscore_retained_as_missing_attribute_only": True,
    }


def term(attr, value):
    return {"type": "term", "attr": attr, "op": "eq", "value": value}


def request(pattern):
    return {
        "dsl_version": "corpus-query/v1",
        "unit": "token",
        "within": "sentence",
        "overlap": "all",
        "pattern": pattern,
    }


def workload(source):
    noun, verb = term("upos", "NOUN"), term("upos", "VERB")
    word = term("form", "the" if source == "gum" else "的")
    unicode_word = term("form", "’" if source == "gum" else "。")
    pair = {"type": "sequence", "items": [noun, noun]}
    gap = {
        "type": "sequence",
        "items": [noun, {"type": "gap", "min": 0, "max": 2}, verb],
    }
    two_gaps = {
        "type": "sequence",
        "items": [
            noun,
            {"type": "gap", "min": 0, "max": 1},
            verb,
            {"type": "gap", "min": 0, "max": 2},
            noun,
        ],
    }
    values = [
        ("form", word),
        ("unicode", unicode_word),
        ("lemma", term("lemma", "be" if source == "gum" else "是")),
        ("upos_noun", noun),
        ("upos_verb", verb),
        ("phrase", pair),
        ("bounded_gap", gap),
        ("two_bounded_gaps", two_gaps),
        ("or_duplicate", {"type": "any_of", "patterns": [noun, noun]}),
        ("or_nested_endpoints", {"type": "any_of", "patterns": [noun, pair, noun]}),
        ("empty", term("form", "S0_ABSENT_9e18092c")),
    ]
    return [{"id": name, "query": request(pattern)} for name, pattern in values]


def verify(target, raw_path, source):
    from pipelines.query.real_reference import raw_reference

    ledger = [
        json.loads(line)
        for line in (target / "import-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    selected = {row["block_ordinal"] for row in ledger if row["status"] == "accepted"}
    roundtrip = verify_roundtrip(target, raw_path, selected)
    observations = []
    coordinates = Coordinates(target)
    availability = json.loads(
        (target / "attribute-availability.json").read_text(encoding="utf-8")
    )
    options = {
        "allowed_attributes": frozenset(availability["available_attributes"]),
        "timeout": 30,
    }
    try:
        for entry in workload(source):
            query = entry["query"]
            if entry["id"] == "lemma" and "lemma" not in options["allowed_attributes"]:
                for call in (
                    lambda query=query: page_result(
                        query, target / "registry", coordinates, **options
                    ),
                    lambda query=query: cqp_counts(
                        query, target / "registry", document_attribute="doc", **options
                    ),
                ):
                    try:
                        call()
                    except QueryError as error:
                        assert str(error) == "ATTRIBUTE_UNAVAILABLE"
                    else:
                        raise AssertionError("missing lemma was queried")
                observations.append(
                    {
                        **entry,
                        "status": "rejected",
                        "error": "ATTRIBUTE_UNAVAILABLE",
                        "missing_values": availability["missing_values"]["lemma"],
                    }
                )
                continue
            expected = raw_reference(
                raw_path,
                source,
                PINS[source]["source_document_boundaries"],
                selected,
                query,
            )
            started = time.perf_counter()
            page = page_result(query, target / "registry", coordinates, **options)
            page_seconds = time.perf_counter() - started
            started = time.perf_counter()
            counts = cqp_counts(
                query, target / "registry", document_attribute="doc", **options
            )
            count_seconds = time.perf_counter() - started
            complete = cqp_spans(query, target / "registry", **options)
            second = cqp_page_spans(query, target / "registry", offset=50, **options)
            assert page["spans"] == expected["spans"][:50], entry["id"] + ": spans"
            assert page["page"] == expected["page"], entry["id"] + ": KWIC"
            assert counts == expected["counts"], entry["id"] + ": counts"
            assert sorted(complete) == expected["spans"], (
                entry["id"] + ": complete enumeration"
            )
            assert second == expected["spans"][50:100], entry["id"] + ": page 2"
            assert all(page[key] is None for key in counts)
            observations.append(
                {
                    **entry,
                    "counts": counts,
                    "first_page_rows": len(page["page"]),
                    "first_page_sha256": hashlib.sha256(
                        json.dumps(
                            page["page"], ensure_ascii=False, sort_keys=True
                        ).encode()
                    ).hexdigest(),
                    "full_spans_sha256": hashlib.sha256(
                        json.dumps(expected["spans"]).encode()
                    ).hexdigest(),
                    "first_page_seconds": page_seconds,
                    "exact_count_seconds": count_seconds,
                    "first_50_kwic_equal": True,
                    "full_spans_equal": True,
                    "exact_three_counts_equal": True,
                    "second_page_equal": True,
                    "pending_counts_are_null": True,
                }
            )
        return {
            "pid": os.getpid(),
            "status": "passed",
            "queries": observations,
            "attribute_availability": availability,
            "attribute_roundtrip": roundtrip,
            "scheduling": "sequential functional checks; no concurrency or capacity claim",
        }
    finally:
        coordinates.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reopen", choices=PINS)
    args = parser.parse_args()
    target = args.output.resolve()
    if not target.is_relative_to((ROOT / "tmp").resolve()):
        parser.error("experiment outputs must be under repository tmp")
    if args.reopen:
        result = verify(target, ROOT / PINS[args.reopen]["path"], args.reopen)
        save(target / "reopened.json", result)
        print(
            json.dumps(
                {
                    "source": args.reopen,
                    "reopen": result["status"],
                    "pid": result["pid"],
                }
            ),
            flush=True,
        )
        return
    target.mkdir(parents=True, exist_ok=False)
    snapshot = target / "source"
    snapshot.mkdir()
    sources = [
        "pipelines/query/real_corpus.py",
        "pipelines/query/real_reference.py",
        "pipelines/query/cwb.py",
        "pipelines/query/cwb_paged.py",
        "pipelines/query/cwb_benchmark.py",
        "contracts/semantics.py",
        "contracts/schemas/corpus-query.schema.json",
        "tests/query/test_real_corpus.py",
    ]
    source_hashes = {}
    for name in sources:
        destination = snapshot / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
        source_hashes[name] = digest(destination)
    report = {
        "schema": "s0-real-corpus/v1",
        "formal_acceptance": False,
        "scope": "real fixed UD test splits; functional/readiness only; no replication",
        "publication_state": "NOT_PUBLISHED",
        "model_egress": "not_approved; no model calls",
        "network_mode": "offline local files and local CWB subprocesses",
        "cwb_version": subprocess.run(
            ["cqp", "-v"], capture_output=True, text=True, check=True
        ).stdout.strip(),
        "parent_pid": os.getpid(),
        "source_hashes": source_hashes,
        "sources": {},
    }
    for source, pin in PINS.items():
        path = ROOT / pin["path"]
        raw = path.read_bytes()
        manifest = json.loads((ROOT / pin["manifest"]).read_text(encoding="utf-8"))[
            "sources"
        ][pin["manifest_key"]]
        assert digest(path) == pin["sha256"] == manifest["sample_sha256"]
        assert pin["commit"] == manifest["commit"]
        assert (
            hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            == pin["git_blob_sha1"]
        )
        records, ledger, stats = import_conllu(
            raw, source, pin["source_document_boundaries"]
        )
        work = target / source
        write_index_input(work, records, ledger)
        build = build_index(work)
        initial = verify(work, path, source)
        command = [
            sys.executable,
            "-m",
            "pipelines.query.real_corpus",
            "--output",
            str(work),
            "--reopen",
            source,
        ]
        subprocess.run(command, check=True, timeout=180, cwd=ROOT)
        reopened = json.loads((work / "reopened.json").read_text(encoding="utf-8"))
        assert reopened["pid"] != os.getpid()
        for left, right in zip(initial["queries"], reopened["queries"], strict=True):
            if left.get("status") == "rejected":
                assert left == right
                continue
            for key in ("counts", "first_page_sha256", "full_spans_sha256"):
                assert left[key] == right[key]
        files = {
            str(p.relative_to(work)): {"bytes": p.stat().st_size, "sha256": digest(p)}
            for p in work.rglob("*")
            if p.is_file()
        }
        report["sources"][source] = {
            "pin": pin,
            "import": stats,
            "build": build,
            "initial": initial,
            "fresh_python_reopen": reopened,
            "cache_eviction_performed": False,
            "artifacts": files,
        }
        save(target / "report.json", report)
        print(
            json.dumps({"source": source, "status": "passed", "import": stats}),
            flush=True,
        )
    report["status"] = "passed"
    save(target / "report.json", report)


if __name__ == "__main__":
    main()
