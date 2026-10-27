"""Fixed evidence, immutable note revisions and authorized complete exports.

Material-bearing HTTP models are not model-egress authorization. Agent adapters
must use explicit metadata projections or reject the operation.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from contracts.releases import RecipeView, StrictView
from contracts.research import (
    ContextView,
    Count,
    Digest,
    HitRef,
    QueryAST,
    QueryCounts,
    ResearchError,
    ResearchProgress,
    RunState,
)

UniqueIDs = Annotated[
    list[UUID], Field(max_length=100, json_schema_extra={"uniqueItems": True})
]
QueryIDs = Annotated[
    list[UUID], Field(max_length=16, json_schema_extra={"uniqueItems": True})
]


class EvidenceInput(StrictView):
    result_set_id: UUID
    ordinal: Count


class QueryMethod(StrictView):
    query_run_id: UUID
    result_set_id: UUID
    snapshot_id: UUID
    query: QueryAST
    query_sha256: Digest
    recipe: RecipeView
    counts: QueryCounts
    result_sha256: Digest
    index_identity_sha256: Digest

    @model_validator(mode="after")
    def complete_result(self):
        if self.counts.count_state != "complete":
            raise ValueError("Evidence requires complete query counts")
        return self


class EvidenceSummary(StrictView):
    id: UUID
    project_id: UUID
    created_by: UUID
    created_at: datetime
    query_run_id: UUID
    result_set_id: UUID
    snapshot_id: UUID
    hit_ref: HitRef

    @model_validator(mode="after")
    def fixed_result(self):
        if self.hit_ref.result_set_id != self.result_set_id:
            raise ValueError("Evidence hit must reference its fixed result")
        return self


class EvidenceView(EvidenceSummary):
    context: ContextView
    method: QueryMethod
    context_sha256: Digest

    @model_validator(mode="after")
    def fixed_context(self):
        if (
            self.context.project_id != self.project_id
            or self.context.snapshot_id != self.snapshot_id
            or self.context.hit_ref != self.hit_ref
            or self.method.query_run_id != self.query_run_id
            or self.method.result_set_id != self.result_set_id
            or self.method.snapshot_id != self.snapshot_id
        ):
            raise ValueError("Evidence context and method must share fixed identity")
        return self


class CreateAction(StrictView):
    create: bool


class EvidenceList(StrictView):
    items: list[EvidenceSummary]
    total: Count
    next_cursor: str | None
    allowed_actions: CreateAction


class EvidenceAction(StrictView):
    action_id: UUID
    existing: bool
    evidence: EvidenceView


class NoteInput(StrictView):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=100000)
    evidence_ids: UniqueIDs = Field(default_factory=list)
    query_run_ids: QueryIDs = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_references(self):
        if any(
            len(values) != len(set(values))
            for values in (self.evidence_ids, self.query_run_ids)
        ):
            raise ValueError("References must be unique")
        if len(self.evidence_ids) + len(self.query_run_ids) > 100:
            raise ValueError("At most one hundred authorization references")
        return self


class NoteUpdate(NoteInput):
    expected_revision: int = Field(ge=1)


class NoteAccept(StrictView):
    expected_revision: int = Field(ge=1)


class NoteActions(StrictView):
    update: bool
    accept: bool
    export: bool


class NoteSummary(StrictView):
    id: UUID
    project_id: UUID
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    evidence_ids: UniqueIDs
    query_run_ids: QueryIDs
    authorization_evidence_ids: UniqueIDs
    authorization_query_run_ids: UniqueIDs
    status: Literal["draft", "accepted"]
    accepted_by: UUID | None
    accepted_at: datetime | None
    allowed_actions: NoteActions

    @model_validator(mode="after")
    def authorization_and_acceptance(self):
        values = (
            self.evidence_ids,
            self.query_run_ids,
            self.authorization_evidence_ids,
            self.authorization_query_run_ids,
        )
        if any(len(v) != len(set(v)) for v in values):
            raise ValueError("References must be unique")
        if (
            not set(self.evidence_ids) <= set(self.authorization_evidence_ids)
            or not set(self.query_run_ids) <= set(self.authorization_query_run_ids)
            or len(self.authorization_evidence_ids)
            + len(self.authorization_query_run_ids) > 100
        ):
            raise ValueError("Authorization must retain every displayed dependency")
        if self.status == "accepted":
            if self.accepted_by is None or self.accepted_at is None:
                raise ValueError("Accepted revisions require a recorded human actor")
        elif self.accepted_by is not None or self.accepted_at is not None:
            raise ValueError("Draft revisions cannot inherit human acceptance")
        return self


class NoteView(NoteSummary):
    body: str = Field(min_length=1, max_length=100000)


class NoteList(StrictView):
    items: list[NoteSummary]
    total: Count
    next_cursor: str | None
    allowed_actions: CreateAction


class NoteAction(StrictView):
    action_id: UUID
    note: NoteView


class QueryExportTarget(StrictView):
    kind: Literal["query_runs"]
    query_run_ids: list[UUID] = Field(
        min_length=1, max_length=16, json_schema_extra={"uniqueItems": True}
    )

    @model_validator(mode="after")
    def distinct_runs(self):
        if len(set(self.query_run_ids)) != len(self.query_run_ids):
            raise ValueError("Export query runs must be unique")
        return self


class NoteExportTarget(StrictView):
    kind: Literal["note_revision"]
    note_id: UUID
    revision: int = Field(ge=1)


ExportTarget = Annotated[
    QueryExportTarget | NoteExportTarget, Field(discriminator="kind")
]


class ExportInput(StrictView):
    target: ExportTarget
    format: Literal["csv", "json"]


class ExportResult(StrictView):
    filename: str = Field(min_length=1)
    media_type: Literal["application/zip", "application/json"]
    container: Literal["zip", "file"]
    byte_size: Count
    sha256: Digest
    manifest_sha256: Digest
    row_count: Count


class ExportActions(StrictView):
    cancel: bool
    retry: bool
    download: bool


class ExportView(StrictView):
    id: UUID
    job_id: UUID
    project_id: UUID
    actor_id: UUID
    target: ExportTarget
    format: Literal["csv", "json"]
    state: RunState
    stage: Literal["QUEUED", "EXPORTING", "STORING", "COMPLETE", "FAILED", "CANCELLED"]
    attempt: int = Field(ge=0)
    progress: ResearchProgress
    error: ResearchError | None
    result: ExportResult | None
    created_at: datetime
    updated_at: datetime
    allowed_actions: ExportActions

    @model_validator(mode="after")
    def fixed_export(self):
        if self.id != self.job_id:
            raise ValueError("Export identity is its durable job identity")
        if (self.state == "SUCCEEDED") != (self.result is not None):
            raise ValueError("Only successful exports have a published artifact")
        if self.result is not None:
            expected = (
                ("zip", "application/zip", ".zip")
                if self.format == "csv"
                else ("file", "application/json", ".json")
            )
            if (
                (self.result.container, self.result.media_type) != expected[:2]
                or not self.result.filename.endswith(expected[2])
            ):
                raise ValueError("Export format and actual artifact type must agree")
        return self


class ExportAction(StrictView):
    action_id: UUID
    export_id: UUID
    job_id: UUID
    state: RunState
    run: ExportView

    @model_validator(mode="after")
    def same_job(self):
        if (
            self.export_id != self.job_id
            or self.run.id != self.export_id
            or self.run.state != self.state
        ):
            raise ValueError("Export action must identify its actual job")
        return self


class ExportList(StrictView):
    items: list[ExportView]
    total: Count
    next_cursor: str | None


OUTCOME_INPUTS = {
    "evidence.create": "evidence-create",
    "evidence.list": "list-input",
    "evidence.get": "evidence-ref",
    "notes.list": "list-input",
    "notes.get": "note-ref",
    "notes.create": "note-create",
    "notes.update": "note-update-tool",
    "notes.accept": "note-accept-tool",
    "exports.create": "export-create",
    "exports.list": "list-input",
    "exports.get": "export-ref",
}


def build_outcomes(save, obj):
    for name, model in [
        ("evidence-create", EvidenceInput),
        ("evidence", EvidenceView),
        ("evidence-action", EvidenceAction),
        ("evidence-list", EvidenceList),
        ("note-create", NoteInput),
        ("note-update", NoteUpdate),
        ("note-accept", NoteAccept),
        ("note", NoteView),
        ("note-action", NoteAction),
        ("note-list", NoteList),
        ("export-create", ExportInput),
        ("export", ExportView),
        ("export-action", ExportAction),
        ("export-list", ExportList),
    ]:
        save(f"s3-outcomes-{name}", model.model_json_schema())
    uuid = {"type": "string", "format": "uuid"}
    save("s3-outcomes-evidence-ref", obj({"evidence_id": uuid}))
    save("s3-outcomes-export-ref", obj({"export_id": uuid}))
    save(
        "s3-outcomes-note-ref",
        obj({"note_id": uuid, "revision": {"type": "integer", "minimum": 1}}, ["note_id"]),
    )
    for name, model in [("note-update-tool", NoteUpdate), ("note-accept-tool", NoteAccept)]:
        schema = model.model_json_schema()
        schema["properties"]["note_id"] = uuid
        schema["required"].append("note_id")
        save(f"s3-outcomes-{name}", schema)
    save(
        "s3-outcomes-list-input",
        obj(
            {"cursor": {"type": "string", "minLength": 1},
             "page_size": {"type": "integer", "minimum": 1, "maximum": 100}},
            [],
        ),
    )
    (Path(__file__).parent / "s3-outcomes-capabilities.json").write_text(
        json.dumps(
            {"stage": "S3", "runtime_tool_schema": "s3-outcomes-tools-v1",
             "manual_http": "scoped_http_and_browser_accepted", "available_tools": [],
             "acceptance": "results/2026-10-17-s3-outcomes-contracts.json; 11 captured HTTP response families and scoped browser acceptance; unsaved-leave dialog interaction remains unverified",
             "coverage": [{"capability_id": name,
                           "input_schema": f"schemas/s3-outcomes-{schema}.schema.json",
                           "scope_kind": ["project"], "tool_availability": "planned"}
                          for name, schema in OUTCOME_INPUTS.items()],
             "limits": ["Evidence is explicitly registered from a complete fixed hit.",
                        "Note revisions retain inherited authorization dependencies.",
                        "CSV is a ZIP with results.csv and methods.json; JSON preserves text.",
                        "Shared export permission is independently approved per acquisition.",
                        "No material-bearing Pi scope or production model egress is enabled."]},
            ensure_ascii=False, indent=2,
        ) + "\n", encoding="utf-8",
    )
