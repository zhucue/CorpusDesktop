"""Run with python -m pipelines.sources.probe. Standard library only."""

from __future__ import annotations

import argparse
import bz2
import hashlib
import json
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

MIB = 1024 * 1024
SEED = "corpus-s0-20261016-v1"
ROOT = Path(__file__).resolve().parents[2]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_bounded(response, maximum: int, *, prefix: bool, deadline: float) -> bytes:
    """A prefix reads exactly its cap; a whole file reads one sentinel byte."""
    chunks = []
    remaining = maximum if prefix else maximum + 1
    while remaining:
        if time.monotonic() > deadline:
            raise TimeoutError("total download deadline exceeded")
        chunk = response.read(min(65536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    body = b"".join(chunks)
    if not prefix and len(body) > maximum:
        raise ValueError("download exceeds byte limit")
    return body


class Probe:
    def __init__(self, output: Path):
        self.output = output
        self.output.mkdir(parents=True, exist_ok=True)
        self.requests: list[dict] = []

    def get(self, name: str, url: str, maximum: int = 2 * MIB,
            *, prefix: bool = False, timeout: int = 90) -> tuple[bytes, dict]:
        record = {"name": name, "url": url, "maximum_bytes": maximum,
                  "prefix_requested": prefix, "socket_timeout_seconds": 60,
                  "download_deadline_seconds": timeout, "status": "failed"}
        self.requests.append(record)
        started = time.monotonic()
        try:
            headers = {"User-Agent": "CorpusDesktop-S0-source-qualification/0.1",
                       "Accept-Encoding": "identity"}
            if prefix:
                headers["Range"] = f"bytes=0-{maximum - 1}"
            print(f"GET {name} (cap={maximum}, deadline={timeout}s)", flush=True)
            with urlopen(Request(url, headers=headers), timeout=60) as response:
                record.update(http_status=response.status, resolved_url=response.url,
                              headers={key.lower(): value for key, value in response.headers.items()
                                       if key.lower() in {"last-modified", "etag", "content-length",
                                                          "content-range", "content-type"}})
                length = response.headers.get("Content-Length")
                if not prefix and length and int(length) > maximum:
                    raise ValueError("declared content length exceeds byte limit")
                body = read_bounded(response, maximum, prefix=prefix, deadline=started + timeout)
                if length and len(body) < min(int(length), maximum):
                    raise ValueError("truncated HTTP body")
                if not body:
                    raise ValueError("empty HTTP body")
                if prefix and response.status == 206 and not re.fullmatch(
                    rf"bytes 0-{len(body)-1}/\d+", response.headers.get("Content-Range", "")
                ):
                    raise ValueError("unexpected Content-Range")
            path = self.output / name
            path.write_bytes(body)
            record.update(status="downloaded_prefix" if prefix else "downloaded",
                          bytes=len(body), sha256=digest(body), local_file=str(path.relative_to(ROOT)),
                          checksum_scope="downloaded prefix" if prefix else "complete response body")
            return body, record
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            record["elapsed_seconds"] = round(time.monotonic() - started, 3)

    def get_curl(self, name: str, url: str, maximum: int) -> tuple[bytes, dict]:
        """System TLS transport for slow Tatoeba files; no resume of partial files."""
        record = {"name": name, "url": url, "maximum_bytes": maximum,
                  "download_deadline_seconds": 3600, "connect_timeout_seconds": 60,
                  "status": "failed", "transport": "curl"}
        self.requests.append(record)
        path = self.output / (name + ".partial")
        headers_path = self.output / (name + ".headers")
        print(f"GET {name} with curl; progress in {name}.progress.log", flush=True)
        started = time.monotonic()
        try:
            with (self.output / (name + ".progress.log")).open("w") as log:
                result = subprocess.run(["curl.exe" if __import__("os").name == "nt" else "curl",
                                         "--fail", "--location", "--max-time", "3600", "--connect-timeout", "60",
                                         "--speed-limit", "1", "--speed-time", "60", "--max-filesize", str(maximum),
                                         "--user-agent", "CorpusDesktop-S0-source-qualification/0.1",
                                         "--dump-header", str(headers_path), "--output", str(path),
                                         "--write-out", "%{json}", url],
                                        stdout=subprocess.PIPE, stderr=log, timeout=3660, check=False)
            transfer = json.loads(result.stdout)
            record.update(http_status=transfer["http_code"], resolved_url=transfer["url_effective"],
                          curl_exit=result.returncode)
            if result.returncode:
                raise OSError(f"curl exit {result.returncode}; see {name}.progress.log")
            body = path.read_bytes()
            if not body or len(body) > maximum:
                raise ValueError("empty or oversized curl download")
            raw_headers = headers_path.read_text(encoding="utf-8").strip().split("\n\n")[-1]
            headers = {line.split(":", 1)[0].lower(): line.split(":", 1)[1].strip()
                       for line in raw_headers.splitlines() if ":" in line}
            if "content-length" in headers and len(body) != int(headers["content-length"]):
                raise ValueError("truncated curl download")
            target = self.output / name
            path.replace(target)
            record.update(status="downloaded", bytes=len(body), sha256=digest(body),
                          checksum_scope="complete response body", headers=headers,
                          local_file=str(target.relative_to(ROOT)))
            return body, record
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            record["elapsed_seconds"] = round(time.monotonic() - started, 3)


def unpack_bz2(data: bytes, *, prefix: bool = False, maximum: int = 32 * MIB) -> bytes:
    decompressor = bz2.BZ2Decompressor()
    output = decompressor.decompress(data, max_length=maximum + 1)
    if len(output) > maximum:
        raise ValueError("decompressed data exceeds byte limit")
    if not prefix and not decompressor.eof:
        raise ValueError("incomplete bzip2 file")
    return output if not prefix else output.rsplit(b"\n", 1)[0] + b"\n"


def parse_detailed(data: bytes, language: str) -> dict[int, dict]:
    result = {}
    for line in data.decode("utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) != 6 or fields[1] != language:
            raise ValueError("invalid detailed sentence row")
        sentence_id = int(fields[0])
        if sentence_id in result:
            raise ValueError("duplicate sentence ID")
        result[sentence_id] = {"id": sentence_id, "language": language, "text": fields[2],
                               "owner": fields[3], "added": fields[4], "modified": fields[5],
                               "attribution_url": f"https://tatoeba.org/en/sentences/show/{sentence_id}"}
    return result


def select_pairs(links: bytes, chinese: dict, english: dict, count: int = 10000) -> tuple[list, int]:
    eligible = set()
    for line in links.decode("utf-8").splitlines():
        source_id, target_id = map(int, line.split("\t"))
        if source_id in chinese and target_id in english:
            eligible.add((source_id, target_id))
    ranked = sorted(eligible, key=lambda pair: (digest(f"{SEED}:{pair[0]}:{pair[1]}".encode()), pair))
    return ranked[:count], len(eligible)


def tatoeba(probe: Probe) -> dict:
    base = "https://downloads.tatoeba.org/exports/per_language/"
    chinese, cmn_record = probe.get_curl("cmn_sentences_detailed.tsv.bz2", base + "cmn/cmn_sentences_detailed.tsv.bz2", 4 * MIB)
    links, links_record = probe.get_curl("cmn-eng_links.tsv.bz2", base + "cmn/cmn-eng_links.tsv.bz2", 2 * MIB)
    english, eng_record = probe.get_curl("eng_sentences_detailed.tsv.bz2", base + "eng/eng_sentences_detailed.tsv.bz2", 40 * MIB)
    probe.get("tatoeba-downloads.html", "https://tatoeba.org/en/downloads")
    probe.get("tatoeba-cmn-index.html", base + "cmn/")
    versions = {record["headers"].get("last-modified", "")[:16] for record in (cmn_record, links_record, eng_record)}
    if len(versions) != 1 or "" in versions:
        raise ValueError("Tatoeba export date mismatch; retry a stable weekly export")
    cmn = parse_detailed(unpack_bz2(chinese), "cmn")
    eng = parse_detailed(unpack_bz2(english, maximum=256 * MIB), "eng")
    pairs, population = select_pairs(unpack_bz2(links), cmn, eng)
    if len(pairs) < 10000:
        raise ValueError("fewer than 10000 direct bilingual sample pairs")
    rows = [{"edge_id": f"tatoeba:{a}:{b}", "source": cmn[a], "target": eng[b],
             "relation": "upstream_direct_link", "license": "CC-BY-2.0-FR"} for a, b in pairs]
    write_json(probe.output / "tatoeba-sample.json", rows)
    return {"status": "sample_downloaded", "version": next(iter(versions)),
            "identity": {r["name"]: r["sha256"] for r in (cmn_record, links_record, eng_record)},
            "sample_seed": SEED, "sample_method": "lowest SHA256(seed:cmn_id:eng_id) from unique eligible direct links",
            "sample_scope": "complete cmn and eng detailed files joined to complete direct cmn-eng links; deterministic 10000-pair development sample, not a balanced corpus",
            "eligible_pair_count": population, "sample_pair_count": len(pairs), "pair_ids": pairs,
            "available_cmn_sentences": len(cmn), "available_eng_sentences": len(eng),
            "publisher_checksum": "not present in inspected directory; local SHA256 records acquired bytes only",
            "license_record": "CC BY 2.0 FR per official downloads page; sentence owner and URL preserved; CC0 subset not assumed",
            "release_approved": False, "model_egress": "not_approved", "full_corpus_downloaded": False}


def wikimedia(probe: Probe, wiki: str) -> dict:
    release = "2026-10-01"
    base = f"https://dumps.wikimedia.org/other/mediawiki_content_current/{wiki}/{release}/xml/bzip2/"
    sums, sums_record = probe.get(f"{wiki}-SHA256SUMS", base + "SHA256SUMS", 4 * MIB)
    files = parse_sha256sums(sums, base, wiki, release)
    chosen = min(files, key=lambda item: item["name"])
    data, _ = probe.get(f"{wiki}-articles.prefix.bz2", chosen["url"], 65536, prefix=True)
    if not data.startswith(b"BZh"):
        raise ValueError("download is not bzip2")
    return {"status": "download_prefix_verified", "version": release, "files": files,
            "dataset": "mediawiki_content_current", "chosen_probe_file": chosen["name"], "publisher_sha256": chosen["sha256"],
            "checksum_manifest_sha256": sums_record["sha256"], "publisher_checksum_verified": False,
            "checksum_note": "SHA256SUMS existence marks completed monthly export. Only 64 KiB downloaded; full-file SHA256 remains unverified.",
            "namespace_filter": [0], "current_revisions_only": True,
            "license_record": "Wikimedia Terms of Use section 7; CC BY-SA 4.0/GFDL where applicable; page-specific exceptions require retention",
            "attribution_fields_required": ["wiki", "page_id", "title", "revision_id", "revision_url", "history_url", "license", "modifications"],
            "release_approved": False, "model_egress": "not_approved", "full_corpus_downloaded": False}


def parse_sha256sums(body: bytes, base: str, wiki: str, release: str) -> list[dict]:
    files = []
    for line in body.decode().splitlines():
        checksum, name = line.split(maxsplit=1)
        name = name.lstrip("*")
        name = name.removeprefix("./")
        if not re.fullmatch(r"[0-9a-f]{64}", checksum) or not re.fullmatch(rf"{wiki}-{release}-[A-Za-z0-9-]+\.xml\.bz2", name):
            raise ValueError("invalid publisher checksum entry")
        files.append({"name": name, "sha256": checksum, "url": urljoin(base, name)})
    if not files or len({f["name"] for f in files}) != len(files):
        raise ValueError("empty or duplicate publisher checksum entries")
    return files


def ud(probe: Probe) -> dict:
    repository = "UniversalDependencies/UD_Chinese-GSD"
    tag = "r2.18"
    # Resolved using official git ls-remote on 2026-10-16; pinned in registry.json.
    commit = "e0d85a020182e264d6384be2a59c0f4879a1cc35"
    base = f"https://raw.githubusercontent.com/{repository}/{commit}/"
    readme, _ = probe.get("ud-README.md", base + "README.md")
    license_body, _ = probe.get("ud-LICENSE.txt", base + "LICENSE.txt")
    data, record = probe.get("zh_gsd-ud-test.conllu", base + "zh_gsd-ud-test.conllu", 4 * MIB)
    ids = re.findall(r"^# sent_id = (.+)$", data.decode(), flags=re.MULTILINE)
    if not ids or len(ids) != len(set(ids)) or "Attribution-ShareAlike 4.0" not in license_body.decode():
        raise ValueError("invalid UD sample or unexpected license")
    if "not the underlying content" not in readme.decode():
        raise ValueError("UD underlying-content caveat changed; review required")
    return {"status": "sample_downloaded_license_review_required", "version": tag, "commit": commit,
            "sample_file": record["url"], "sample_sha256": record["sha256"], "sentence_count": len(ids),
            "sentence_ids": ids, "language": "zh-Hant", "license_record": "CC BY-SA 4.0 for UD annotations; Google does not claim copyright in underlying text",
            "attribution": ["Mo Shen", "Ryan McDonald", "Daniel Zeman", "Peng Qi", "Universal Dependencies Chinese-GSD"],
            "release_approved": False, "model_egress": "not_approved", "full_treebank_downloaded": False,
            "blocking_review": "Confirm underlying text rights or approve an alternative UD treebank before public release"}


def ud_gum(probe: Probe) -> dict:
    repository = "UniversalDependencies/UD_English-GUM"
    commit = "b58e74bc22d17220c9198864c253a50a897bf27f"
    base = f"https://raw.githubusercontent.com/{repository}/{commit}/"
    readme, _ = probe.get("gum-README.md", base + "README.md")
    license_body, license_record = probe.get("gum-LICENSE.txt", base + "LICENSE.txt")
    if b"NonCommercial" not in license_body or b"License: CC BY-NC-SA 4.0" not in readme:
        raise ValueError("GUM licensing changed; review required")
    data, record = probe.get("en_gum-ud-test.conllu", base + "en_gum-ud-test.conllu", 16 * MIB)
    ids = re.findall(r"^# sent_id = (.+)$", data.decode(), flags=re.MULTILINE)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("invalid GUM sentence IDs")
    return {"status": "alternative_sample_downloaded_license_review_required", "version": "r2.18",
            "commit": commit, "sample_sha256": record["sha256"], "sentence_count": len(ids),
            "sentence_ids": ids, "license_file_sha256": license_record["sha256"],
            "license_record": "CC BY-NC-SA 4.0; LICENSE describes underlying sources and separate Reddit data not included in this repository",
            "attribution": "Original text sources and GUM annotators; Zeldes (2017), The GUM Corpus; preserve document meta::author and meta::sourceURL",
            "blocking_review": "Confirm intended deployment meets NonCommercial and ShareAlike conditions, or select another reviewed treebank",
            "release_approved": False, "model_egress": "not_approved", "full_treebank_downloaded": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/sources-s0" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--source", choices=["all", "tatoeba", "zhwiki", "enwiki", "ud", "gum"], default="all")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "tmp" / "sources-s0"):
        parser.error("output must stay inside repository tmp/sources-s0")
    probe = Probe(output)
    results = {"schema": "source-qualification/v1", "observed_at_utc": datetime.now(UTC).isoformat(),
               "stage": "S0", "publication_state": "NOT_PUBLISHED", "sources": {}, "requests": probe.requests}
    tasks = {"tatoeba": tatoeba, "zhwiki": lambda p: wikimedia(p, "zhwiki"),
             "enwiki": lambda p: wikimedia(p, "enwiki"), "ud": ud, "gum": ud_gum}
    for name, task in tasks.items():
        if args.source not in {"all", name}:
            continue
        try:
            results["sources"][name] = task(probe)
        except Exception as exc:  # noqa: BLE001 -- CLI must persist failed acquisition evidence.
            results["sources"][name] = {"status": "blocked", "error": f"{type(exc).__name__}: {exc}", "release_approved": False}
        write_json(output / "manifest.json", results)
        print(f"{name}: {results['sources'][name]['status']}", flush=True)
    print(str(output / "manifest.json"))
    return int(any(s["status"] == "blocked" for s in results["sources"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
