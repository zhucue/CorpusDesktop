"""Fixed-acquisition private indexes; publication and policy approval are separate."""

import json
from pathlib import Path

S3_INPUTS = {
    "indexes.build": "index-build", "indexes.report": "index-ref",
    "jobs.list": "scoped-job-list", "jobs.get": "scoped-job-ref",
    "jobs.cancel": "scoped-job-ref", "jobs.retry": "scoped-job-ref",
}


def build_s3(save, obj):
    root = Path(__file__).parent

    def prior(name):
        value = json.loads((root / f"schemas/{name}.schema.json").read_text(encoding="utf-8"))
        return {key: item for key, item in value.items() if key not in {"$id", "$schema"}}

    sync_run = prior("s2-sync-run")
    uuid = sync_run["properties"]["id"]
    sha = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    index_ref = obj({"index_run_id": uuid})
    build = obj({"source_id": {"const": "D12"}, "acquisition_id": uuid})
    listing = prior("s2-sync-list")
    listing["properties"]["task_kind"] = {"const": "source_index"}
    listing["required"].append("task_kind")
    save("s3-index-build", build)
    save("s3-index-ref", index_ref)
    save("s3-index-list", listing)
    for name, new in [("scoped-job-ref", index_ref), ("scoped-job-list", listing)]:
        schema = prior(f"s2-{name}")
        schema["oneOf"].append(new)
        save(f"s3-{name}", schema)

    result = obj({"index_id": uuid, "state": {"const": "INDEXED"}, "searchable": {"const": False},
                  "identity_sha256": sha, "manifest_sha256": sha,
                  "counts": {"type": "object"}, "artifact_bytes": {"type": "integer", "minimum": 0},
                  "quality": {"type": "object"}})
    properties = {key: value for key, value in sync_run["properties"].items()
                  if key not in {"connector_id", "source_revision", "result", "stage"}}
    properties.update({"acquisition_id": uuid,
                       "recipe": obj({"id": {"type": "string", "minLength": 1}, "sha256": sha}),
                       "stage": {"enum": ["QUEUED", "FETCHING", "INDEXING", "VERIFYING", "STORING", "INDEXED", "FAILED", "CANCELLED"]},
                       "result": {"oneOf": [{"type": "null"}, result]}})
    run = obj(properties)
    run["allOf"] = [{"if": {"properties": {"state": {"const": "SUCCEEDED"}}},
                     "then": {"properties": {"result": result, "stage": {"const": "INDEXED"}, "error": {"type": "null"}}},
                     "else": {"properties": {"result": {"type": "null"}}}}]
    save("s3-index-run", run)
    save("s3-index-action", obj({"action_id": uuid, "index_run_id": uuid, "job_id": uuid,
                                 "state": properties["state"], "existing": {"type": "boolean"}, "run": run}))
    save("s3-index-run-list", obj({"items": {"type": "array", "items": run},
                                   "total": {"type": "integer", "minimum": 0},
                                   "next_cursor": {"type": ["string", "null"]},
                                   "allowed_actions": obj({"start": {"type": "boolean"}})}))
    inventory = {"stage": "S3", "available_tools": [], "tool_production_authorization": "not_accepted",
                 "coverage": [{"capability_id": name, "input_schema": f"schemas/s3-{schema}.schema.json",
                               "scope_kind": "platform", "manual_http": "scoped_http_private_index_accepted",
                               "tool_availability": "planned", "adapter": "explicit_contract_test_only"}
                              for name, schema in S3_INPUTS.items()],
                 "limits": ["D12 fixed acquisition and server recipe only; no paths, URLs or model-supplied authority.",
                            "INDEXED is a private artifact, not READY, searchable, licensed, published or mounted.",
                            "Platform jobs.list uses source_id=D12 and task_kind=source_index for indexes; omitting task_kind retains sync semantics.",
                            "Platform jobs.get/cancel/retry require exactly one of index_run_id or sync_run_id; project job_id remains separate.",
                            "Successful identity reuse returns existing=true; physical reuse does not grant access.",
                            "Scoped HTTP/browser acceptance is recorded in results/2026-10-16-s3-index-contracts.json; formal query performance remains unaccepted."]}
    (root / "s3-capabilities.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
