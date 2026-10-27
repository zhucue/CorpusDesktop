"""One bounded recovery experiment for the fixed October 2026 English shard."""
import argparse
import hashlib
import http.client
import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from .probe import MIB, ROOT, parse_sha256sums, write_json
from .wiki_shard import (
    BASE,
    MAXIMUM,
    NAME,
    file_sha256,
    response_headers,
    verify_sample,
)

OLD = ROOT / "tmp/sources-s0/20261016-enwiki-sample"
DEFAULT = ROOT / "tmp/sources-s0/20261016-enwiki-ranges"
CHUNK = 64 * MIB
TOTAL = 2_154_933_323
DEADLINE = 21600
SEGMENT_DEADLINE = 900


class VersionMismatch(ValueError):
    pass


def validate_response(status, headers, start, end, expected):
    wanted = {"Content-Range": f"bytes {start}-{end}/{TOTAL}", "Content-Length": str(end - start + 1),
              "ETag": expected["etag"], "Last-Modified": expected["last-modified"]}
    if status != 206 or any(headers.get(k) != value for k, value in wanted.items()):
        raise VersionMismatch("range status, byte positions, total length or version mismatch")


def read_body(response, path, size, state, attempt, started, clock=time.monotonic):
    h = hashlib.sha256()
    with path.open("xb") as stream:
        while attempt["bytes"] < size:
            if clock() - started > SEGMENT_DEADLINE or clock() > state["deadline_monotonic"]:
                raise TimeoutError("range or experiment deadline exceeded")
            chunk = response.read(min(MIB, size - attempt["bytes"]))
            if not chunk:
                raise OSError("incomplete range body")
            state["network_bytes_received"] += len(chunk)
            attempt["bytes"] += len(chunk)
            stream.write(chunk)
            h.update(chunk)
        extra = response.read(1)
        state["network_bytes_received"] += len(extra)
        if extra:
            raise VersionMismatch("range body exceeds advertised length")
    attempt["sha256"] = h.hexdigest()


def acquire_segment(output, state, start, end, opener=urllib.request.urlopen):
    size = end - start + 1
    for number in range(2):
        if state["network_bytes_received"] + size + 1 > MAXIMUM or time.monotonic() > state["deadline_monotonic"]:
            raise ValueError("remaining experiment network/time budget insufficient")
        attempt = {"start": start, "end_inclusive": end, "attempt": number + 1, "bytes": 0,
                   "status": "requesting", "started_at": datetime.now(UTC).isoformat()}
        path = output / f"range-{start}-{end}-attempt-{number + 1}.part"
        attempt["local_file"] = str(path.relative_to(ROOT))
        state["attempts"].append(attempt)
        write_json(output / "range-state.json", state)
        request = urllib.request.Request(BASE + NAME, headers={"Range": f"bytes={start}-{end}",
            "If-Range": state["validators"]["etag"], "User-Agent": "CorpusDesktop-S0-source-qualification/0.1"})
        try:
            started = time.monotonic()
            with opener(request, timeout=60) as response:
                attempt.update(http_status=response.status, response_headers=dict(response.headers))
                if response.geturl() != BASE + NAME:
                    raise VersionMismatch("unexpected response URL")
                validate_response(response.status, response.headers, start, end, state["validators"])
                read_body(response, path, size, state, attempt, started)
            attempt["status"] = "range_received_unverified"
            state["segments"].append(attempt.copy())
            return
        except VersionMismatch as exc:
            attempt.update(status="rejected", error=str(exc))
            raise
        except (OSError, urllib.error.URLError, http.client.IncompleteRead) as exc:
            attempt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            if isinstance(exc, urllib.error.HTTPError) and exc.code < 500:
                raise
            if number == 1:
                raise
        finally:
            attempt["finished_at"] = datetime.now(UTC).isoformat()
            if path.exists() and "sha256" not in attempt:
                attempt["sha256"] = file_sha256(path)
            write_json(output / "range-state.json", state)
            print(json.dumps({k: attempt.get(k) for k in ("start", "end_inclusive", "attempt", "status", "bytes", "error")}), flush=True)


def download(output):
    if (output / "range-state.json").exists():
        raise ValueError("existing run found; this experiment does not automatically restart")
    old = json.loads((OLD / "transfer.json").read_text())
    tail = json.loads((OLD / "resume.json").read_text())
    headers = response_headers(output / "head.txt")
    original = response_headers(OLD / "headers.txt")
    if not (output / "head.txt").read_text().startswith("HTTP/1.1 200"):
        raise VersionMismatch("HEAD did not return 200")
    if any(headers.get(k) != original.get(k) for k in ("etag", "last-modified", "content-length")):
        raise VersionMismatch("current HEAD differs from initial version")
    if int(headers["content-length"]) != TOTAL or headers["etag"].startswith("W/"):
        raise VersionMismatch("unexpected total or weak ETag")
    sums = (output / "SHA256SUMS").read_bytes()
    selected = next(row for row in parse_sha256sums(sums, BASE, "enwiki", "2026-10-01") if row["name"] == NAME)
    if selected != old["file"] or old["status"] != "failed" or tail["status"] != "failed":
        raise VersionMismatch("old evidence is not the same failed fixed shard")
    if tail["url"] != selected["url"] or tail["etag"] != headers["etag"] or tail["last_modified"] != headers["last-modified"]:
        raise VersionMismatch("tail version mismatch")
    if tail["response_headers"]["Content-Range"] != f"bytes {tail['offset']}-{TOTAL - 1}/{TOTAL}":
        raise VersionMismatch("old tail range does not follow original partial")
    parts = [(OLD / (NAME + ".partial"), 0, tail["offset"]),
             (OLD / (NAME + ".tail"), tail["offset"], tail["bytes"])]
    prefixes = []
    for path, start, size in parts:
        if path.stat().st_size != size or size <= 0:
            raise ValueError("old prefix file size mismatch")
        prefixes.append({"start": start, "end_inclusive": start + size - 1, "bytes": size,
                         "local_file": str(path.relative_to(ROOT)), "sha256": file_sha256(path),
                         "status": "reused_unverified_prefix", "original_response": "HTTP 200 partial" if start == 0 else tail["response_headers"]})
    state = {"schema": "fixed-shard-range-recovery/v1", "status": "downloading", "file": selected,
             "validators": headers, "prefixes": prefixes, "segments": [], "attempts": [],
             "network_bytes_received": len(sums), "network_byte_limit": MAXIMUM,
             "segment_bytes": CHUNK, "maximum_attempts_per_segment": 2,
             "deadline_seconds": DEADLINE, "segment_deadline_seconds": SEGMENT_DEADLINE,
             "socket_timeout_seconds": 60, "deadline_monotonic": time.monotonic() + DEADLINE,
             "started_at": datetime.now(UTC).isoformat(), "publisher_checksum_verified": False,
             "checksum_manifest_sha256": hashlib.sha256(sums).hexdigest(),
             "historical_failure_evidence": "pipelines/sources/enwiki-transfer-evidence.json"}
    write_json(output / "range-state.json", state)
    try:
        for start in range(sum(p["bytes"] for p in prefixes), TOTAL, CHUNK):
            acquire_segment(output, state, start, min(start + CHUNK, TOTAL) - 1)
        state["status"] = "all_ranges_received_unverified"
    except Exception as exc:
        state.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        state["finished_at"] = datetime.now(UTC).isoformat()
        write_json(output / "range-state.json", state)


def assemble(output):
    state = json.loads((output / "range-state.json").read_text())
    if state["status"] != "all_ranges_received_unverified":
        raise ValueError("all ranges must complete before assembly")
    target = output / NAME
    cursor, whole = 0, hashlib.sha256()
    with target.open("xb") as dest:
        for item in state["prefixes"] + state["segments"]:
            path = (ROOT / item["local_file"]).resolve()
            if not path.is_relative_to(ROOT / "tmp/sources-s0") or item["start"] != cursor:
                raise ValueError("source path or contiguous range mismatch")
            part, size = hashlib.sha256(), 0
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(MIB), b""):
                    size += len(chunk)
                    if cursor + size > TOTAL:
                        raise ValueError("assembled file exceeds expected size")
                    dest.write(chunk)
                    part.update(chunk)
                    whole.update(chunk)
            if size != item["bytes"] or item["end_inclusive"] != cursor + size - 1 or part.hexdigest() != item["sha256"]:
                raise ValueError("stored part integrity mismatch")
            cursor += size
    if cursor != TOTAL or whole.hexdigest() != state["file"]["sha256"]:
        raise ValueError("full publisher SHA256 or total mismatch; no sample may be generated")
    state.update(status="assembled_publisher_verified", publisher_checksum_verified=True, assembled_sha256=whole.hexdigest())
    write_json(output / "range-state.json", state)
    checksum = {"status": "downloaded", "name": "enwiki-SHA256SUMS", "url": BASE + "SHA256SUMS",
                "local_file": str((output / "SHA256SUMS").relative_to(ROOT)), "bytes": (output / "SHA256SUMS").stat().st_size,
                "sha256": state["checksum_manifest_sha256"], "checksum_scope": "complete response body"}
    write_json(output / "transfer.json", {"status": "downloaded_unverified", "file": state["file"], "bytes": TOTAL,
               "checksum_request": checksum, "transfer": {"http_code": None}, "range_assembly": {
                   "method": "original contiguous unverified prefix plus exact validator-checked bounded HTTP ranges; final whole publisher SHA256 verified",
                   "evidence_file": str((output / "range-state.json").relative_to(ROOT)),
                   "prefixes": state["prefixes"], "segments": state["segments"], "attempts": state["attempts"]}})
    state["sample_status"] = "parsing"
    write_json(output / "range-state.json", state)
    try:
        verify_sample(output)
        state["sample_status"] = "completed"
    except Exception as exc:
        state.update(sample_status="failed", sample_error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        write_json(output / "range-state.json", state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["download", "verify-sample"], required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "tmp/sources-s0"):
        raise ValueError("output outside sources experiment directory")
    try:
        (download if args.phase == "download" else assemble)(output)
    except Exception as exc:
        write_json(output / f"{args.phase}-error.json", {"status": "failed", "error": f"{type(exc).__name__}: {exc}",
                   "observed_at_utc": datetime.now(UTC).isoformat(), "sample_generated_by_this_attempt": False})
        raise


if __name__ == "__main__":
    main()
