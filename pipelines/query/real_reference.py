"""Independent raw-CoNLL-U enumerator for the finite real-corpus query experiment.

Does not read canonical revisions/tokens, VRT, CQP output or importer offsets.
Raw FORM capture groups recover #text coordinates independently of prefix mapping.
"""

import re


def raw_attributes(path, selected_blocks):
    rows = []
    for ordinal, block in enumerate(
        re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip())
    ):
        if ordinal in selected_blocks:
            rows.extend(
                tuple(line.split("\t")[1:4])
                for line in block.splitlines()
                if re.match(r"^[1-9]\d*\t", line)
            )
    return rows


def endpoints(pattern, words, position):
    kind = pattern["type"]
    if kind == "term":
        column = {"form": 1, "lemma": 2, "upos": 3}[pattern["attr"]]
        if position < len(words) and words[position][column] == pattern["value"]:
            return {position + 1}
        return set()
    if kind == "any_of":
        return set().union(
            *(endpoints(branch, words, position) for branch in pattern["patterns"])
        )
    if kind != "sequence":
        raise ValueError("unsupported reference pattern")
    positions = {position}
    for item in pattern["items"]:
        if item["type"] == "gap":
            positions = {
                start + length
                for start in positions
                for length in range(item["min"], item["max"] + 1)
                if start + length <= len(words)
            }
        else:
            positions = {
                end for start in positions for end in endpoints(item, words, start)
            }
    return positions


def raw_reference(path, source, document_mode, selected_blocks, query):
    if (
        query["unit"] != "token"
        or query["within"] != "sentence"
        or query.get("condition")
        or query.get("filters")
    ):
        raise ValueError("unsupported reference query")
    spans, evidence, document_hits, sentence_hits = [], [], set(), set()
    base = 0
    document = None
    # Independent parser: regex blocks, raw integer-ID rows, no importer functions.
    content = path.read_text(encoding="utf-8")
    for ordinal, block in enumerate(re.split(r"\n\s*\n", content.strip())):
        lines = block.splitlines()
        if boundary := re.search(r"^# newdoc id = (.+)$", block, re.MULTILINE):
            document = boundary[1]
        if ordinal not in selected_blocks:
            continue
        sentence = re.search(r"^# sent_id = (.+)$", block, re.MULTILINE)[1]
        text = re.search(r"^# text = (.*)$", block, re.MULTILINE)[1]
        if document_mode == "unavailable":
            document = source + ":record:" + sentence
        words = [line.split("\t") for line in lines if re.match(r"^[1-9]\d*\t", line)]
        matcher = re.fullmatch(
            r"\s*"
            + r"\s*".join("(" + re.escape(row[1]) + ")" for row in words)
            + r"\s*",
            text,
        )
        if matcher is None:
            raise AssertionError("Independent raw text mapping failed: " + sentence)
        local = sorted(
            {
                (start, end)
                for start in range(len(words))
                for end in endpoints(query["pattern"], words, start)
            }
        )
        for start, end in local:
            left, right = matcher.start(start + 1), matcher.end(end)
            spans.append((base + start, base + end))
            evidence.append(
                {
                    "revision_id": source + ":" + sentence,
                    "start": left,
                    "end": right,
                    "left": text[max(0, left - 40) : left],
                    "match": text[left:right],
                    "right": text[right : right + 40],
                }
            )
            document_hits.add(document)
            sentence_hits.add(sentence)
        base += len(words)
    return {
        "spans": spans,
        "page": evidence[:50],
        "counts": {
            "total_hits": len(spans),
            "matched_segments": len(sentence_hits),
            "matched_documents": len(document_hits),
        },
    }
