"""Validate captured research HTTP bodies and semantic invariants; never invent evidence."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from contracts.research import (  # noqa: E402 - support direct repository-local CLI execution
    ContextView,
    HitPage,
    QueryAction,
    QueryList,
    QueryRunView,
    SnapshotAction,
    SnapshotList,
    SnapshotView,
)

MODELS = {
    "snapshots": ("snapshot", SnapshotView),
    "snapshot_actions": ("snapshot-action", SnapshotAction),
    "snapshot_lists": ("snapshots", SnapshotList),
    "queries": ("query", QueryRunView),
    "query_actions": ("query-action", QueryAction),
    "query_lists": ("queries", QueryList),
    "hit_pages": ("hits", HitPage),
    "contexts": ("context", ContextView),
}


def validate_research_reports(
    paths, require_all=False, *, models=MODELS, prefix="s3-research"
):
    validators, hashes = {}, {}
    for name, (schema_name, _) in models.items():
        raw = (
            ROOT / "contracts/schemas" / f"{prefix}-{schema_name}.schema.json"
        ).read_bytes()
        validators[name] = Draft202012Validator(
            json.loads(raw), format_checker=FormatChecker()
        )
        hashes[name] = hashlib.sha256(raw).hexdigest()
    counts = dict.fromkeys(models, 0)
    failures, inputs = [], []
    for path in paths:
        raw = Path(path).read_bytes()
        report = json.loads(raw)
        if not isinstance(report, dict):
            raise TypeError("REPORT_MUST_BE_OBJECT")
        inputs.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
        for name, (_, model) in models.items():
            values = report.get(name, [])
            if not isinstance(values, list):
                raise TypeError("RESPONSE_COLLECTION_MUST_BE_ARRAY")
            for index, value in enumerate(values):
                counts[name] += 1
                location = f"{path}:{name}[{index}]"
                errors = list(validators[name].iter_errors(value))
                failures.extend(
                    {
                        "location": location,
                        "field": list(error.absolute_path),
                        "rule": error.validator,
                    }
                    for error in errors
                )
                if not errors:
                    try:
                        model.model_validate(value)
                    except ValidationError as error:
                        # Never echo material, credentials, invalid input or arbitrary error messages.
                        failures.extend(
                            {
                                "location": location,
                                "field": list(item["loc"]),
                                "rule": item["type"],
                            }
                            for item in error.errors(
                                include_input=False, include_context=False
                            )
                        )
    missing = [name for name, count in counts.items() if not count]
    passed = (
        bool(sum(counts.values())) and not failures and (not require_all or not missing)
    )
    return {
        "status": "passed" if passed else "failed",
        "require_all": require_all,
        "validated_response_counts": counts,
        "not_recorded": missing,
        "failures": failures,
        "inputs": inputs,
        "schema_sha256": hashes,
        "limits": "Recorded HTTP shape and semantic invariants only; authorization, durable spans, exact query correctness and performance require independent execution evidence.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    result = validate_research_reports(args.reports, args.require_all)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
