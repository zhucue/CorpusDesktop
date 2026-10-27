"""Explicit D12 acquisition contracts; no public release or production Pi grant."""

import json
from pathlib import Path

S2_INPUTS = {"sync.start": "sync-start", "sync.report": "sync-ref", "jobs.list": "scoped-job-list",
             "jobs.get": "scoped-job-ref", "jobs.cancel": "scoped-job-ref", "jobs.retry": "scoped-job-ref"}


def build_s2(save, obj):
    root = Path(__file__).parent
    uuid = {"type": "string", "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"}
    integer = {"type": "integer", "minimum": 0}
    text = {"type": "string"}
    nullable_count = {"type": ["integer", "null"], "minimum": 0}
    timestamp = {"type": "string", "format": "date-time"}
    source = {"source_id": {"const": "D12"}}
    ref = obj({"sync_run_id": uuid})
    listing = obj({**source, "cursor": {"type": "string", "maxLength": 512},
                   "page_size": {"type": "integer", "minimum": 1, "maximum": 100}}, ["source_id"])
    save("s2-sync-start", obj(source))
    save("s2-sync-ref", ref)
    save("s2-sync-list", listing)
    for name, prior, platform in [("scoped-job-ref", "job-id", ref), ("scoped-job-list", "job-list", listing)]:
        project = json.loads((root / f"schemas/s1-{prior}.schema.json").read_text(encoding="utf-8"))
        project.pop("$schema", None)
        project.pop("$id", None)
        save(f"s2-{name}", {"oneOf": [project, platform], "$comment": "Trusted session scope chooses the branch. Schema validity never grants platform or project access."})
    state = {"enum": ["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]}
    result = obj({"acquisition_id": uuid, "state": {"const": "VALIDATED"}, "searchable": {"const": False},
                  "manifest_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}, "export_date": {"type": ["string", "null"]},
                  "quality": {"type": "object"}, "diff": {"type": "object"}, "license": {"type": "object"}})
    error = obj({"code": text, "message": text, "retryable": {"type": "boolean"}})
    run = obj({"id": uuid, "source_id": {"const": "D12"}, "connector_id": text, "source_revision": {"type": "integer", "minimum": 1},
               "source_identity": obj({"name": text, "publisher": text, "entry_kind": text, "official_url": text}),
               "state": state, "stage": {"enum": ["QUEUED", "ACQUIRING", "PARSING", "STORING", "VALIDATED", "FAILED", "CANCELLED"]},
               "attempt": {"type": "integer", "minimum": 1}, "created_at": timestamp, "updated_at": timestamp,
               "progress": obj({"processed_bytes": integer, "total_bytes": nullable_count, "processed_records": integer,
                                "total_records": nullable_count, "file_name": {"type": ["string", "null"]}}),
               "result": {"oneOf": [{"type": "null"}, result]}, "error": {"oneOf": [{"type": "null"}, error]},
               "allowed_actions": obj({"cancel": {"type": "boolean"}, "retry": {"type": "boolean"}})})
    run["allOf"] = [{"if": {"properties": {"state": {"const": "SUCCEEDED"}}},
                     "then": {"properties": {"result": result, "stage": {"const": "VALIDATED"}, "error": {"type": "null"}}},
                     "else": {"properties": {"result": {"type": "null"}}}}]
    save("s2-sync-run", run)
    save("s2-sync-action", obj({"action_id": uuid, "sync_run_id": uuid, "job_id": uuid, "state": state, "run": run}))
    save("s2-sync-run-list", obj({"items": {"type": "array", "items": run}, "total": integer,
                                 "next_cursor": {"type": ["string", "null"]}, "allowed_actions": obj({"start": {"type": "boolean"}})}))
    inventory = {"stage": "S2", "available_tools": [], "tool_production_authorization": "not_accepted",
                 "coverage": [{"capability_id": name, "input_schema": f"schemas/s2-{schema}.schema.json",
                               "scope_kind": "platform", "manual_http": "implemented", "tool_availability": "planned",
                               "adapter": "explicit_contract_test_only"} for name, schema in S2_INPUTS.items()],
                 "limits": ["D12 fixed connector only; no model-controlled URL, recipe or authorization.",
                            "VALIDATED acquisition is admin-only staging, not a published catalog release, searchable index or approved license.",
                            "Project jobs retain their original branch; platform jobs.list requires source_id=D12, while jobs.get/cancel/retry require sync_run_id.",
                            "No upstream check button, scheduled sync or release publication is implemented."]}
    (root / "s2-capabilities.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
