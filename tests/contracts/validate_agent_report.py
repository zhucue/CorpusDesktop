"""Validate captured K09 browser control/projection HTTP responses."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from contracts.agent import (  # noqa: E402
    EventList,
    MessageList,
    RunList,
    RuntimeView,
    RunView,
    SessionList,
    SessionView,
)
from tests.contracts.validate_research_report import validate_research_reports  # noqa: E402

MODELS = {
    "runtimes": ("runtime", RuntimeView),
    "sessions": ("session", SessionView),
    "session_lists": ("session-list", SessionList),
    "runs": ("run", RunView),
    "run_lists": ("run-list", RunList),
    "messages": ("messages", MessageList),
    "events": ("events", EventList),
}


def validate_agent_reports(paths, require_all=False):
    result = validate_research_reports(paths, require_all, models=MODELS, prefix="k09-agent")
    result["limits"] = "Captured HTTP shape and invariants only; real host execution, cancellation, waiting jobs, restoration and browser authorization need separate execution evidence. Production model/material scope is not accepted."
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    result = validate_agent_reports(args.reports, args.require_all)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
