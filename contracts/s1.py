"""Narrow S1 HTTP contracts; production Pi delegation remains unavailable."""

import json
from pathlib import Path

S1_INPUTS = {
    "account.get": "empty", "projects.list": "empty", "projects.get": "empty",
    "projects.create": "project-create", "members.list": "empty", "members.update": "member-update",
    "members.remove": "member-remove", "uploads.create": "upload-create", "uploads.complete": "upload-complete",
    "jobs.list": "job-list", "jobs.get": "job-id", "jobs.cancel": "job-id", "jobs.retry": "job-id",
    "sources.list": "source-list", "sources.get": "source-id", "sources.versions": "source-versions",
    "catalog.create": "catalog-create", "catalog.update": "catalog-update",
}


def build_s1(save, obj):
    from contracts.catalog import (
        SOURCE_ID_PATTERN,
        CatalogCreate,
        CatalogUpdate,
        SourceList,
        SourceVersionList,
        SourceView,
    )

    source_id = {"type": "string", "pattern": SOURCE_ID_PATTERN}
    pagination = {"cursor": {"type": "string", "maxLength": 512}, "page_size": {"type": "integer", "minimum": 1, "maximum": 100}}
    save("s1-source-id", obj({"source_id": source_id}))
    save("s1-source-versions", obj({"source_id": source_id, **pagination}, ["source_id"]))
    save("s1-source-list", obj({"q": {"type": "string", "maxLength": 160},
        "language": {"type": "string", "maxLength": 48}, "category": {"type": "string", "maxLength": 48},
        "status": {"enum": ["catalog_only", "verification_pending", "experimental_evidence"]},
        "capability": {"enum": ["discover", "remote_query", "fulltext_analysis", "export", "model_egress"]}, **pagination}, []))
    save("s1-catalog-create", CatalogCreate.model_json_schema())
    update = CatalogUpdate.model_json_schema()
    update["properties"]["source_id"] = source_id
    update["required"].append("source_id")
    save("s1-catalog-update", update)
    for name, model in [("source-view", SourceView), ("source-list-result", SourceList), ("source-versions-result", SourceVersionList)]:
        save(f"s1-{name}", model.model_json_schema())
    identifier = {"type": "string", "minLength": 1, "maxLength": 200}
    integer = {"type": "integer", "minimum": 0}
    timestamp = {"type": "string", "format": "date-time"}
    job_state = {"enum": ["QUEUED", "RUNNING", "CANCEL_REQUESTED", "CANCELLED", "SUCCEEDED", "FAILED"]}
    media = {"enum": ["text/plain", "text/csv", "text/tab-separated-values", "application/json", "application/x-ndjson"]}
    sha = {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"}
    save("s1-empty", obj({}))
    save("s1-project-create", obj({"name": {"type": "string", "minLength": 1, "maxLength": 160}}))
    save("s1-member-update", obj({"user_id": identifier, "role": {"enum": ["editor", "viewer"]}}))
    save("s1-member-remove", obj({"user_id": identifier}))
    save("s1-upload-create", obj({"filename": {"type": "string", "minLength": 1, "maxLength": 255},
                                 "size": {"type": "integer", "minimum": 1}, "media_type": media, "sha256": sha}))
    save("s1-upload-complete", obj({"upload_id": identifier}))
    save("s1-job-id", obj({"job_id": identifier}))
    save("s1-job-list", obj({"cursor": identifier}, []))
    # Business actions do not require a Pi invocation. The optional linkage is host-owned.
    action = obj({"action_id": identifier, "project_id": identifier, "actor_id": identifier,
                  "operation": {"enum": ["uploads.create", "uploads.complete", "jobs.cancel", "jobs.retry"]},
                  "idempotency_key": identifier, "request_sha256": sha,
                  "agent": {"oneOf": [{"type": "null"}, obj({"invocation_id": identifier, "run_id": identifier})]}})
    action["$comment"] = "Actor and optional agent linkage are trusted ledger fields, never client-authorized identity. Manual actions do not require agent linkage; internal host execution records its own trusted invocation/run linkage."
    save("s1-action", action)
    result = obj({"state": {"const": "VALIDATED"}, "size": integer, "sha256": sha, "upload_id": identifier,
                  "validation": {"const": "utf8-text-and-integrity/v1"}})
    small_error = obj({"code": identifier, "message": {"type": "string"}, "retryable": {"type": "boolean"}})
    job = obj({
        "job_id": identifier, "project_id": identifier, "actor_id": identifier, "action_id": identifier,
        "upload_id": identifier, "filename": {"type": "string"}, "kind": {"const": "UPLOAD_VALIDATE"}, "state": job_state,
        "stage": {"enum": ["queued", "validating", "validated", "failed", "cancelled"]},
        "attempt": {"type": "integer", "minimum": 1, "maximum": 3}, "lease_epoch": integer,
        "lease_expires_at": {"type": ["string", "null"], "format": "date-time"},
        "progress": obj({"processed_bytes": integer, "total_bytes": {"type": ["integer", "null"], "minimum": 0}}),
        "error": {"oneOf": [{"type": "null"}, small_error]},
        "result": {"oneOf": [{"type": "null"}, result]},
        "result_ref": {"oneOf": [{"type": "null"}, obj({"upload_id": identifier, "state": {"const": "VALIDATED"}})]},
        "allowed_actions": {"type": "array", "items": {"enum": ["cancel", "retry"]}, "uniqueItems": True},
        "created_at": timestamp, "updated_at": timestamp,
    })
    job["allOf"] = [
        {"if": {"properties": {"state": {"const": "SUCCEEDED"}}},
         "then": {"properties": {"result": result, "error": {"type": "null"}, "result_ref": {"type": "object"}}},
         "else": {"properties": {"result": {"type": "null"}, "result_ref": {"type": "null"}}}},
        {"if": {"properties": {"state": {"const": "FAILED"}}}, "then": {"properties": {"error": small_error}}},
    ]
    import copy
    import_job = copy.deepcopy(job)
    import_result = obj({"material_id": identifier, "material_revision_id": identifier, "state": {"const": "READY"}})
    import_job["properties"].update({
        "kind": {"const": "TXT_IMPORT"},
        "stage": {"enum": ["QUEUED", "FETCHING", "PARSING", "STORING", "COMPLETE", "FAILED", "CANCELLED"]},
        "progress": obj({"processed_bytes": integer, "total_bytes": {"type": ["integer", "null"], "minimum": 0}, "processed_records": integer, "total_records": {"type": ["integer", "null"], "minimum": 0}, "file_name": {"type": ["string", "null"]}}),
        "result": {"oneOf": [{"type": "null"}, import_result]},
        "result_ref": {"oneOf": [{"type": "null"}, obj({"material_revision_id": identifier, "state": {"const": "READY"}})]},
    })
    import_job["allOf"][0]["then"]["properties"]["result"] = import_result
    export_job = copy.deepcopy(import_job)
    export_result = obj({"export_id": identifier, "state": {"const": "READY"}})
    export_job["properties"].update({
        "kind": {"const": "EXPORT"}, "upload_id": {"type": "null"}, "filename": {"type": "null"},
        "stage": {"enum": ["QUEUED", "EXPORTING", "STORING", "COMPLETE", "FAILED", "CANCELLED"]},
        "result": {"oneOf": [{"type": "null"}, export_result]},
        "result_ref": {"oneOf": [{"type": "null"}, export_result]},
    })
    export_job["allOf"][0]["then"]["properties"]["result"] = export_result
    save("s1-job", {"oneOf": [job, import_job, export_job]})
    save("job-event", obj({"event_id": identifier, "job_id": identifier,
                           "sequence": {"type": "integer", "minimum": 1}, "kind": identifier,
                           "state": job_state, "attempt": {"type": "integer", "minimum": 1},
                           "payload": {"type": "object"}, "created_at": timestamp}))
    save("s1-attempt", obj({"job_id": identifier, "number": {"type": "integer", "minimum": 1},
                            "state": job_state, "lease_epoch": integer,
                            "started_at": {"type": ["string", "null"], "format": "date-time"},
                            "finished_at": {"type": ["string", "null"], "format": "date-time"}}))
    save("s1-accepted-upload", obj({"status": {"const": "accepted"}, "action_id": identifier,
                                    "job_id": identifier, "upload_id": identifier, "state": job_state,
                                    "result_ref": {"type": "null"}}))
    inventory = {"stage": "S1", "tool_production_authorization": "not_accepted", "available_tools": [],
                 "typed_client": "contracts/types/s1.ts", "adapter": "services/agent-runtime/src/s1-tools.ts",
                 "coverage": [{"capability_id": name, "input_schema": f"schemas/s1-{schema}.schema.json",
                               "manual_http": "implemented", "adapter": "explicit_contract_test_only",
                               "tool_availability": "planned"} for name, schema in S1_INPUTS.items()],
                 "limitations": ["Internal host credential, invocation/run ledger and completed linear checkpoint restore have separate evidence; real-model execution, material egress, in-flight and full asynchronous recovery remain unaccepted.",
                                  "Source catalog metadata and experimental evidence do not grant production analysis, release publication or license approval.",
                                  "Project create has no idempotency ledger and must not be automatically retried.",
                                  "members.update only upserts existing account IDs; email invitations are not implemented.",
                                  "Upload success means file validation only, not parsing or a searchable snapshot."]}
    (Path(__file__).parent / "s1-capabilities.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
