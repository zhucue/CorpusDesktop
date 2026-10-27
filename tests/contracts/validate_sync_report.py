"""Validate captured HTTP JSON, without manufacturing missing responses.

Usage: python tests/contracts/validate_sync_report.py smoke.json [capture.json]
       Add --require-all to require run, action and list response evidence.

Smoke reports use runs[].run, runs[].start and runs[].list. Additional HTTP
captures may use actions[] and lists[]. Only recorded bodies are validated.
"""

import argparse
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = {"run": "s2-sync-run", "action": "s2-sync-action", "list": "s2-sync-run-list"}


def validate_reports(paths, require_all=False, *, schemas=None, run_id_field="sync_run_id"):
    schemas = SCHEMAS if schemas is None else schemas
    counts = dict.fromkeys(schemas, 0)
    failures = []
    inputs = []
    validators = {}
    schema_hashes = {}
    for kind, name in schemas.items():
        raw = (ROOT / "contracts/schemas" / f"{name}.schema.json").read_bytes()
        schema = json.loads(raw)
        Draft202012Validator.check_schema(schema)
        validators[kind] = Draft202012Validator(schema, format_checker=FormatChecker())
        schema_hashes[kind] = hashlib.sha256(raw).hexdigest()
    for path in paths:
        raw = Path(path).read_bytes()
        report = json.loads(raw)
        if not isinstance(report, dict):
            raise TypeError("REPORT_MUST_BE_OBJECT")
        runs = report.get("runs", [])
        if not isinstance(runs, list):
            raise TypeError("RESPONSE_COLLECTION_MUST_BE_ARRAY")
        inputs.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
        for kind, field in [("run", "runs"), ("action", "actions"), ("list", "lists")]:
            records = report.get(field, [])
            if not isinstance(records, list):
                raise TypeError("RESPONSE_COLLECTION_MUST_BE_ARRAY")
            located = [(f"{field}[{index}]", record) for index, record in enumerate(records)]
            if kind != "run":
                nested = "start" if kind == "action" else "list"
                located.extend((f"runs[{index}].{nested}", run[nested])
                               for index, run in enumerate(runs)
                               if isinstance(run, dict) and nested in run)
            for label, record in located:
                body = record.get("run") if kind == "run" and isinstance(record, dict) else record
                errors = list(validators[kind].iter_errors(body))
                location = f"{path}:{label}"
                for error in errors:
                    # Do not echo response contents or server error messages.
                    failures.append({"location": location, "field": list(error.absolute_path),
                                     "rule": error.validator})
                if (not errors and kind == "action"
                        and not (body[run_id_field] == body["job_id"] == body["run"]["id"]
                                 and body["state"] == body["run"]["state"])):
                    failures.append({"location": location, "rule": "ACTION_RUN_ID_STATE_EQUAL"})
                counts[kind] += 1
    missing = [kind for kind, count in counts.items() if count == 0]
    passed = not failures and sum(counts.values()) > 0 and (not require_all or not missing)
    return {"status": "passed" if passed else "failed", "validated_response_counts": counts,
            "not_recorded": missing, "require_all": require_all, "failures": failures,
            "inputs": inputs, "schema_sha256": schema_hashes,
            "scope": "Captured JSON contract validation only; no authorization or worker acceptance claim."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    result = validate_reports(args.reports, args.require_all)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
