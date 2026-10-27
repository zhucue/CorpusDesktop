"""Validate recorded policy/release/mount HTTP bodies without filling absent evidence."""

import argparse
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = {
    "policies": "s3-release-policy", "policy_actions": "s3-release-policy-action",
    "releases": "s3-release-view", "release_actions": "s3-release-action",
    "mounts": "s3-release-mount", "mount_actions": "s3-release-mount-action",
    "mount_lists": "s3-release-mounts", "manifests": "s3-release-manifest",
    "version_lists": "s1-source-versions-result",
}


def validate_release_reports(paths, require_all=False):
    validators, hashes = {}, {}
    for name, schema_name in SCHEMAS.items():
        raw = (ROOT / "contracts/schemas" / f"{schema_name}.schema.json").read_bytes()
        schema = json.loads(raw)
        Draft202012Validator.check_schema(schema)
        validators[name] = Draft202012Validator(schema, format_checker=FormatChecker())
        hashes[name] = hashlib.sha256(raw).hexdigest()
    counts = dict.fromkeys(SCHEMAS, 0)
    failures, inputs = [], []
    for path in paths:
        raw = Path(path).read_bytes()
        report = json.loads(raw)
        if not isinstance(report, dict):
            raise TypeError("REPORT_MUST_BE_OBJECT")
        inputs.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
        for name, validator in validators.items():
            records = report.get(name, [])
            if not isinstance(records, list):
                raise TypeError("RESPONSE_COLLECTION_MUST_BE_ARRAY")
            for index, value in enumerate(records):
                counts[name] += 1
                for error in validator.iter_errors(value):
                    failures.append({"location": f"{path}:{name}[{index}]", "field": list(error.absolute_path), "rule": error.validator})
    missing = [name for name, count in counts.items() if not count]
    passed = bool(sum(counts.values())) and not failures and (not require_all or not missing)
    return {"status": "passed" if passed else "failed", "require_all": require_all,
            "validated_response_counts": counts, "not_recorded": missing, "failures": failures,
            "inputs": inputs, "schema_sha256": hashes,
            "limits": "Recorded response shape only; authentication, stored-object integrity and production licensing need separate evidence."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    result = validate_release_reports(args.reports, args.require_all)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)

