"""Validate actual private TXT and research captures without inventing responses."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from contracts.materials import (  # noqa: E402
    ImportAction,
    ImportList,
    ImportView,
    MaterialList,
    MaterialView,
    ValidatedUploadList,
)
from tests.contracts.validate_research_report import validate_research_reports  # noqa: E402

MODELS = {
    "imports": ("import", ImportView),
    "import_actions": ("import-action", ImportAction),
    "import_lists": ("imports", ImportList),
    "materials": ("material", MaterialView),
    "material_lists": ("materials", MaterialList),
    "validated_upload_lists": ("uploads", ValidatedUploadList),
}


def validate_private_reports(paths, require_all=False):
    research = validate_research_reports(paths, require_all)
    private = validate_research_reports(
        paths, require_all, models=MODELS, prefix="s3-private"
    )
    counts = (
        research["validated_response_counts"] | private["validated_response_counts"]
    )
    failures = research["failures"] + private["failures"]
    missing = research["not_recorded"] + private["not_recorded"]
    return {
        **research,
        "status": "passed"
        if sum(counts.values()) and not failures and (not require_all or not missing)
        else "failed",
        "validated_response_counts": counts,
        "not_recorded": missing,
        "failures": failures,
        "schema_sha256": research["schema_sha256"] | private["schema_sha256"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    result = validate_private_reports(args.reports, args.require_all)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
