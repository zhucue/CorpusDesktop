"""Stream the fixed English current shard to disk; hash and parse in a later CPU phase."""
import argparse
import bz2
import hashlib
import json
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from .probe import MIB, ROOT, Probe, parse_sha256sums, write_json
from .wiki_sample import LimitedReader, select_articles

NAME = "enwiki-2026-10-01-p43486390p48278244.xml.bz2"
BASE = "https://dumps.wikimedia.org/other/mediawiki_content_current/enwiki/2026-10-01/xml/bzip2/"
MAXIMUM = 2560 * MIB


def response_headers(path: Path):
    return {key.strip().lower(): value.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if ":" in line for key, value in [line.split(":", 1)]}


def resume_once(output: Path):
    """One explicitly requested recovery of this fixed shard; never restart automatically."""
    record = json.loads((output / "transfer.json").read_text(encoding="utf-8"))
    if record["status"] != "failed" or record["file"]["url"] != BASE + NAME:
        raise ValueError("expected failed fixed-shard transfer")
    partial = output / (NAME + ".partial")
    tail = output / (NAME + ".tail")
    receipt = output / "resume.json"
    if receipt.exists() or tail.exists():
        raise ValueError("one recovery attempt already exists; inspect evidence instead of retrying")
    original = response_headers(output / "headers.txt")
    head = response_headers(output / "resume-head.txt")
    if any(original.get(k) != head.get(k) for k in ("etag", "last-modified", "content-length")):
        raise ValueError("HEAD version differs from original transfer")
    total = int(original["content-length"])
    offset = partial.stat().st_size
    if not original.get("etag") or original["etag"].startswith("W/") or not 0 < offset < total <= MAXIMUM:
        raise ValueError("invalid version validator or byte bounds")
    state = {"status": "downloading_tail", "offset": offset, "total": total, "etag": original["etag"],
             "last_modified": original["last-modified"], "url": BASE + NAME,
             "deadline_seconds": 21600, "socket_timeout_seconds": 60,
             "started_at": datetime.now(UTC).isoformat(), "bytes": 0}
    write_json(receipt, state)
    started = time.monotonic()
    request = urllib.request.Request(BASE + NAME, headers={"Range": f"bytes={offset}-", "If-Range": original["etag"],
                                                        "User-Agent": "CorpusDesktop-S0-source-qualification/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            expected_range = f"bytes {offset}-{total - 1}/{total}"
            if response.status != 206 or response.headers.get("Content-Range") != expected_range:
                raise ValueError("server did not honor exact continuation range")
            if response.headers.get("ETag") != original["etag"] or response.headers.get("Last-Modified") != original["last-modified"]:
                raise ValueError("range response version mismatch")
            state["response_headers"] = dict(response.headers)
            with tail.open("xb") as stream:
                while chunk := response.read(MIB):
                    state["bytes"] += len(chunk)
                    if state["bytes"] > total - offset or time.monotonic() - started > 21600:
                        raise ValueError("continuation exceeds byte/time limit")
                    stream.write(chunk)
                    write_json(receipt, state)
            if state["bytes"] != total - offset:
                raise ValueError("incomplete range body")
        state["status"] = "tail_downloaded_unverified"
    except Exception as exc:
        state.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        state["finished_at"] = datetime.now(UTC).isoformat()
        write_json(receipt, state)


def assemble_tail(output: Path, record: dict):
    state = json.loads((output / "resume.json").read_text(encoding="utf-8"))
    partial, tail, target = (output / (NAME + suffix) for suffix in (".partial", ".tail", ""))
    if state["status"] != "tail_downloaded_unverified" or partial.stat().st_size != state["offset"] or tail.stat().st_size != state["total"] - state["offset"]:
        raise ValueError("resume artifacts incomplete")
    with target.open("xb") as dest:
        for source in (partial, tail):
            with source.open("rb") as stream:
                for chunk in iter(lambda: stream.read(MIB), b""):
                    dest.write(chunk)
    record.update(status="downloaded_unverified", bytes=target.stat().st_size, recovery="one verified If-Range/206 continuation; original pieces retained")
    write_json(output / "transfer.json", record)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(MIB), b""):
            h.update(chunk)
    return h.hexdigest()


def download(output: Path):
    probe = Probe(output)
    sums, checksum = probe.get("enwiki-SHA256SUMS", BASE + "SHA256SUMS")
    selected = next(f for f in parse_sha256sums(sums, BASE, "enwiki", "2026-10-01") if f["name"] == NAME)
    partial = output / (NAME + ".partial")
    if partial.exists() or (output / NAME).exists():
        raise ValueError("existing shard or partial found; inspect its process and evidence before any restart")
    record = {"file": selected, "checksum_request": checksum, "maximum_bytes": MAXIMUM,
              "deadline_seconds": 21600, "status": "downloading", "started_at": datetime.now(UTC).isoformat(),
              "publisher_checksum_verified": False}
    write_json(output / "transfer.json", record)
    print(f"Downloading {NAME}; progress: {output / 'progress.log'}", flush=True)
    try:
        with (output / "progress.log").open("w") as log:
            result = subprocess.run(["curl.exe", "--fail", "--location", "--max-time", "21600",
                                     "--connect-timeout", "60", "--speed-time", "60", "--speed-limit", "1",
                                     "--max-filesize", str(MAXIMUM), "--user-agent", "CorpusDesktop-S0-source-qualification/0.1",
                                     "--dump-header", str(output / "headers.txt"), "--output", str(partial),
                                     "--write-out", "%{json}", selected["url"]], stdout=subprocess.PIPE,
                                    stderr=log, timeout=21660, check=False)
        record["transfer"] = json.loads(result.stdout)
        record["curl_exit"] = result.returncode
        if result.returncode or not partial.exists() or not 0 < partial.stat().st_size <= MAXIMUM:
            raise OSError(f"download failed; curl={result.returncode}; see progress.log")
        if partial.stat().st_size != int(record["transfer"]["size_download"]):
            raise ValueError("download size mismatch")
        partial.replace(output / NAME)
        record.update(status="downloaded_unverified", bytes=(output / NAME).stat().st_size)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        record.update(status="failed", error=str(exc))
        raise
    finally:
        record["finished_at"] = datetime.now(UTC).isoformat()
        write_json(output / "transfer.json", record)
    print("Download complete; publisher SHA256 and sample are still pending.")


def verify_sample(output: Path):
    record = json.loads((output / "transfer.json").read_text(encoding="utf-8"))
    if record["status"] == "failed" and (output / "resume.json").exists():
        assemble_tail(output, record)
    if record["status"] != "downloaded_unverified" or record["file"]["name"] != NAME or record["file"]["url"] != BASE + NAME:
        raise ValueError("expected complete fixed English shard transfer")
    path = output / NAME
    if path.stat().st_size != record["bytes"] or path.stat().st_size > MAXIMUM:
        raise ValueError("shard size mismatch")
    print("Streaming full-file SHA256...", flush=True)
    checksum = file_sha256(path)
    if checksum != record["file"]["sha256"]:
        raise ValueError("publisher SHA256 mismatch")
    print("Publisher SHA256 verified; parsing entire shard with 32GiB/1800s expansion limits...", flush=True)
    with bz2.open(path, "rb") as stream:
        articles, population = select_articles(LimitedReader(stream, maximum=32768 * MIB, seconds=1800), "enwiki")
    if len(articles) != 1000:
        raise ValueError("insufficient eligible English articles")
    sample = output / "articles.json"
    write_json(sample, articles)
    source = {"status": "sample_downloaded", "dataset": "mediawiki_content_current", "version": "2026-10-01",
              "sample_article_count": len(articles), "eligible_article_count": population,
              "sample_seed": "corpus-s0-20261016-v1",
              "sample_method": "lowest SHA256(seed:page_id:revision_id) across ALL eligible pages in one fixed complete shard",
              "sample_scope": "one selected shard; not corpus-wide random sample",
              "sample_ids": [[a["page_id"], a["revision_id"]] for a in articles],
              "sample_sha256": file_sha256(sample), "sample_file": str(sample.relative_to(ROOT)),
              "shard": record["file"], "publisher_checksum_verified": True, "namespace_filter": [0],
              "redirects_excluded": True, "text_format": "raw wikitext; cleaning not yet run",
              "release_approved": False, "model_egress": "not_approved", "full_corpus_downloaded": False,
              "expanded_bytes_limit": 32768 * MIB, "parse_deadline_seconds": 1800,
              "xml_storage": "streamed through bz2 and iterparse; whole XML not written; retained memory includes current page and 1000 selected pages"}
    request = {"status": "downloaded", "name": NAME, "url": BASE + NAME, "local_file": str(path.relative_to(ROOT)),
               "bytes": path.stat().st_size, "sha256": checksum, "checksum_scope": "complete downloaded file",
               "maximum_bytes": MAXIMUM, "http_status": record["transfer"]["http_code"],
               "publisher_checksum_verified": True, "record_kind": "verified_local_artifact"}
    if record.get("range_assembly"):
        request.update(http_status=None, assembly=record["range_assembly"])
    if record.get("recovery"):
        recovery = json.loads((output / "resume.json").read_text(encoding="utf-8"))
        request.update(http_status=None, assembly="ordered original partial + independently downloaded If-Range tail",
                       network_attempts=[
                           {"http_status": record["transfer"]["http_code"], "curl_exit": record["curl_exit"],
                            "status": "failed_partial", "bytes": recovery["offset"], "error": record.get("error")},
                           {"http_status": 206, "status": recovery["status"], "bytes": recovery["bytes"],
                            "content_range": recovery["response_headers"]["Content-Range"],
                            "etag": recovery["etag"], "last_modified": recovery["last_modified"]}])
    write_json(output / "manifest.json", {"schema": "source-qualification/v1", "sources": {"enwiki": source},
               "observed_at_utc": datetime.now(UTC).isoformat(), "requests": [record["checksum_request"], request]})
    print(f"Complete shard verified; {len(articles)} samples from {population} eligible articles.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/sources-s0/20261016-enwiki-sample")
    parser.add_argument("--phase", choices=["download", "resume-once", "verify-sample"], default="download")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "tmp/sources-s0"):
        raise ValueError("output outside source experiment directory")
    try:
        {"download": download, "resume-once": resume_once, "verify-sample": verify_sample}[args.phase](output)
    except Exception as exc:
        write_json(output / f"{args.phase}-error.json", {"phase": args.phase, "status": "failed",
                   "error": f"{type(exc).__name__}: {exc}", "observed_at_utc": datetime.now(UTC).isoformat(),
                   "sample_generated_by_this_attempt": False})
        raise


if __name__ == "__main__":
    main()
