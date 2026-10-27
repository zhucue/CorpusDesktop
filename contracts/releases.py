"""Fixed acquisition approval, immutable publication and project whole-source mounts."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictView(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecipeView(StrictView):
    id: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class IndexCounts(StrictView):
    sentences: int = Field(ge=0)
    cmn_sentences: int = Field(ge=0)
    eng_sentences: int = Field(ge=0)
    characters: int = Field(ge=0)
    tokens: int = Field(ge=0)
    direct_edges: int = Field(ge=0)
    unknown_owner: int = Field(ge=0)


class IndexQuality(StrictView):
    all_source_sentences_indexed: bool
    rejected_sentences: int = Field(ge=0)
    token_roundtrip_verified: bool
    attributes: list[Literal["form"]]
    document_count_unit: Literal["imported_sentence_record"]
    normalization: Literal["none"]


class PolicyView(StrictView):
    source_id: str
    acquisition_id: UUID
    revision: int = Field(ge=0)
    decision: Literal["unknown", "allow", "deny"]
    policy_id: UUID | None
    source_identity: dict[str, Any]
    source_identity_revision: int
    identity_current: bool
    acquisition_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    license_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    license: dict[str, Any]
    quality: dict[str, Any]
    review_note: str | None
    evidence_urls: list[str]
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    scope: Literal["internal_research"]
    export_decision: Literal["allow", "deny"]
    export: bool
    model_egress: Literal[False]


class ReleaseView(StrictView):
    release_id: UUID
    source_id: str
    source_snapshot_id: UUID
    index_id: UUID
    acquisition_id: UUID
    version: str
    published_at: datetime
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    index_identity_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    recipe: RecipeView
    counts: IndexCounts
    quality: IndexQuality
    policy_revision: int = Field(ge=1)
    current_policy_revision: int = Field(ge=0)
    state: Literal["PUBLISHED"]
    searchable: bool
    available: bool
    unavailable_reason: str | None


class MountActions(StrictView):
    read_manifest: bool
    remove: bool


class MountView(StrictView):
    id: UUID
    project_id: UUID
    created_at: datetime
    removed_at: datetime | None
    state: Literal["ACTIVE", "REMOVED"]
    release: ReleaseView
    allowed_actions: MountActions


class PolicyAction(StrictView):
    action_id: UUID
    policy: PolicyView


class ReleaseAction(StrictView):
    action_id: UUID
    existing: bool
    release: ReleaseView


class MountAction(StrictView):
    action_id: UUID
    existing: bool
    mount: MountView


class MountListActions(StrictView):
    create: bool


class MountList(StrictView):
    items: list[MountView]
    total: int = Field(ge=0)
    next_cursor: str | None
    allowed_actions: MountListActions


class MountManifest(StrictView):
    mount_id: UUID
    source_snapshot_id: UUID
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest: dict[str, Any]


RELEASE_INPUTS = {
    "policies.get": "policy-ref", "policies.update": "policy-update",
    "releases.publish": "publish", "releases.get": "release-ref",
    "mounts.list": "mount-list", "mounts.get": "mount-ref",
    "mounts.manifest": "mount-ref", "mounts.create": "mount-create",
    "mounts.remove": "mount-ref",
}


def build_releases(save, obj):
    uuid = {"type": "string", "pattern": r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"}
    source = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"}
    policy_ref = {"policy_kind": {"const": "source"}, "source_id": source, "acquisition_id": uuid}
    update = {"expected_revision": {"type": "integer", "minimum": 0},
              "decision": {"enum": ["allow", "deny"]},
              "review_note": {"type": "string", "minLength": 1, "maxLength": 4000},
              "evidence_urls": {"type": "array", "minItems": 1, "maxItems": 12,
                                "items": {"type": "string", "pattern": "^https?://", "maxLength": 2048}}}
    manual_update = {**update, "export_decision": {"enum": ["allow", "deny"], "default": "deny"}}
    save("s3-release-policy-manual-update", obj(manual_update, list(update)))
    inputs = {"policy-ref": obj(policy_ref), "policy-update": obj({**policy_ref, **update}),
              "publish": obj({"source_id": source, "index_id": uuid, "expected_policy_revision": {"type": "integer", "minimum": 1}}),
              "release-ref": obj({"source_id": source, "release_id": uuid}),
              "mount-list": obj({"cursor": {"type": "string", "maxLength": 512}, "page_size": {"type": "integer", "minimum": 1, "maximum": 100}}, []),
              "mount-ref": obj({"mount_id": uuid}), "mount-create": obj({"source_snapshot_id": uuid})}
    for name, value in inputs.items():
        save(f"s3-release-{name}", value)
    for name, model in [("policy", PolicyView), ("view", ReleaseView), ("mount", MountView)]:
        save(f"s3-release-{name}", model.model_json_schema())
    release = ReleaseView.model_json_schema()
    mount = MountView.model_json_schema()
    # Nested Pydantic schemas retain local definitions at their document root.
    def envelope(properties, nested):
        defs = nested.pop("$defs", {})
        value = obj(properties)
        if defs:
            value["$defs"] = defs
        return value
    save("s3-release-action", envelope({"action_id": uuid, "existing": {"type": "boolean"}, "release": release}, release))
    policy = PolicyView.model_json_schema()
    save("s3-release-policy-action", envelope({"action_id": uuid, "policy": policy}, policy))
    save("s3-release-mount-action", envelope({"action_id": uuid, "existing": {"type": "boolean"}, "mount": mount}, mount))
    mount = MountView.model_json_schema()
    save("s3-release-mounts", envelope({"items": {"type": "array", "items": mount}, "total": {"type": "integer", "minimum": 0}, "next_cursor": {"type": ["string", "null"]}, "allowed_actions": obj({"create": {"type": "boolean"}})}, mount))
    save("s3-release-manifest", obj({"mount_id": uuid, "source_snapshot_id": uuid, "manifest_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}, "manifest": {"type": "object"}}))
    inventory = {"stage": "S3", "available_tools": [], "runtime_tool_schema": "s3-release-tools-v1",
                 "tool_production_authorization": "not_accepted",
                 "coverage": [{"capability_id": name, "input_schema": f"schemas/s3-release-{schema}.schema.json",
                               "scope_kind": ["account", "platform", "project"] if name == "releases.get" else ["project"] if name.startswith("mounts.") else ["platform"],
                               "manual_http": "scoped_fixture_http_mounts_accepted", "tool_availability": "planned"}
                              for name, schema in RELEASE_INPUTS.items()],
                 "limits": ["Acquisition-specific internal-research approval never grants export or model egress, or approves another acquisition.",
                            "Catalog-wide license remains pending; publication and mounting do not open a public query endpoint.",
                            "Mount writes bind the current project; whole fixed snapshots only, no filters, URL, recipe or model identity.",
                            "Current policy, source identity and project authority must be rechecked by the backend, including replay/context reuse.",
                            "s3-tools-v1 checkpoints are incompatible; no silent restoration under s3-release-tools-v1.",
                            "Synthetic-fixture approval is not approval of real D12 data."]}
    (Path(__file__).parent / "s3-release-capabilities.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
