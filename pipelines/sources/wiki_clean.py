"""Restricted wikitext extraction with source-codepoint mappings, not MediaWiki rendering."""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.metadata
import json
import platform
import re
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .probe import ROOT, digest, write_json

PARSER_VERSION = "0.7.2"
POLICY = {
    "version": "wikitext-source-subset/v1",
    "coordinates": "Unicode codepoints, half-open; source is decoded revision wikitext, not XML bytes",
    "unicode": "identity; no NFC/NFKC or simplified/traditional conversion",
    "whitespace": "CRLF/CR -> LF; tab/NBSP -> space; other whitespace preserved",
    "entities": "semicolon-terminated HTML entities decoded; complete source entity span retained even for multiple codepoints",
    "links": "main-title links retain explicit label or literal title; all colon targets and empty pipe tricks excluded",
    "external_links": "explicit labels only; URLs without labels excluded",
    "templates_tables_comments": "excluded completely with source spans and synthetic double-newline boundaries",
    "tags": "b/i/em/strong/sup/sub/nowiki without attributes retained; others excluded",
    "unsupported_plain_markup": "reject article when markup delimiters, variant conversion or magic words remain in plain nodes",
    "discontinuities": "synthetic separators require separate index segments; no cross-boundary phrase/gap matching",
    "maximum_source_codepoints": 1_000_000,
    "maximum_depth": 50,
    "publication": "NOT_PUBLISHED; restricted development subset, not complete article text",
}


class UnsupportedWikitext(ValueError):
    pass


class Extractor:
    def __init__(self, source: str):
        self.source = source
        self.parts: list[str] = []
        self.mapping: list[dict] = []
        self.exclusions: list[dict] = []
        self.position = 0

    def emit(self, text: str, start: int | None, end: int | None, operation: str):
        if not text:
            return
        stop = self.position + len(text)
        span = {"canonical": [self.position, stop], "source": [start, end] if start is not None else None,
                "operation": operation, "precision": "exact_copy" if operation == "copy" else
                "synthetic" if start is None else "source_span"}
        if operation == "copy" and self.mapping and self.mapping[-1]["operation"] == "copy" and self.mapping[-1]["source"][1] == start:
            self.mapping[-1]["source"][1] = end
            self.mapping[-1]["canonical"][1] = stop
        else:
            self.mapping.append(span)
        self.parts.append(text)
        self.position = stop

    def literal(self, text: str, start: int, *, nowiki=False):
        if not nowiki and re.search(r"\{\{|\}\}|\[\[|\]\]|\{\||\|\}|-\{|\}-|<|__[A-Z_]+__", text):
            raise UnsupportedWikitext(f"unparsed markup in plain node at codepoint {start}")
        cursor = 0
        pattern = r"\r\n|\r|\t|\u00a0" if nowiki else r"\r\n|\r|\t|\u00a0|&(?:#[xX][0-9a-fA-F]+|#\d+|[A-Za-z][A-Za-z0-9]+);"
        for match in re.finditer(pattern, text):
            self.emit(text[cursor:match.start()], start + cursor, start + match.start(), "copy")
            if match[0].startswith("&"):
                decoded = html.unescape(match[0]).replace("\xa0", " ")
                if decoded == match[0]:
                    raise UnsupportedWikitext("unknown HTML entity")
                self.emit(decoded, start + match.start(), start + match.end(), "html_entity")
            else:
                self.emit("\n" if "\r" in match[0] else " ", start + match.start(), start + match.end(), "whitespace")
            cursor = match.end()
        self.emit(text[cursor:], start + cursor, start + len(text), "copy")

    def exclude(self, start: int, end: int, reason: str):
        self.exclusions.append({"source": [start, end], "reason": reason,
                                "canonical_boundary": [self.position, self.position + 2]})
        self.emit("\n\n", None, None, "excluded_content_boundary")

    def child(self, code, start: int, depth: int):
        text = str(code)
        if self.source[start:start + len(text)] != text:
            raise UnsupportedWikitext("child serialization cannot be anchored exactly")
        self.walk(code, start, depth + 1)

    def walk(self, code, start: int, depth=0):
        from mwparserfromhell import nodes

        if depth > POLICY["maximum_depth"]:
            raise UnsupportedWikitext("AST depth limit exceeded")
        cursor = start
        for node in code.nodes:
            raw = str(node)
            end = cursor + len(raw)
            if self.source[cursor:end] != raw:
                raise UnsupportedWikitext("node serialization differs from source")
            if isinstance(node, nodes.Text):
                self.literal(raw, cursor)
            elif isinstance(node, nodes.HTMLEntity):
                value = node.normalize()
                value = value.replace("\xa0", " ")
                self.emit(value, cursor, end, "html_entity")
            elif isinstance(node, nodes.Wikilink):
                title = str(node.title)
                if ":" in title or node.text is not None and not str(node.text):
                    self.exclude(cursor, end, "namespace_or_pipe_trick_link")
                else:
                    self.child(node.text if node.text is not None else node.title,
                               cursor + 2 + (len(title) + 1 if node.text is not None else 0), depth)
            elif isinstance(node, nodes.ExternalLink):
                if node.title is None or not str(node.title) or not node.brackets:
                    self.exclude(cursor, end, "external_url_without_label")
                else:
                    self.child(node.title, cursor + 1 + len(str(node.url)) + (0 if node.suppress_space else 1), depth)
            elif isinstance(node, nodes.Heading):
                self.emit("\n\n", None, None, "heading_boundary")
                self.child(node.title, cursor + node.level, depth)
                self.emit("\n\n", None, None, "heading_boundary")
            elif isinstance(node, nodes.Tag):
                tag = str(node.tag).lower()
                if tag in {"b", "i", "em", "strong", "sup", "sub", "nowiki"} and not node.attributes and not node.self_closing and not node.invalid:
                    if node.wiki_markup:
                        prefix = node.wiki_markup + (node.padding or "") + (node.wiki_style_separator or "")
                    else:
                        prefix = "<" + str(node.tag) + node.padding + ">"
                    offset = cursor + len(prefix)
                    if tag == "nowiki":
                        content = str(node.contents)
                        if self.source[offset:offset + len(content)] != content:
                            raise UnsupportedWikitext("nowiki source mismatch")
                        self.literal(content, offset, nowiki=True)
                    else:
                        self.child(node.contents, offset, depth)
                else:
                    self.exclude(cursor, end, "tag:" + tag)
            elif isinstance(node, (nodes.Template, nodes.Argument, nodes.Comment)):
                self.exclude(cursor, end, type(node).__name__.lower())
            else:
                raise UnsupportedWikitext("unsupported AST node " + type(node).__name__)
            cursor = end
        if cursor != start + len(str(code)):
            raise UnsupportedWikitext("incomplete AST coverage")


def source_spans(result: dict, start: int, end: int) -> list[dict]:
    if not 0 <= start < end <= len(result["canonical_text"]):
        raise ValueError("invalid canonical span")
    spans = []
    for item in result["mapping"]:
        a, b = item["canonical"]
        low, high = max(a, start), min(b, end)
        if low >= high:
            continue
        original = item["source"]
        if item["operation"] == "copy":
            original = [original[0] + low - a, original[0] + high - a]
        spans.append({"canonical": [low, high], "source": original, "precision": item["precision"]})
    return spans


def extract(source: str) -> dict:
    import mwparserfromhell

    if importlib.metadata.version("mwparserfromhell") != PARSER_VERSION:
        raise ValueError("unexpected parser version")
    if not source or len(source) > POLICY["maximum_source_codepoints"]:
        raise UnsupportedWikitext("empty or oversized source")
    code = mwparserfromhell.parse(source)
    if str(code) != source:
        raise UnsupportedWikitext("parser does not preserve complete input")
    extractor = Extractor(source)
    extractor.walk(code, 0)
    text = "".join(extractor.parts)
    if not text.strip():
        raise UnsupportedWikitext("no retained prose")
    result = {"status": "restricted_subset", "canonical_text": text, "mapping": extractor.mapping,
              "exclusions": extractor.exclusions, "source_sha256": digest(source.encode()),
              "canonical_sha256": digest(text.encode()), "mapping_verified": False}
    cursor = 0
    segments = []
    segment_start = 0
    for item in result["mapping"]:
        a, b = item["canonical"]
        if a != cursor or not a < b:
            raise ValueError("non-contiguous mapping")
        if item["operation"] == "copy" and text[a:b] != source[slice(*item["source"])]:
            raise ValueError("copy mapping mismatch")
        if item["source"] is None:
            if a > segment_start:
                segments.append([segment_start, a])
            segment_start = b
        cursor = b
    if segment_start < len(text):
        segments.append([segment_start, len(text)])
    if cursor != len(text):
        raise ValueError("missing output mapping")
    result.update(mapping_verified=True, index_segments=segments,
                  scope="literal source prose subset; all generated/omitted content explicitly excluded")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "tmp/sources-s0/20261016-zhwiki-sample/articles.json")
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/source-cleaning-s0/results")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "tmp"):
        raise ValueError("experiment output must remain in tmp")
    output.mkdir(parents=True, exist_ok=True)
    if args.input.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("input exceeds sample byte limit")
    data = args.input.read_bytes()
    rows = json.loads(data)
    if len(rows) > 5000:
        raise ValueError("article limit exceeded")
    recipe = {"policy": POLICY, "dependency": json.loads((ROOT / "pipelines/sources/cleaning-dependency.json").read_text()),
              "implementation_sha256": digest(Path(__file__).read_bytes())}
    recipe_hash = digest(json.dumps(recipe, sort_keys=True).encode())
    results, failures, reasons = [], [], Counter()
    started = time.monotonic()
    with (output / "cleaned.jsonl").open("w", encoding="utf-8") as stream:
        for row in rows:
            identity = {k: row[k] for k in ("wiki", "page_id", "revision_id", "title", "revision_url", "history_url", "license")}
            try:
                result = extract(row["text"])
                result.update(identity, recipe_sha256=recipe_hash)
                stream.write(json.dumps(result, ensure_ascii=False) + "\n")
                reasons.update(e["reason"] for e in result["exclusions"])
                results.append({"page_id": row["page_id"], "revision_id": row["revision_id"],
                                "canonical_codepoints": len(result["canonical_text"]),
                                "source_sha256": result["source_sha256"], "canonical_sha256": result["canonical_sha256"],
                                "mapping_spans": len(result["mapping"]), "exclusions": len(result["exclusions"])})
            except (ValueError, RecursionError) as exc:
                failures.append({**identity, "status": "rejected", "error": str(exc), "source_sha256": digest(row["text"].encode())})
            if time.monotonic() - started > 600:
                raise TimeoutError("sample processing deadline exceeded")
    with (output / "cleaned.jsonl").open("rb") as stream:
        output_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    report = {"schema": "wikitext-cleaning-experiment/v1", "status": "restricted_subset_only",
              "observed_at_utc": datetime.now(UTC).isoformat(), "runtime": {"python": platform.python_version(), "platform": platform.platform()},
              "input_file": str(args.input.resolve().relative_to(ROOT)), "output_file": str((output / "cleaned.jsonl").relative_to(ROOT)),
              "input_sha256": digest(data), "input_articles": len(rows), "retained_articles": len(results),
              "rejected_articles": len(failures), "recipe_sha256": recipe_hash, "recipe": recipe,
              "elapsed_seconds": time.monotonic() - started, "exclusion_counts": dict(reasons),
              "canonical_codepoints": sum(r["canonical_codepoints"] for r in results),
              "output_sha256": output_hash,
              "articles": results, "failures": failures, "complete_mediawiki_render": False,
              "production_ready": False, "full_text_coverage": "NOT_VALIDATED"}
    write_json(output / "report.json", report)
    print(json.dumps({k: report[k] for k in ("input_articles", "retained_articles", "rejected_articles", "canonical_codepoints", "exclusion_counts")}))


if __name__ == "__main__":
    main()
