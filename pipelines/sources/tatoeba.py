"""Bounded full Mandarin/English Tatoeba acquisition and parsing.

Trusted worker API: acquire(directory, checkpoint, expected=None), then
parse(acquisition, new_directory, checkpoint, previous_database=None).
Callbacks receive progress dicts and may raise to stop work. No publication or
license approval happens here. SQLite is a staging artifact, not an API database.
"""
from __future__ import annotations

import bz2
import gzip
import hashlib
import json
import os
import sqlite3
import time
from collections import Counter
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

MIB = 1024 * 1024
FILES = {
    "cmn_sentences_detailed.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/cmn/cmn_sentences_detailed.tsv.bz2",
    "eng_sentences_detailed.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/eng/eng_sentences_detailed.tsv.bz2",
    "cmn-eng_links.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/cmn/cmn-eng_links.tsv.bz2",
}
LICENSE_URLS = {
    "tatoeba-downloads.html": "https://tatoeba.org/en/downloads",
    "tatoeba-attribution.html": "https://en.wiki.tatoeba.org/articles/show/using-the-tatoeba-corpus",
}
RECIPE = "tatoeba-full-cmn-eng-v1"
LIMITS = {"file_bytes": 64 * MIB, "network_bytes": 160 * MIB,
          "download_seconds": 1800, "socket_seconds": 15,
          "expanded_file_bytes": 512 * MIB, "line_bytes": MIB,
          "sentences": 3_000_000, "edges": 2_000_000,
          "parse_seconds": 1200, "output_bytes": 2 * 1024 * MIB}


class SourceError(ValueError):
    """Explicit source failure; caller must not publish artifacts."""

    def __init__(self, message, code="SOURCE_INVALID"):
        super().__init__(message)
        self.code = code


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceError("Official URL redirected; review connector before retry")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_file(path, checkpoint=lambda _: None):
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        while chunk := stream.read(MIB):
            size += len(chunk)
            digest.update(chunk)
            progress(checkpoint, {"phase": "hash", "file": Path(path).name, "bytes": size})
    return size, digest.hexdigest()


def write_json(path, value):
    Path(path).write_bytes(encoded(value) + b"\n")


def progress(callback, event):
    callback({"stage": event.get("stage", event.get("phase")),
              "processed_bytes": event.get("processed_bytes", event.get("bytes", event.get("expanded_bytes", 0))),
              "total_bytes": event.get("total_bytes", event.get("total")),
              "processed_records": event.get("processed_records", event.get("rows", 0)),
              "total_records": event.get("total_records"),
              "file_name": event.get("file_name", event.get("file")),
              **({"expected": event["expected"]} if "expected" in event else {})})


def new_directory(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise SourceError("Attempt directory must be empty; old artifacts are immutable")
    return path


def metadata(response):
    try:
        size = int(response.headers["Content-Length"])
        modified = response.headers["Last-Modified"]
        date = parsedate_to_datetime(modified).astimezone(UTC).date().isoformat()
        etag = response.headers["ETag"]
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceError("Missing or invalid official object identity") from exc
    if not etag or not 0 < size <= LIMITS["file_bytes"]:
        raise SourceError("Official file exceeds limit or has no ETag")
    return {"bytes": size, "etag": etag, "last_modified": modified, "export_date": date}


def acquire(output_dir, checkpoint=lambda _: None, *, expected=None, _opener=None):
    """Download all three mutable official exports, checking identity before/after.

    expected is {filename: {bytes, etag, last_modified, export_date}} from a prior
    acquisition. One network retry per object; identity mismatch never retries.
    Errors persist acquisition-error.json and never return a successful receipt.
    """
    output = new_directory(output_dir)
    opener = _opener or build_opener(NoRedirect())
    started = time.monotonic()
    total = 0
    attempts = []

    def check(event):
        if time.monotonic() - started > LIMITS["download_seconds"]:
            raise SourceError("Acquisition deadline exceeded", "SOURCE_LIMIT_EXCEEDED")
        progress(checkpoint, event)

    def request(url, method="GET", headers=None):
        check({"phase": "download", "network_bytes": total})
        response = opener.open(Request(url, method=method, headers={"User-Agent": "CorpusDesktop/0.1", **(headers or {})}),
                               timeout=LIMITS["socket_seconds"])
        if response.status != 200 or response.geturl() != url:
            response.close()
            raise SourceError("Unexpected HTTP status or redirected URL")
        return response

    def heads():
        result = {}
        for name, url in FILES.items():
            with request(url, "HEAD") as response:
                result[name] = metadata(response)
        if len({item["export_date"] for item in result.values()}) != 1:
            raise SourceError("Weekly export dates differ; no mixed bundle allowed")
        return result

    try:
        before = heads()
        if expected is not None and before != expected:
            raise SourceError("Official version changed from expected acquisition", "SOURCE_VERSION_CHANGED")
        write_json(output / "observed-inputs.json", before)
        check({"stage": "pinned", "expected": before})
        records = []
        for name, url in {**FILES, **LICENSE_URLS}.items():
            pin = before.get(name)
            limit = pin["bytes"] if pin else 2 * MIB
            target = output / name
            for attempt in (1, 2):
                received = 0
                record = {"name": name, "attempt": attempt, "bytes": 0}
                attempts.append(record)
                try:
                    headers = {"If-Match": pin["etag"], "If-Unmodified-Since": pin["last_modified"]} if pin else {}
                    with request(url, headers=headers) as response, target.open("wb") as stream:
                        if pin and metadata(response) != pin:
                            raise SourceError("GET metadata differs from fixed HEAD", "SOURCE_VERSION_CHANGED")
                        while chunk := response.read(64 * 1024):
                            received += len(chunk)
                            total += len(chunk)
                            record["bytes"] = received
                            if received > limit or total > LIMITS["network_bytes"]:
                                raise SourceError("Download byte budget exceeded", "SOURCE_LIMIT_EXCEEDED")
                            stream.write(chunk)
                            check({"phase": "download", "file": name, "bytes": received, "total": limit})
                    if pin and received != pin["bytes"]:
                        raise EOFError("Incomplete HTTP body")
                    record["status"] = "complete"
                    break
                except (URLError, TimeoutError, EOFError, OSError, IncompleteRead) as exc:
                    record["error"] = type(exc).__name__
                    if isinstance(exc, HTTPError) and exc.code == 412:
                        raise SourceError("Official version changed during conditional GET", "SOURCE_VERSION_CHANGED") from exc
                    retryable = not isinstance(exc, HTTPError) or exc.code in (408, 429, 500, 502, 503, 504)
                    if attempt == 2 or not retryable:
                        raise SourceError(f"Official download failed for {name}", "SOURCE_DOWNLOAD_FAILED") from exc
            size, sha = digest_file(target, check)
            records.append({"name": name, "url": url, "path": str(target), "bytes": size,
                            "sha256": sha, **(pin or {})})
        if heads() != before:
            raise SourceError("Official input changed during acquisition", "SOURCE_VERSION_CHANGED")
        result = {"schema": "tatoeba-acquisition/v1", "observed_at": datetime.now(UTC).isoformat(),
                  "files": records[:3], "license_evidence": records[3:], "expected": before,
                  "export_date": next(iter(before.values()))["export_date"],
                  "snapshot_atomicity": "Upstream has no atomic snapshot guarantee; matching before/after metadata is checked",
                  "checksum_basis": "Locally computed SHA256 of acquired bytes; no publisher checksum is claimed",
                  "attempts": attempts, "network_bytes": total}
        write_json(output / "acquisition.json", result)
        return result
    except Exception as exc:
        write_json(output / "acquisition-error.json", {"status": "failed", "error": f"{type(exc).__name__}: {exc}", "attempts": attempts})
        raise


def lines(path, checkpoint, started):
    expanded = 0
    with bz2.open(path, "rb") as stream:
        number = 0
        while raw := stream.readline(LIMITS["line_bytes"] + 1):
            number += 1
            expanded += len(raw)
            if len(raw) > LIMITS["line_bytes"] or expanded > LIMITS["expanded_file_bytes"]:
                raise SourceError("Expanded bytes or line exceeds limit", "SOURCE_LIMIT_EXCEEDED")
            if number % 2000 == 0:
                if time.monotonic() - started > LIMITS["parse_seconds"]:
                    raise SourceError("Parse deadline exceeded", "SOURCE_LIMIT_EXCEEDED")
                checkpoint({"phase": "parse", "file": Path(path).name, "rows": number, "expanded_bytes": expanded})
            yield number, raw.rstrip(b"\r\n").decode("utf-8", errors="strict")


def _id(value):
    if not value.isascii() or not value.isdecimal() or not 0 < int(value) <= 2**63 - 1:
        raise SourceError("Invalid positive sentence ID")
    return int(value)


def _artifact(path, checkpoint, media_type):
    size, sha = digest_file(path, checkpoint)
    return {"name": path.name, "path": str(path), "bytes": size, "sha256": sha, "media_type": media_type}


def parse(acquisition, output_dir, checkpoint=lambda _: None, *, previous_database=None):
    """Parse the FULL two-language corpus and direct edges to bounded disk outputs.

    Same-ID identical rows/reciprocal edges deduplicate; conflicting sentence ID
    fails. Missing-edge endpoints are counted and excluded, never synthesized.
    Equal text under different upstream IDs remains distinct with attribution.
    """
    output = new_directory(output_dir)
    started = time.monotonic()
    rows = {item["name"]: item for item in acquisition["files"]}
    if set(rows) != set(FILES):
        raise SourceError("Exactly three complete official inputs required")
    for name, item in rows.items():
        if item["url"] != FILES[name] or digest_file(item["path"], checkpoint) != (item["bytes"], item["sha256"]):
            raise SourceError("Input identity mismatch")
    database = output / "corpus.sqlite3"
    temp_root = Path(__file__).resolve().parents[2] / "tmp"
    temp_root.mkdir(exist_ok=True)
    configured_temp = Path(os.environ.setdefault("SQLITE_TMPDIR", str(temp_root))).resolve()
    if not configured_temp.is_relative_to(temp_root):
        raise SourceError("SQLite temporary directory must remain in repository tmp")
    configured_temp.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # SQLite's Windows VFS uses GetTempPath, not SQLITE_TMPDIR. Require the
        # dedicated process launcher to configure TMP/TEMP before SQLite opens;
        # never mutate SQLite's global temp_store_directory while threads run.
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetTempPathW(len(buffer), buffer)
        if not 0 < length < len(buffer) or not Path(buffer.value).resolve().is_relative_to(temp_root):
            raise SourceError("Start parser with Windows TMP and TEMP inside repository tmp", "SOURCE_CONFIGURATION_INVALID")
    db = sqlite3.connect(database.as_uri(), uri=True)
    db.execute("PRAGMA temp_store=FILE")
    db.execute("PRAGMA cache_size=-16384")
    db.executescript("""
      CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE sentences(id INTEGER PRIMARY KEY,language TEXT NOT NULL,text TEXT NOT NULL,
        owner TEXT,added TEXT,modified TEXT,record_hash TEXT NOT NULL,text_hash TEXT NOT NULL,source_line INTEGER NOT NULL);
      CREATE TABLE edges(cmn_id INTEGER NOT NULL,eng_id INTEGER NOT NULL,PRIMARY KEY(cmn_id,eng_id));
      CREATE INDEX edges_eng ON edges(eng_id);
    """)
    db.execute("INSERT INTO metadata VALUES('recipe',?)", (RECIPE,))
    quality = Counter({key: 0 for key in ("cmn_input_rows", "eng_input_rows", "cmn_sentences", "eng_sentences", "sentences", "unknown_owner", "duplicate_sentence_rows", "edge_input_rows", "missing_endpoint_rows", "wrong_language_edge_rows", "direct_edges", "duplicate_or_reciprocal_edge_rows")})
    missing_examples = []
    sql_callback_error = []
    last_sql_check = time.monotonic()

    def tick(event):
        if time.monotonic() - started > LIMITS["parse_seconds"]:
            raise SourceError("Parse deadline exceeded", "SOURCE_LIMIT_EXCEEDED")
        if sum(p.stat().st_size for p in output.iterdir() if p.is_file()) > LIMITS["output_bytes"]:
            raise SourceError("Output byte budget exceeded", "SOURCE_LIMIT_EXCEEDED")
        progress(checkpoint, event)

    def sql_progress():
        nonlocal last_sql_check
        if time.monotonic() - last_sql_check >= 1:
            last_sql_check = time.monotonic()
            try:
                tick({"stage": "quality_or_diff"})
            except Exception as exc:  # noqa: BLE001 -- rethrow original callback after SQLite interrupt
                sql_callback_error.append(exc)
                return 1
        return 0

    db.set_progress_handler(sql_progress, 100_000)

    try:
        for lang in ("cmn", "eng"):
            name = f"{lang}_sentences_detailed.tsv.bz2"
            for number, line in lines(rows[name]["path"], tick, started):
                fields = line.split("\t")
                if len(fields) != 6 or fields[1] != lang or not fields[2] or "\x00" in line:
                    raise SourceError(f"Invalid detailed row: {name}:{number}")
                ident = _id(fields[0])
                owner, added, modified = (None if x in ("", "\\N") else x for x in fields[3:])
                values = (ident, lang, fields[2], owner, added, modified)
                hashed = hashlib.sha256(encoded(values)).hexdigest()
                previous = db.execute("SELECT record_hash FROM sentences WHERE id=?", (ident,)).fetchone()
                quality[f"{lang}_input_rows"] += 1
                if previous:
                    if previous[0] != hashed:
                        raise SourceError(f"Conflicting sentence ID {ident}")
                    quality["duplicate_sentence_rows"] += 1
                    continue
                db.execute("INSERT INTO sentences VALUES(?,?,?,?,?,?,?,?,?)", (*values, hashed, hashlib.sha256(fields[2].encode()).hexdigest(), number))
                quality[f"{lang}_sentences"] += 1
                quality["sentences"] += 1
                quality["unknown_owner"] += int(owner is None)
                if quality["sentences"] > LIMITS["sentences"]:
                    raise SourceError("Sentence limit exceeded", "SOURCE_LIMIT_EXCEEDED")
                if number % 10000 == 0:
                    db.commit()
        db.commit()
        for number, line in lines(rows["cmn-eng_links.tsv.bz2"]["path"], tick, started):
            fields = line.split("\t")
            if len(fields) != 2:
                raise SourceError("Invalid direct link row")
            a, b = map(_id, fields)
            quality["edge_input_rows"] += 1
            if number > LIMITS["edges"]:
                raise SourceError("Edge input limit exceeded", "SOURCE_LIMIT_EXCEEDED")
            languages = dict(db.execute("SELECT id,language FROM sentences WHERE id IN (?,?)", (a, b)))
            if a not in languages or b not in languages:
                quality["missing_endpoint_rows"] += 1
                if len(missing_examples) < 20:
                    missing_examples.append([a, b])
                continue
            if {languages[a], languages[b]} != {"cmn", "eng"}:
                quality["wrong_language_edge_rows"] += 1
                continue
            pair = (a, b) if languages[a] == "cmn" else (b, a)
            count = db.execute("INSERT OR IGNORE INTO edges VALUES(?,?)", pair).rowcount
            quality["direct_edges"] += count
            quality["duplicate_or_reciprocal_edge_rows"] += 1 - count
        db.commit()
        quality["same_text_distinct_ids"] = db.execute("SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM sentences GROUP BY language,text HAVING COUNT(*)>1)").fetchone()[0]
        quality["unlinked_sentences"] = db.execute("SELECT COUNT(*) FROM sentences s WHERE NOT EXISTS(SELECT 1 FROM edges e WHERE e.cmn_id=s.id OR e.eng_id=s.id)").fetchone()[0]
        diff = {"baseline": None, "status": "initial", "sentence_added": quality["sentences"], "sentence_removed": 0,
                "sentence_changed": 0, "text_changed": 0, "edge_added": quality["direct_edges"], "edge_removed": 0}
        if previous_database is not None:
            previous_database = Path(previous_database).resolve()
            previous_sha = digest_file(previous_database, tick)[1]
            db.execute("ATTACH DATABASE ? AS previous", (previous_database.as_uri() + "?mode=ro",))
            if db.execute("SELECT value FROM previous.metadata WHERE key='recipe'").fetchone() != (RECIPE,):
                raise SourceError("Incompatible previous parsed corpus")
            diff.update(baseline=previous_sha, status="compared")
            for label, table, predicate in [
                ("sentence_added", "sentences n", "NOT EXISTS(SELECT 1 FROM previous.sentences p WHERE p.id=n.id)"),
                ("sentence_removed", "previous.sentences p", "NOT EXISTS(SELECT 1 FROM sentences n WHERE n.id=p.id)"),
                ("sentence_changed", "sentences n JOIN previous.sentences p USING(id)", "n.record_hash<>p.record_hash"),
                ("text_changed", "sentences n JOIN previous.sentences p USING(id)", "n.text_hash<>p.text_hash"),
                ("edge_added", "edges n", "NOT EXISTS(SELECT 1 FROM previous.edges p WHERE p.cmn_id=n.cmn_id AND p.eng_id=n.eng_id)"),
                ("edge_removed", "previous.edges p", "NOT EXISTS(SELECT 1 FROM edges n WHERE n.cmn_id=p.cmn_id AND n.eng_id=p.eng_id)"),
            ]:
                tick({"phase": "diff", "metric": label})
                diff[label] = db.execute(f"SELECT COUNT(*) FROM {table} WHERE {predicate}").fetchone()[0]
        for name, query, make in [
            ("sentences.jsonl.gz", "SELECT id,language,text,owner,added,modified,record_hash,source_line FROM sentences ORDER BY id", lambda r: {"id": r[0], "language": r[1], "text": r[2], "owner": r[3], "added": r[4], "modified": r[5], "record_sha256": r[6], "source_line": r[7], "sentence_url": f"https://tatoeba.org/en/sentences/show/{r[0]}", "license": "CC-BY-2.0-FR", "modifications": []}),
            ("direct_edges.jsonl.gz", "SELECT cmn_id,eng_id FROM edges ORDER BY cmn_id,eng_id", lambda r: {"cmn_id": r[0], "eng_id": r[1], "relation": "upstream_direct_link"}),
        ]:
            with (output / name).open("wb") as target, gzip.GzipFile(fileobj=target, mode="wb", filename="", mtime=0) as compressed:
                for number, record in enumerate(db.execute(query), 1):
                    compressed.write(encoded(make(record)) + b"\n")
                    if number % 2000 == 0:
                        tick({"phase": "export", "file": name, "rows": number})
        db.close()
        quality_report = {**dict(quality), "missing_endpoint_examples": missing_examples,
                          "policy": "Full language exports; distinct IDs retained even for equal text; missing/wrong-language edges excluded explicitly"}
        write_json(output / "quality.json", quality_report)
        write_json(output / "diff.json", diff)
        license_record = {"declared": "CC-BY-2.0-FR", "cc0_subset_assumed": False,
                          "attribution": "Tatoeba contributors; sentence owner and original sentence URL retained; owner is not claimed to be original author",
                          "release_approved": False, "model_egress": "not_approved",
                          "evidence": [{k: v for k, v in row.items() if k != "path"} for row in acquisition.get("license_evidence", [])]}
        write_json(output / "license.json", license_record)
        write_json(output / "acquisition.json", {k: v for k, v in acquisition.items() if k not in ("files", "license_evidence")} | {
            "files": [{k: v for k, v in row.items() if k != "path"} for row in acquisition["files"]],
            "license_evidence": license_record["evidence"]})
        artifacts = [_artifact(path, tick, "application/gzip" if path.suffix == ".gz" else "application/vnd.sqlite3" if path.suffix == ".sqlite3" else "application/json") for path in sorted(output.iterdir()) if path.is_file()]
        for row in [*acquisition["files"], *acquisition.get("license_evidence", [])]:
            artifact = _artifact(Path(row["path"]), tick, "text/html" if row["name"].endswith(".html") else "application/octet-stream")
            if (artifact["bytes"], artifact["sha256"]) != (row["bytes"], row["sha256"]):
                raise SourceError("Acquired artifact changed during parse")
            artifacts.append(artifact)
        identity = {name: rows[name]["sha256"] for name in sorted(rows)}
        manifest = {"schema": "tatoeba-full-bundle/v1", "source_id": "D12", "recipe": RECIPE,
                    "input_identity": hashlib.sha256(encoded(identity)).hexdigest(), "inputs": [{k: v for k, v in rows[name].items() if k != "path"} for name in sorted(rows)],
                    "export_date": acquisition["export_date"], "scope": "all cmn and eng sentences plus all eligible direct cmn-eng links; not a sample",
                    "stage": "VALIDATED", "published": False, "query_ready": False,
                    "quality": quality_report, "diff": diff, "license": license_record,
                    "limits": LIMITS, "snapshot_atomicity": acquisition.get("snapshot_atomicity"),
                    "checksum_basis": "Acquired-byte SHA256; no publisher checksum is claimed",
                    "artifacts": [{k: v for k, v in item.items() if k != "path"} for item in artifacts]}
        manifest_path = output / "manifest.json"
        write_json(manifest_path, manifest)
        artifacts.append(_artifact(manifest_path, tick, "application/json"))
        tick({"phase": "validated", "sentences": quality["sentences"], "direct_edges": quality["direct_edges"]})
        return {"manifest": manifest, "manifest_path": manifest_path, "artifacts": artifacts}
    except Exception as exc:
        db.close()
        write_json(output / "parse-error.json", {"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        if sql_callback_error:
            raise sql_callback_error[0] from exc
        raise
