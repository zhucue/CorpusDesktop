"""Read immutable S3 source indices without loading the corpus into Python objects."""
import hashlib
import json
import mmap
from bisect import bisect_left, bisect_right
from pathlib import Path

from pipelines.query.cwb import cqp_counts, cqp_page_spans
from pipelines.query.engine import QueryError
from pipelines.query.source_index import RECORD, TOKEN, U64, digest
from pipelines.query.source_recipe import RECIPE_SHA256, encoded, storage_key


def storage_query(query):
    """Translate only exact surface literals on a copy; all other semantics stay compiler-validated."""
    import copy
    result = copy.deepcopy(query)

    def visit(pattern):
        if pattern.get("type") == "term" and pattern.get("attr") == "form" and pattern.get("op") == "eq":
            pattern["value"] = storage_key(pattern["value"])
        for child in pattern.get("items", pattern.get("patterns", [])):
            visit(child)
    visit(result["pattern"])
    return result


class _Positions:
    def __init__(self, mapped, offset, count):
        self.mapped, self.offset, self.count = mapped, offset, count

    def __len__(self):
        return self.count

    def __getitem__(self, number):
        if not 0 <= number < self.count:
            raise IndexError(number)
        return U64.unpack_from(self.mapped, self.offset + number * 8)[0]


class _RecordStarts:
    def __init__(self, reader, field=3):
        self.reader, self.field = reader, field

    def __len__(self):
        return self.reader.count

    def __getitem__(self, number):
        return self.reader.record(number)[self.field]


def _monotone_bisect(sequence, value, lower, *, right=False):
    """Bracket a forward seek locally before bisecting a sorted mmap view.

    Successive posting/record seeks usually advance only a few entries. A full
    remaining-range bisect would unpack millions of distant records repeatedly.
    Exponential bracketing also bounds work when the next candidate is far away.
    """
    upper, step, size = lower, 1, len(sequence)
    while upper < size:
        current = sequence[upper]
        if current > value or (current == value and not right):
            break
        lower = upper + 1
        upper += step
        step *= 2
    search = bisect_right if right else bisect_left
    return search(sequence, value, lower, min(upper + 1, size))


def character_anchors(pattern, vocabulary):
    """Select necessary characters only; original text still decides every match.

    A missing character is a zero-cost empty posting. OR needs every branch's
    candidates; a sequence can use any required (non-gap) item. Posting counts
    estimate work without reading text or changing persisted index identity.
    """
    def cost(characters):
        return sum(vocabulary.get(c, {}).get("count", 0) for c in characters)

    kind = pattern["type"]
    if kind == "literal":
        return {min(set(pattern["value"]), key=lambda c: (cost({c}), c))}
    if kind == "any_of":
        return set().union(*(character_anchors(p, vocabulary) for p in pattern["patterns"]))
    if kind == "sequence":
        choices = [character_anchors(p, vocabulary) for p in pattern["items"] if p["type"] != "gap"]
        return min(choices, key=lambda chars: (cost(chars), tuple(sorted(chars))))
    raise QueryError("QUERY_UNSUPPORTED")


class SourceIndexReader:
    def __init__(self, directory, runtime_directory=None, *, verify=True):
        self.directory = Path(directory).resolve()
        self.runtime = Path(runtime_directory).resolve() if runtime_directory is not None else None
        self.manifest = json.loads((self.directory / "manifest.json").read_text("utf-8"))
        from pipelines.query.project_recipe import (
            RECIPE_SHA256 as PROJECT_RECIPE_SHA256,
        )
        supported = {"source-index/v1": RECIPE_SHA256, "project-index/v1": PROJECT_RECIPE_SHA256}
        self.is_project = self.manifest["format"] == "project-index/v1"
        if supported.get(self.manifest["format"]) != self.manifest["recipe_sha256"]:
            raise ValueError("INDEX_RECIPE_MISMATCH")
        if hashlib.sha256(encoded(self.manifest["identity"])).hexdigest() != self.manifest["identity_sha256"]:
            raise ValueError("INDEX_IDENTITY_MISMATCH")
        for entry in self.manifest["files"]:
            path = self.directory / entry["name"]
            if not path.resolve().is_relative_to(self.directory) or path.is_symlink() or path.stat().st_size != entry["bytes"]:
                raise ValueError("INDEX_FILE_INVALID")
            if verify and digest(path) != entry["sha256"]:
                raise ValueError("INDEX_HASH_MISMATCH")
        self.handles, self.maps = [], {}
        try:
            names = ("texts.utf8", "records.map", "tokens.map", "characters.bin")
            if self.is_project:
                names += ("metadata.map", "members.jsonl")
            for name in names:
                handle = (self.directory / name).open("rb")
                self.handles.append(handle)
                self.maps[name] = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
            self.count = self.manifest["counts"]["sentences"]
            if len(self.maps["records.map"]) != self.count * RECORD.size:
                raise ValueError("INDEX_RECORD_COUNT_MISMATCH")
            self.starts = _RecordStarts(self)
            self.byte_starts = _RecordStarts(self, field=1)
            self.vocabulary = json.loads((self.directory / "characters.json").read_text("utf-8"))
            if self.runtime is None:
                # API mapping mode is strictly read-only: no registry or executable.
                return
            self.runtime.mkdir(parents=True, exist_ok=False)
            self.registry = self.runtime / "registry"
            self.registry.mkdir()
            home = str(self.directory / "data")
            if any(c in home for c in '\\"\n\r'):
                # CWB supported deployment is Linux. Reject ambiguous registry escaping.
                raise ValueError("INDEX_REGISTRY_PATH_INVALID")
            registry = (self.directory / "registry/source").read_text("utf-8")
            if registry.count('"__INDEX_DATA__"') != 1:
                raise ValueError("INDEX_REGISTRY_INVALID")
            (self.registry / "source").write_text(registry.replace('"__INDEX_DATA__"', '"' + home + '"'), encoding="utf-8")
            # Fixed wrapper suppresses user startup and macro files. No query enters a shell command.
            self.executable = self.runtime / "cqp-fixed"
            self.executable.write_text('#!/bin/sh\nexec /usr/bin/cqp -I /dev/null -M /dev/null -m "$@"\n', encoding="ascii")
            self.executable.chmod(0o700)
        except BaseException:
            self.close()
            raise

    def close(self):
        for mapped in self.maps.values():
            mapped.close()
        for handle in self.handles:
            handle.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def record(self, ordinal):
        if not 0 <= ordinal < self.count:
            raise IndexError(ordinal)
        return RECORD.unpack_from(self.maps["records.map"], ordinal * RECORD.size)

    def text(self, ordinal):
        _, offset, size, *_ = self.record(ordinal)
        return self.maps["texts.utf8"][offset:offset + size].decode("utf-8")

    def metadata(self, ordinal):
        if self.is_project:
            from pipelines.query.project_index import META
            offset, size = META.unpack_from(self.maps['metadata.map'], ordinal*META.size)
            value = json.loads(self.maps['members.jsonl'][offset:offset+size])
            if value['ordinal'] != ordinal or value['document_ordinal'] != self.record(ordinal)[0]:
                raise ValueError('INDEX_METADATA_INVALID')
            return value
        text = self.text(ordinal)
        sid = self.record(ordinal)[0]
        revision = f"tatoeba:{sid}:{hashlib.sha256(text.encode()).hexdigest()}"
        return {'document_id':f'tatoeba:{sid}', 'document_ordinal':ordinal,
                'revision_id':revision, 'segment_id':revision+':sentence', 'segment_start_cp':0,
                'segment_end_cp':len(text), 'origin_kind':'source', 'source_sentence_id':sid,
                'source_url':f'https://tatoeba.org/en/sentences/show/{sid}'}

    def document_ordinal(self, ordinal):
        return self.record(ordinal)[0] if self.is_project else ordinal

    def hit(self, ordinal, left, right):
        text = self.text(ordinal)
        meta = self.metadata(ordinal)
        start = meta['segment_start_cp']
        return {"source_sentence_id":meta['source_sentence_id'], "revision_id":meta['revision_id'],
                "document_id":meta['document_id'], "origin_kind":meta['origin_kind'],
                "source_id":meta.get("source_id"), "material_id":meta["document_id"] if meta["origin_kind"] == "private" else None,
                "segment_id":meta['segment_id'], "context_start_cp":start,
                "start":start+left, "end":start+right, "left":text[max(0,left-40):left],
                "match":text[left:right], "right":text[right:right+40], "source_url":meta['source_url']}

    def span_hit(self, ordinal, left, right, token_start=None, token_end=None, *, context_codepoints=40):
        """Map a verified span; token offsets are real CWB positions or absent."""
        if type(context_codepoints) is not int or not 0 <= context_codepoints <= 200:
            raise ValueError("INVALID_CONTEXT")
        record = self.record(ordinal)
        if not 0 <= left < right <= record[4]:
            raise ValueError("INVALID_SPAN")
        if (token_start is None) != (token_end is None):
            raise ValueError("INVALID_TOKEN_SPAN")
        if token_start is not None:
            upper = self.record(ordinal + 1)[5] if ordinal + 1 < self.count else self.manifest['counts']['tokens']
            if not record[5] <= token_start < token_end <= upper:
                raise ValueError("INVALID_TOKEN_SPAN")
            first = TOKEN.unpack_from(self.maps['tokens.map'], token_start * TOKEN.size)
            last = TOKEN.unpack_from(self.maps['tokens.map'], (token_end - 1) * TOKEN.size)
            if first[0] != ordinal or first[1] != left or last[0] != ordinal or last[2] != right:
                raise ValueError("INVALID_TOKEN_SPAN")
        text = self.text(ordinal)
        hit = self.hit(ordinal, left, right)
        return {**hit, "sentence_ordinal": ordinal,
                "start_cp": hit["start"], "end_cp": hit["end"],
                "token_start": token_start - record[5] if token_start is not None else None,
                "token_end": token_end - record[5] if token_end is not None else None,
                "global_token_start": token_start, "global_token_end": token_end,
                "left": text[max(0, left-context_codepoints):left],
                "right": text[right:right+context_codepoints]}

    def token_page(self, query, *, offset=0, limit=50):
        if query.get("within") != "sentence":
            raise QueryError("QUERY_UNSUPPORTED")
        spans = cqp_page_spans(storage_query(query), self.registry, corpus="SOURCE", offset=offset, limit=limit, executable=str(self.executable), allowed_attributes=frozenset({"form"}))
        page = []
        for start, end in spans:
            ordinal, left, _ = TOKEN.unpack_from(self.maps["tokens.map"], start * TOKEN.size)
            last, _, right = TOKEN.unpack_from(self.maps["tokens.map"], (end - 1) * TOKEN.size)
            if last != ordinal:
                raise ValueError("INDEX_CROSS_SENTENCE_HIT")
            page.append(self.hit(ordinal, left, right))
        return {"page": page, "total_hits": None, "matched_segments": None, "matched_documents": None, "count_state": "pending"}

    def token_counts(self, query):
        return {**cqp_counts(storage_query(query), self.registry, corpus="SOURCE", document_attribute="doc", executable=str(self.executable), allowed_attributes=frozenset({"form"})), "count_state": "complete"}

    def _character_matches(self, query, checkpoint=None, *, max_sentence_spans=250_000):
        """Yield sorted spans without materializing a complete result set."""
        from jsonschema import Draft202012Validator

        from contracts.semantics import validate_query_semantics

        schema = json.loads((Path(__file__).resolve().parents[2] / "contracts/schemas/corpus-query.schema.json").read_text("utf-8"))
        Draft202012Validator(schema).validate(query)
        validate_query_semantics(query)
        if query["unit"] != "character" or query["within"] != "sentence" or query.get("condition") or query.get("filters"):
            raise QueryError("QUERY_UNSUPPORTED")

        # Merge only posting-derived candidate sentences, not every material object.
        import heapq

        def candidate_sentences(character):
            entry = self.vocabulary.get(character)
            if not entry:
                return
            posting = _Positions(self.maps["characters.bin"], entry["offset"], entry["count"])
            at, lower_ordinal = 0, 0
            while at < len(posting):
                if checkpoint:
                    checkpoint()
                ordinal = _monotone_bisect(self.starts, posting[at], lower_ordinal, right=True) - 1
                yield ordinal
                _, _, _, start, length, _ = self.record(ordinal)
                at = _monotone_bisect(posting, start + length, at + 1)
                lower_ordinal = ordinal + 1

        def literal_sentences(value):
            # Valid UTF-8 has an unambiguous byte representation. Native find
            # supplies candidate sentences only: original-text matching below
            # still computes overlapping Unicode codepoint spans.
            try:
                needle = value.encode('utf-8')
            except UnicodeEncodeError:
                return  # An isolated surrogate cannot occur in validated UTF-8.
            at, lower_ordinal = 0, 0
            texts = self.maps['texts.utf8']
            while (found := texts.find(needle, at)) >= 0:
                if checkpoint:
                    checkpoint()
                if time.monotonic() - started > 120:
                    raise QueryError("QUERY_TIMEOUT")
                ordinal = _monotone_bisect(self.byte_starts, found, lower_ordinal, right=True) - 1
                _, start, length, *_ = self.record(ordinal)
                end = start + length
                if found + len(needle) <= end:
                    yield ordinal
                # Even a rejected cross-sentence candidate must resume at this
                # sentence's end, not after the needle (which could skip a real
                # match in the following sentence).
                at, lower_ordinal = end, ordinal + 1

        work = 0

        def add_span(result, span):
            nonlocal work
            work += 1
            if work % 1024 == 0:
                if time.monotonic() - started > 120:
                    raise QueryError("QUERY_TIMEOUT")
                if checkpoint:
                    checkpoint()
            result.add(span)
            if len(result) > max_sentence_spans:
                raise QueryError("QUERY_RESULT_TOO_LARGE")

        def matches(pattern, text):
            kind = pattern["type"]
            if kind == "literal":
                value, start, result = pattern["value"], 0, set()
                while (start := text.find(value, start)) >= 0:
                    add_span(result, (start, start + len(value)))
                    start += 1
                return result
            if kind == "any_of":
                result = set()
                for branch in pattern['patterns']:
                    for span in matches(branch, text):
                        add_span(result, span)
                return result
            spans, gap = matches(pattern["items"][0], text), (0, 0)
            for item in pattern["items"][1:]:
                if item["type"] == "gap":
                    gap = (item["min"], item["max"])
                    continue
                following = sorted(matches(item, text))
                starts = [a for a, _ in following]
                combined = set()
                for a, b in spans:
                    for i in range(bisect_left(starts, b + gap[0]), bisect_right(starts, b + gap[1])):
                        add_span(combined, (a, following[i][1]))
                spans = combined
                gap = (0, 0)
            return spans

        import time
        started = time.monotonic()
        previous = None
        pattern = query['pattern']
        candidates = literal_sentences(pattern['value']) if pattern['type'] == 'literal' else heapq.merge(
            *(candidate_sentences(c) for c in sorted(character_anchors(pattern, self.vocabulary))))
        for ordinal in candidates:
            if checkpoint:
                checkpoint()
            if time.monotonic() - started > 120:
                raise QueryError("QUERY_TIMEOUT")
            if ordinal == previous:
                continue
            previous = ordinal
            spans = sorted(matches(query["pattern"], self.text(ordinal)))
            for left, right in spans:
                yield ordinal, left, right

    def character_page(self, query, *, offset=0, limit=50):
        from itertools import islice
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("INVALID_PAGE")
        page = [self.hit(*hit) for hit in islice(self._character_matches(query), offset, offset + limit)]
        return {"page": page, "total_hits": None, "matched_segments": None, "matched_documents": None, "count_state": "pending"}

    def character_counts(self, query):
        total = segments = documents = source_documents = private_documents = 0
        previous_segment = previous_document = None
        for ordinal, _, _ in self._character_matches(query):
            total += 1
            if ordinal != previous_segment:
                segments += 1
                document = self.document_ordinal(ordinal)
                if document != previous_document:
                    documents += 1
                    private = self.is_project and self.metadata(ordinal)['origin_kind'] == 'private'
                    private_documents += private
                    source_documents += not private
                previous_segment, previous_document = ordinal, document
        result = {"total_hits":total, "matched_segments":segments, "matched_documents":documents,
                  "count_state":"complete", "document_count_unit":"document" if self.is_project else "imported_sentence_record"}
        if self.is_project:
            result.update(matched_source_documents=source_documents, matched_private_documents=private_documents)
        return result

    def character_query(self, query, *, offset=0, limit=50):
        """Convenience verification path; serving uses independent page/count calls."""
        page = self.character_page(query, offset=offset, limit=limit)["page"]
        result = self.character_counts(query)
        return {"page": page, **result}
