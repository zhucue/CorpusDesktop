"""Bounded S0 CQP adapter. Only compiler-generated token queries reach stdin."""

import re
import subprocess
from itertools import product

from contracts.semantics import validate_query_semantics
from pipelines.query.engine import QueryError


def compile_token_pattern(pattern, allowed_attributes):
    kind = pattern["type"]
    if kind == "term":
        attr, value = pattern["attr"], pattern["value"]
        if attr not in allowed_attributes or not re.fullmatch(r"[a-z][a-z0-9_]*", attr):
            raise QueryError("ATTRIBUTE_UNAVAILABLE")
        if pattern["op"] != "eq":
            raise QueryError("QUERY_UNSUPPORTED: regex")
        # The first executable subset deliberately rejects CQP quoting/control characters.
        # Full literal escaping must be separately accepted before expanding this boundary.
        if any(c in value for c in '"\\;<>') or any(ord(c) < 32 for c in value):
            raise QueryError(
                "QUERY_UNSUPPORTED: CQP literal quoting not accepted in S0"
            )
        return "[" + ("word" if attr == "form" else attr) + '="' + value + '" %l]'
    if kind == "sequence":
        parts = []
        for item in pattern["items"]:
            if item["type"] == "gap":
                parts.append(
                    "[]{" + str(int(item["min"])) + "," + str(int(item["max"])) + "}"
                )
            else:
                parts.append(compile_token_pattern(item, allowed_attributes))
        return " ".join(parts)
    if kind == "any_of":
        return (
            "("
            + " | ".join(
                compile_token_pattern(p, allowed_attributes)
                for p in pattern["patterns"]
            )
            + ")"
        )
    raise QueryError("QUERY_UNSUPPORTED: only token patterns are CQP candidates")


def _query_expressions(query, corpus, allowed_attributes):
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator, ValidationError

    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "contracts/schemas/corpus-query.schema.json"
        ).read_text(encoding="utf-8")
    )
    try:
        Draft202012Validator(schema).validate(query)
        validate_query_semantics(query)
    except (ValueError, ValidationError) as error:
        raise QueryError("QUERY_UNSUPPORTED: invalid AST") from error
    if query["unit"] != "token" or query.get("condition") or query.get("filters"):
        raise QueryError(
            "QUERY_UNSUPPORTED: CQP S0 adapter supports positive token patterns only"
        )
    if not re.fullmatch("[A-Z][A-Z0-9_]*", corpus):
        raise QueryError("Invalid registered corpus identifier")

    def fixed_patterns(pattern):
        if pattern["type"] == "any_of":
            return [
                variant
                for branch in pattern["patterns"]
                for variant in fixed_patterns(branch)
            ]
        if pattern["type"] != "sequence":
            return [pattern]
        alternatives = []
        combinations = 1
        for item in pattern["items"]:
            if item["type"] == "gap":
                combinations *= item["max"] - item["min"] + 1
                if combinations > 256:
                    raise QueryError(
                        "QUERY_UNSUPPORTED: S0 fixed-gap expansion exceeds 256"
                    )
                alternatives.append(
                    [
                        {"type": "gap", "min": n, "max": n}
                        for n in range(int(item["min"]), int(item["max"]) + 1)
                    ]
                )
            else:
                alternatives.append([item])
        return [
            {"type": "sequence", "items": list(items)}
            for items in product(*alternatives)
        ]

    variants = fixed_patterns(query["pattern"])
    if len(variants) > 256:
        raise QueryError("QUERY_UNSUPPORTED: S0 branch expansion exceeds 256")
    boundary = "s" if query["within"] == "sentence" else "p"
    return [
        compile_token_pattern(variant, allowed_attributes) + " within " + boundary
        for variant in variants
    ]


def cqp_spans(
    query,
    registry,
    corpus="S0",
    executable="cqp",
    allowed_attributes=frozenset({"form"}),
    timeout=30,
):
    # CQP variable-length queries can discard alternative ends at the same start.
    # Execute every bounded fixed-length branch, then union full token spans.
    commands = corpus + ";\nset MatchingStrategy traditional;\n"
    for expression in _query_expressions(query, corpus, allowed_attributes):
        commands += "A = " + expression + ";\ndump A;\n"
    commands += "exit;\n"
    result = subprocess.run(
        [executable, "-c", "-r", str(registry)],
        input=commands,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
        check=True,
    )
    if re.search(r"\b(error|syntax error|undefined)\b", result.stderr, re.IGNORECASE):
        raise RuntimeError(result.stderr)
    spans = set()
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and fields[0].isdigit() and fields[1].isdigit():
            spans.add((int(fields[0]), int(fields[1]) + 1))
    return spans


def _union_commands(query, corpus, allowed_attributes):
    """Full NQR union retains all distinct (start,end), including nested spans.

    Do not use query-level cut: the NQR must contain the complete match set.
    No lexical sort/count command is applied, so dump uses corpus position order.
    """
    expressions = _query_expressions(query, corpus, allowed_attributes)
    commands = corpus + ";\nset MatchingStrategy traditional;\n"
    commands += "M = " + expressions[0] + ";\n"
    for expression in expressions[1:]:
        commands += "B = " + expression + ";\nM = union M B;\n"
    return commands


def _run_lines(commands, registry, executable, timeout):
    result = subprocess.run(
        [executable, "-c", "-r", str(registry)],
        input=commands + "exit;\n",
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
        check=True,
    )
    if re.search(r"\b(error|undefined)\b", result.stderr, re.IGNORECASE):
        raise RuntimeError(result.stderr)
    return [
        line
        for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("CQP version ")
    ]


def cqp_page_spans(
    query,
    registry,
    *,
    offset=0,
    limit=50,
    corpus="S0",
    executable="cqp",
    allowed_attributes=frozenset({"form"}),
    timeout=30,
):
    """Export only an ordered page from a fully matched, deduplicated CQP NQR."""
    if (
        type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= 50
    ):
        raise ValueError("offset must be nonnegative; page limit must be 1..50")
    commands = _union_commands(query, corpus, allowed_attributes)
    commands += f"dump M {offset} {offset + limit - 1};\n"
    rows = _run_lines(commands, registry, executable, timeout)
    spans = []
    for line in rows:
        fields = line.split("\t")
        if len(fields) != 4 or not all(
            re.fullmatch(r"-?\d+", field) for field in fields
        ):
            raise RuntimeError("Unexpected CQP page output")
        start, end = int(fields[0]), int(fields[1]) + 1
        if start < 0 or end <= start:
            raise RuntimeError("Invalid CQP span")
        spans.append((start, end))
    if len(spans) > limit or spans != sorted(set(spans)):
        raise RuntimeError("CQP page is not a bounded unique corpus-position sequence")
    return spans


def cqp_counts(
    query,
    registry,
    *,
    document_attribute,
    corpus="S0",
    executable="cqp",
    allowed_attributes=frozenset({"form"}),
    timeout=30,
):
    """Independent exact counts, with no hit dump or page truncation.

    The trusted index recipe must supply full sentence/document structural coverage.
    Paragraph-spanning queries are rejected until touched-sentence counting exists.
    """
    commands = _union_commands(query, corpus, allowed_attributes)
    if query["within"] != "sentence":
        raise QueryError(
            "QUERY_UNSUPPORTED: paged count currently requires sentence scope"
        )
    if not re.fullmatch(r"[a-z][a-z0-9_]*", document_attribute):
        raise ValueError("Invalid document structural attribute")
    commands += (
        "size M;\nS = M expand to s;\nsize S;\n"
        f"D = M expand to {document_attribute};\nsize D;\n"
    )
    rows = _run_lines(commands, registry, executable, timeout)
    if len(rows) != 3 or not all(row.isdigit() for row in rows):
        raise RuntimeError("Unexpected CQP count output")
    hits, segments, documents = map(int, rows)
    if not 0 <= documents <= segments <= hits:
        raise RuntimeError("Invalid CQP counts or structural coverage")
    return {
        "total_hits": hits,
        "matched_segments": segments,
        "matched_documents": documents,
    }
