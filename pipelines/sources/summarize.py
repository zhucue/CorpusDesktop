"""Verify acquired bytes and combine selected S0 manifests into a durable evidence file."""
import argparse
import hashlib
import json
from pathlib import Path

from .probe import ROOT, digest, write_json


def summarize(paths: list[Path]) -> dict:
    report = {"schema": "source-qualification-summary/v1", "publication_state": "NOT_PUBLISHED",
              "sources": {}, "requests": [], "input_manifests": []}
    for path in paths:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for name, source in manifest["sources"].items():
            if name in {"zhwiki", "enwiki"} and source.get("status") != "blocked" and source.get("dataset") != "mediawiki_content_current":
                raise ValueError("legacy Wikimedia probe cannot satisfy the current baseline")
            if name in report["sources"]:
                raise ValueError(f"duplicate source {name}; explicitly select one authoritative probe")
            if name in {"zhwiki", "enwiki"} and source.get("sample_file"):
                sample = (ROOT / source["sample_file"]).resolve()
                if not sample.is_relative_to(ROOT / "tmp/sources-s0") or digest(sample.read_bytes()) != source["sample_sha256"]:
                    raise ValueError("sample file integrity mismatch")
            report["sources"][name] = source
        for request in manifest["requests"]:
            if request["status"] in {"downloaded", "downloaded_prefix"}:
                local = (ROOT / request["local_file"]).resolve()
                if not local.is_relative_to(ROOT / "tmp" / "sources-s0"):
                    raise ValueError("artifact outside source probe directory")
                with local.open("rb") as stream:
                    actual_hash = hashlib.file_digest(stream, "sha256").hexdigest()
                if local.stat().st_size != request["bytes"] or actual_hash != request["sha256"]:
                    raise ValueError(f"acquired file integrity mismatch: {local}")
            report["requests"].append(request)
        report["input_manifests"].append({"path": str(path.relative_to(ROOT)),
                                           "sha256": digest(path.read_bytes()),
                                           "observed_at_utc": manifest["observed_at_utc"]})
    report["requirements_pending"] = ["Wikimedia production cleaning and full-text coverage acceptance (restricted Chinese subset experiment is separate evidence)",
                                        "UD underlying text/deployment license approval",
                                        "source publication and model egress policy decisions"]
    for wiki in ("zhwiki", "enwiki"):
        source = report["sources"].get(wiki, {})
        if source.get("sample_article_count", 0) < 1000 or not source.get("publisher_checksum_verified"):
            report["requirements_pending"].append(f"{wiki} 1000-5000 article reproducible sample and full publisher SHA256 validation")
    if report["sources"].get("tatoeba", {}).get("sample_pair_count", 0) < 10000:
        report["requirements_pending"].append("Tatoeba fixed 10000 direct-pair sample download")
    report["k01_complete"] = False
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifests", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, default=ROOT / "pipelines/sources/s0-evidence.json")
    args = parser.parse_args()
    report = summarize([p.resolve() for p in args.manifests])
    write_json(args.output, report)
    print(f"Verified {len(report['requests'])} request records; K01 remains incomplete.")
