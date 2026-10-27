"""Validate captured evidence, note, export and independent source-policy responses."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from contracts.outcomes import (  # noqa: E402
    EvidenceAction,
    EvidenceList,
    EvidenceView,
    ExportAction,
    ExportList,
    ExportView,
    NoteAction,
    NoteList,
    NoteView,
)
from contracts.releases import PolicyAction, PolicyView  # noqa: E402
from tests.contracts.validate_research_report import validate_research_reports  # noqa: E402

MODELS = {
    "evidence": ("evidence", EvidenceView),
    "evidence_actions": ("evidence-action", EvidenceAction),
    "evidence_lists": ("evidence-list", EvidenceList),
    "notes": ("note", NoteView),
    "note_actions": ("note-action", NoteAction),
    "note_lists": ("note-list", NoteList),
    "exports": ("export", ExportView),
    "export_actions": ("export-action", ExportAction),
    "export_lists": ("export-list", ExportList),
}
POLICIES = {
    "policies": ("policy", PolicyView),
    "policy_actions": ("policy-action", PolicyAction),
}


def validate_outcomes_reports(paths, require_all=False):
    outcomes = validate_research_reports(
        paths, require_all, models=MODELS, prefix="s3-outcomes"
    )
    policies = validate_research_reports(
        paths, require_all, models=POLICIES, prefix="s3-release"
    )
    counts = outcomes["validated_response_counts"] | policies["validated_response_counts"]
    failures = outcomes["failures"] + policies["failures"]
    missing = outcomes["not_recorded"] + policies["not_recorded"]
    return {
        **outcomes,
        "status": "passed"
        if sum(counts.values()) and not failures and (not require_all or not missing)
        else "failed",
        "validated_response_counts": counts,
        "not_recorded": missing,
        "failures": failures,
        "schema_sha256": outcomes["schema_sha256"] | policies["schema_sha256"],
        "limits": "Captured HTTP schema and semantic invariants only; authorization, immutable evidence, note conflicts, complete export bytes and browser flows require execution evidence.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    result = validate_outcomes_reports(args.reports, args.require_all)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
