"""Validate captured index HTTP runs[].run/start/list and actions[]/lists[] bodies."""

import argparse
import json
from pathlib import Path

from validate_sync_report import validate_reports

SCHEMAS = {"run": "s3-index-run", "action": "s3-index-action", "list": "s3-index-run-list"}


def validate_index_reports(paths, require_all=False):
    return validate_reports(paths, require_all, schemas=SCHEMAS, run_id_field="index_run_id")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    result = validate_index_reports(args.reports, args.require_all)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
