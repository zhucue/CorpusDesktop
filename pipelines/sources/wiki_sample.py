"""Select a fixed article sample from one fully verified current export shard."""
from __future__ import annotations

import argparse
import bz2
import heapq
import json
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from .probe import MIB, ROOT, SEED, Probe, digest, parse_sha256sums, write_json


class LimitedReader:
    def __init__(self, stream, maximum=1024 * MIB, seconds=300):
        self.stream, self.maximum = stream, maximum
        self.read_bytes = 0
        self.deadline = time.monotonic() + seconds

    def read(self, size=-1):
        if time.monotonic() > self.deadline:
            raise TimeoutError("XML parsing deadline exceeded")
        body = self.stream.read(min(65536, size if size >= 0 else 65536))
        self.read_bytes += len(body)
        if self.read_bytes > self.maximum:
            raise ValueError("expanded XML exceeds byte limit")
        return body


def select_articles(stream, wiki: str, count=1000):
    candidates = 0
    selected = []
    context = ET.iterparse(stream, events=("start", "end"))
    _, root = next(context)
    namespace = root.tag.split("}")[0] + "}" if "}" in root.tag else ""
    q = lambda name: namespace + name
    for event, page in context:
        if event != "end" or page.tag != q("page"):
            continue
        revision = page.find(q("revision"))
        if page.findtext(q("ns")) == "0" and page.find(q("redirect")) is None and revision is not None:
            text = revision.findtext(q("text"))
            if text and text.strip():
                page_id, revision_id = int(page.findtext(q("id"))), int(revision.findtext(q("id")))
                candidates += 1
                rank = int(digest(f"{SEED}:{page_id}:{revision_id}".encode()), 16)
                row = {"wiki": wiki, "page_id": page_id, "revision_id": revision_id,
                       "title": page.findtext(q("title")), "text": text,
                       "revision_url": f"https://{wiki[:-4]}.wikipedia.org/w/index.php?oldid={revision_id}",
                       "history_url": f"https://{wiki[:-4]}.wikipedia.org/w/index.php?curid={page_id}&action=history",
                       "license": "Wikimedia Terms of Use section 7; page-specific exceptions remain to be reviewed",
                       "modifications": "raw wikitext retained; no text cleaning applied"}
                item = (-rank, -page_id, -revision_id, row)
                if len(selected) < count:
                    heapq.heappush(selected, item)
                elif item[:3] > selected[0][:3]:
                    heapq.heapreplace(selected, item)
        root.remove(page)
    return [item[3] for item in sorted(selected, reverse=True)], candidates


def validate_receipt(path: Path, wiki: str, receipt: dict | None = None) -> Path:
    path = path.resolve()
    if not path.is_relative_to(ROOT / "tmp/sources-s0"):
        raise ValueError("receipt outside source output directory")
    if receipt is not None:
        file = receipt["file"]
        base = f"https://dumps.wikimedia.org/other/mediawiki_content_current/{wiki}/2026-10-01/xml/bzip2/"
        files = parse_sha256sums(f'{file["sha256"]}  {file["name"]}'.encode(), base, wiki, "2026-10-01")
        if file["url"] != files[0]["url"] or receipt["request"]["url"] != file["url"]:
            raise ValueError("receipt wiki, version or URL mismatch")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("download_receipt", type=Path, nargs="?", default=ROOT / "tmp/sources-s0/20261016-zhwiki-sample/download.json")
    parser.add_argument("--wiki", choices=["zhwiki", "enwiki"], required=True)
    parser.add_argument("--download", action="store_true", help="Download the fixed 28MB Chinese tail shard with its official checksum")
    args = parser.parse_args()
    args.download_receipt = validate_receipt(args.download_receipt, args.wiki)
    if args.download:
        if args.wiki != "zhwiki":
            raise ValueError("English shards exceed this experiment's 100MiB cap")
        probe = Probe(args.download_receipt.resolve().parent)
        base = "https://dumps.wikimedia.org/other/mediawiki_content_current/zhwiki/2026-10-01/xml/bzip2/"
        sums, checksum_request = probe.get("zhwiki-SHA256SUMS", base + "SHA256SUMS")
        selected = next(f for f in parse_sha256sums(sums, base, "zhwiki", "2026-10-01")
                        if f["name"] == "zhwiki-2026-10-01-p9590059p9623184.xml.bz2")
        _, request = probe.get_curl(selected["name"], selected["url"], 100 * MIB)
        if request["sha256"] != selected["sha256"]:
            raise ValueError("complete shard publisher SHA256 mismatch")
        write_json(args.download_receipt, {"file": selected, "request": request,
                                          "checksum_request": checksum_request, "publisher_checksum_verified": True})
    receipt = json.loads(args.download_receipt.read_text(encoding="utf-8"))
    validate_receipt(args.download_receipt, args.wiki, receipt)
    path = (ROOT / receipt["request"]["local_file"]).resolve()
    if not path.is_relative_to(ROOT / "tmp/sources-s0"):
        raise ValueError("download outside source output directory")
    body = path.read_bytes()
    if len(body) > 100 * MIB or digest(body) != receipt["file"]["sha256"]:
        raise ValueError("complete shard publisher SHA256 mismatch or size limit")
    with bz2.open(path, "rb") as stream:
        articles, candidates = select_articles(LimitedReader(stream), args.wiki)
    if len(articles) < 1000:
        raise ValueError(f"only {len(articles)} eligible articles; 1000 required")
    sample_path = path.parent / "articles.json"
    write_json(sample_path, articles)
    result = {"status": "sample_downloaded", "dataset": "mediawiki_content_current", "version": "2026-10-01",
              "sample_article_count": len(articles), "eligible_article_count": candidates,
              "sample_seed": SEED, "sample_method": "lowest SHA256(seed:page_id:revision_id) from one fixed shard",
              "sample_scope": "biased tail-shard development sample; not corpus-wide random sample",
              "sample_ids": [[a["page_id"], a["revision_id"]] for a in articles],
              "sample_sha256": digest(sample_path.read_bytes()), "sample_file": str(sample_path.relative_to(ROOT)),
              "shard": receipt["file"], "publisher_checksum_verified": True,
              "namespace_filter": [0], "redirects_excluded": True, "text_format": "raw wikitext; cleaning map pending",
              "release_approved": False, "model_egress": "not_approved", "full_corpus_downloaded": False}
    write_json(path.parent / "manifest.json", {"schema": "source-qualification/v1",
               "observed_at_utc": datetime.now(UTC).isoformat(), "sources": {args.wiki: result},
               "requests": ([receipt["checksum_request"]] if "checksum_request" in receipt else []) + [receipt["request"]]})
    print(f"Verified complete shard and selected {len(articles)} of {candidates} articles")


if __name__ == "__main__":
    main()
