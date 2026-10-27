"""Fixed project research snapshots and material-bearing manual query contracts.

These response models do not authorize material egress to a model. Pi adapters
return a separate metadata projection while material scope remains unsupported.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from contracts.releases import IndexCounts, RecipeView, StrictView
from contracts.semantics import validate_query_semantics

Count = Annotated[int, Field(ge=0)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
RunState = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
Sort = tuple[Literal["document_ordinal"], Literal["start"], Literal["end"]]


class LiteralPattern(StrictView):
    type: Literal["literal"]
    value: str = Field(min_length=1)


class TermPattern(StrictView):
    type: Literal["term"]
    attr: Literal["form"]
    op: Literal["eq"]
    value: str = Field(min_length=1, max_length=1024)


class GapPattern(StrictView):
    type: Literal["gap"]
    min: Count
    max: Count


class CharacterSequence(StrictView):
    type: Literal["sequence"]
    items: list[LiteralPattern | GapPattern] = Field(min_length=2)


class TokenSequence(StrictView):
    type: Literal["sequence"]
    items: list[TermPattern | GapPattern] = Field(min_length=2)


class CharacterUnion(StrictView):
    type: Literal["any_of"]
    patterns: list[LiteralPattern | CharacterSequence] = Field(min_length=2)


class TokenUnion(StrictView):
    type: Literal["any_of"]
    patterns: list[TermPattern | TokenSequence] = Field(min_length=2)


class QueryBase(StrictView):
    dsl_version: Literal["corpus-query/v1"]
    within: Literal["sentence"]
    overlap: Literal["all"]
    normalization: Literal["none"] = "none"
    sort: Sort = ("document_ordinal", "start", "end")

    @model_validator(mode="after")
    def valid_gaps(self):
        validate_query_semantics(self.model_dump())
        return self


class CharacterQuery(QueryBase):
    unit: Literal["character"]
    pattern: LiteralPattern | CharacterSequence | CharacterUnion


class TokenQuery(QueryBase):
    unit: Literal["token"]
    pattern: TermPattern | TokenSequence | TokenUnion


QueryAST = Annotated[CharacterQuery | TokenQuery, Field(discriminator="unit")]


class SnapshotInput(StrictView):
    mount_ids: list[UUID] = Field(
        default_factory=list, max_length=16, json_schema_extra={"uniqueItems": True}
    )
    material_revision_ids: list[UUID] = Field(
        default_factory=list, max_length=16, json_schema_extra={"uniqueItems": True}
    )

    @model_validator(mode="after")
    def valid_members(self):
        if not 1 <= len(self.mount_ids) + len(self.material_revision_ids) <= 16:
            raise ValueError("Select between one and sixteen fixed members")
        if len(set(self.mount_ids)) != len(self.mount_ids) or len(
            set(self.material_revision_ids)
        ) != len(self.material_revision_ids):
            raise ValueError("Duplicate fixed members are not allowed")
        return self


class QueryInput(StrictView):
    snapshot_id: UUID
    query: QueryAST
    page_size: int = Field(default=50, ge=1, le=50)
    context_codepoints: int = Field(default=40, ge=0, le=200)


class ResearchProgress(StrictView):
    processed_bytes: Count
    total_bytes: Count | None
    processed_records: Count
    total_records: Count | None
    file_name: str | None


class ResearchError(StrictView):
    code: str
    message: str
    retryable: bool


class QueryCapabilities(StrictView):
    character: Literal[True]
    token_form: Literal[True]
    lemma: Literal[False]
    upos: Literal[False]
    regex: Literal[False]
    within: list[Literal["sentence"]] = Field(min_length=1, max_length=1)
    context_unit: Literal["codepoint"]


class SourceSnapshotMember(StrictView):
    kind: Literal["whole_source_mount"]
    mount_id: UUID
    source_id: str
    source_snapshot_id: UUID
    release_id: UUID
    index_id: UUID
    index_identity_sha256: Digest
    ordered_members_sha256: Digest
    recipe: RecipeView


class PrivateSnapshotMember(StrictView):
    kind: Literal["private_revision"]
    material_id: UUID
    material_revision_id: UUID
    revision: int = Field(ge=1)
    language: Literal["cmn", "eng"]
    manifest_sha256: Digest
    canonical_sha256: Digest
    recipe: RecipeView


SnapshotMember = Annotated[
    SourceSnapshotMember | PrivateSnapshotMember, Field(discriminator="kind")
]


class DocumentUnits(StrictView):
    source_records: Count
    private_files: Count


class SnapshotCounts(IndexCounts):
    documents: Count
    document_units: DocumentUnits

    @model_validator(mode="after")
    def exact_document_sum(self):
        if (
            self.documents
            != self.document_units.source_records + self.document_units.private_files
        ):
            raise ValueError("Document total must equal the explicit unit breakdown")
        return self


class SnapshotActions(StrictView):
    retry: bool


class SnapshotView(StrictView):
    id: UUID
    project_id: UUID
    name: str
    job_id: UUID
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    state: Literal["PREPARING", "READY", "FAILED"]
    available: bool
    unavailable_reason: str | None
    manifest_sha256: Digest
    members: list[SnapshotMember] = Field(min_length=1, max_length=16)
    index_kind: Literal["source_reuse", "project"]
    counts: SnapshotCounts | None
    query_capabilities: QueryCapabilities
    progress: ResearchProgress
    error: ResearchError | None
    allowed_actions: SnapshotActions


class SnapshotAction(StrictView):
    action_id: UUID
    existing: bool
    job_id: UUID
    snapshot: SnapshotView


class SnapshotListActions(StrictView):
    create: bool


class SnapshotList(StrictView):
    items: list[SnapshotView]
    total: Count
    next_cursor: str | None
    allowed_actions: SnapshotListActions


class QueryActions(StrictView):
    cancel: bool
    retry: bool
    prepare: bool


class QueryCounts(StrictView):
    count_state: Literal["pending", "complete", "failed"]
    total_hits: Count | None
    matched_segments: Count | None
    matched_documents: Count | None
    document_count_unit: Literal[
        "imported_sentence_record", "uploaded_file", "mixed_document_units"
    ]
    matched_document_units: DocumentUnits | None

    @model_validator(mode="after")
    def complete_counts_only(self):
        values = (self.total_hits, self.matched_segments, self.matched_documents)
        if self.count_state == "complete" and any(value is None for value in values):
            raise ValueError("Complete results require all three counts")
        if self.count_state != "complete" and any(
            value is not None for value in values
        ):
            raise ValueError("Incomplete results must not claim complete counts")
        units = self.matched_document_units
        if self.count_state == "complete":
            if (
                units is None
                or units.source_records + units.private_files != self.matched_documents
            ):
                raise ValueError(
                    "Complete document counts require an exact unit breakdown"
                )
            if (
                self.document_count_unit == "imported_sentence_record"
                and units.private_files
            ):
                raise ValueError("Source-only counts cannot contain private files")
            if self.document_count_unit == "uploaded_file" and units.source_records:
                raise ValueError("Private-only counts cannot contain source records")
        elif units is not None:
            raise ValueError("Incomplete document breakdown must be null")
        return self


class QueryRunView(QueryCounts):
    id: UUID
    project_id: UUID
    snapshot_id: UUID
    result_set_id: UUID
    actor_id: UUID
    name: str
    query: QueryAST
    query_sha256: Digest
    recipe: RecipeView
    sort: Sort
    context_codepoints: int = Field(ge=0, le=200)
    page_size: int = Field(ge=1, le=50)
    state: RunState
    stage: Literal[
        "QUEUED",
        "FIRST_PAGE",
        "FULL_RESULT",
        "PREPARING_CACHE",
        "COMPLETE",
        "FAILED",
        "CANCELLED",
    ]
    attempt: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    first_page_state: Literal["pending", "ready", "failed"]
    prepare_state: Literal["idle", "pending", "ready", "failed"]
    progress: ResearchProgress
    error: ResearchError | None
    allowed_actions: QueryActions


class QueryAction(StrictView):
    action_id: UUID
    job_id: UUID
    query_run_id: UUID
    result_set_id: UUID
    state: RunState
    run: QueryRunView


class QueryList(StrictView):
    items: list[QueryRunView]
    total: Count
    next_cursor: str | None


class HitRef(StrictView):
    result_set_id: UUID
    ordinal: Count


class HitCoordinates(StrictView):
    hit_ref: HitRef
    revision_id: str
    segment_id: str
    origin_kind: Literal["source", "private"]
    document_id: str = Field(min_length=1)
    document_name: str
    material_id: UUID | None
    material_revision_id: UUID | None
    source_id: str | None
    source_sentence_id: str | None
    context_start_cp: Count
    start_cp: Count
    end_cp: Count
    token_start: Count | None
    token_end: Count | None
    global_token_start: Count | None
    global_token_end: Count | None
    source_url: str | None
    evidence_id: None

    @model_validator(mode="after")
    def ordered_coordinates(self):
        if self.start_cp < self.context_start_cp:
            raise ValueError("Hit cannot precede the returned context")
        if self.origin_kind == "private":
            if (
                any(
                    value is not None
                    for value in (
                        self.source_id,
                        self.source_sentence_id,
                        self.source_url,
                    )
                )
                or self.material_id is None
                or self.material_revision_id is None
            ):
                raise ValueError(
                    "Private hits require fixed material identity and no invented source"
                )
        elif (
            any(
                value is None
                for value in (self.source_id, self.source_sentence_id, self.source_url)
            )
            or self.material_id is not None
            or self.material_revision_id is not None
            or self.context_start_cp != 0
        ):
            raise ValueError("Source hits require original source identity")
        if self.end_cp <= self.start_cp:
            raise ValueError("Hit requires a nonempty half-open codepoint span")
        values = (
            self.token_start,
            self.token_end,
            self.global_token_start,
            self.global_token_end,
        )
        if any(value is not None for value in values):
            if any(value is None for value in values):
                raise ValueError("Token coordinates must be all present or all null")
            if (
                self.token_end <= self.token_start
                or self.global_token_end <= self.global_token_start
            ):
                raise ValueError("Token intervals must be nonempty and ordered")
            if (
                self.token_end - self.token_start
                != self.global_token_end - self.global_token_start
            ):
                raise ValueError(
                    "Local and global token intervals must have equal lengths"
                )
        return self


class HitView(HitCoordinates):
    left: str
    match: str
    right: str

    @model_validator(mode="after")
    def exact_match_length(self):
        if len(self.match) != self.end_cp - self.start_cp:
            raise ValueError("Match text must cover the exact codepoint interval")
        return self


class ContextWindow(StrictView):
    unit: Literal["codepoint"]
    before: int = Field(ge=0, le=200)
    after: int = Field(ge=0, le=200)


class HitPage(QueryCounts):
    project_id: UUID
    snapshot_id: UUID
    result_set_id: UUID
    query_run_id: UUID
    hits: list[HitView] = Field(max_length=50)
    next_cursor: str | None
    has_more: bool
    page_state: Literal["pending", "ready"]
    completeness: Literal["preview", "complete"]
    sort: Sort
    context: ContextWindow

    @model_validator(mode="after")
    def page_identity_and_completion(self):
        if self.page_state == "pending" and (self.hits or self.next_cursor is not None):
            raise ValueError("Pending pages have no hits or continuation cursor")
        if self.completeness == "preview" and self.next_cursor is not None:
            raise ValueError("Preview pages cannot advertise a completed-result cursor")
        if (self.completeness == "complete") != (self.count_state == "complete"):
            raise ValueError("Page completeness must match complete counts")
        previous = -1
        for hit in self.hits:
            if (
                hit.hit_ref.result_set_id != self.result_set_id
                or hit.hit_ref.ordinal <= previous
            ):
                raise ValueError(
                    "Hits must reference this result in increasing ordinal order"
                )
            previous = hit.hit_ref.ordinal
        return self


class ContextView(HitCoordinates):
    project_id: UUID
    snapshot_id: UUID
    result_set_id: UUID
    text: str

    @model_validator(mode="after")
    def context_matches_reference(self):
        if (
            self.hit_ref.result_set_id != self.result_set_id
            or self.end_cp - self.context_start_cp > len(self.text)
        ):
            raise ValueError("Context must cover its referenced hit in the same result")
        return self


RESEARCH_INPUTS = {
    "snapshots.create": "snapshot-create",
    "snapshots.get": "snapshot-ref",
    "corpus.describe": "snapshot-ref",
    "corpus.search": "query-create",
    "results.get": "result-ref",
    "results.context": "context-ref",
}


def build_research(save, obj):
    uuid = {"type": "string", "format": "uuid"}
    for name, model in [
        ("snapshot-create", SnapshotInput),
        ("query-create", QueryInput),
        ("snapshot", SnapshotView),
        ("snapshot-action", SnapshotAction),
        ("snapshots", SnapshotList),
        ("query", QueryRunView),
        ("query-action", QueryAction),
        ("queries", QueryList),
        ("hits", HitPage),
        ("context", ContextView),
    ]:
        schema = model.model_json_schema()
        if model is SnapshotInput:
            schema["anyOf"] = [
                {
                    "properties": {
                        "mount_ids": {"minItems": n, "maxItems": n},
                        "material_revision_ids": {
                            "minItems": 1 if n == 0 else 0,
                            "maxItems": 16 - n,
                        },
                    },
                    "required": ["mount_ids"] if n else ["material_revision_ids"],
                }
                for n in range(17)
            ]
        for definition in [schema, *schema.get("$defs", {}).values()]:
            if "origin_kind" in definition.get("properties", {}):
                definition.setdefault("allOf", []).append(
                    {
                        "if": {"properties": {"origin_kind": {"const": "private"}}},
                        "then": {
                            "properties": {
                                **{
                                    key: {"type": "null"}
                                    for key in (
                                        "source_id",
                                        "source_sentence_id",
                                        "source_url",
                                    )
                                },
                                **{
                                    key: {"type": "string", "format": "uuid"}
                                    for key in ("material_id", "material_revision_id")
                                },
                            }
                        },
                        "else": {
                            "properties": {
                                **{
                                    key: {"type": "string"}
                                    for key in (
                                        "source_id",
                                        "source_sentence_id",
                                        "source_url",
                                    )
                                },
                                **{
                                    key: {"type": "null"}
                                    for key in ("material_id", "material_revision_id")
                                },
                                "context_start_cp": {"const": 0},
                            }
                        },
                    }
                )
        # The same count invariant is checked by Pydantic at the HTTP boundary.
        counts = {
            "if": {"properties": {"count_state": {"const": "complete"}}},
            "then": {
                "properties": {
                    key: {"type": "integer", "minimum": 0}
                    for key in ("total_hits", "matched_segments", "matched_documents")
                }
            },
            "else": {
                "properties": {
                    key: {"type": "null"}
                    for key in ("total_hits", "matched_segments", "matched_documents")
                }
            },
        }
        counts["then"]["properties"]["matched_document_units"] = {"type": "object"}
        counts["else"]["properties"]["matched_document_units"] = {"type": "null"}
        if "count_state" in schema.get("properties", {}):
            schema.setdefault("allOf", []).append(counts)
        for definition in schema.get("$defs", {}).values():
            if "count_state" in definition.get("properties", {}):
                definition.setdefault("allOf", []).append(counts)
        save(f"s3-research-{name}", schema)
    save("s3-research-snapshot-ref", obj({"snapshot_id": uuid}))
    save("s3-research-result-ref", obj({"result_set_id": uuid}))
    save(
        "s3-research-context-ref",
        obj({"result_set_id": uuid, "ordinal": {"type": "integer", "minimum": 0}}),
    )
    inventory = {
        "stage": "S3",
        "runtime_tool_schema": "s3-private-tools-v1",
        "available_tools": [],
        "manual_http": "scoped_source_private_mixed_http_and_browser_accepted",
        "coverage": [
            {
                "capability_id": name,
                "input_schema": f"schemas/s3-research-{schema}.schema.json",
                "scope_kind": ["project"],
                "tool_availability": "planned",
                "adapter_behavior": "deny_material_egress"
                if name in {"corpus.search", "results.context"}
                else "metadata_projection_only",
            }
            for name, schema in RESEARCH_INPUTS.items()
        ],
        "limits": [
            "One to sixteen fixed whole-source mounts or private revisions; source-only reuse remains supported; private/mixed HTTP and browser slice accepted.",
            "Snapshot preparation is asynchronous; a published source release is not a READY research snapshot.",
            "First page is a preview; all three exact counts stay null until durable full-result publication.",
            "Context uses actual Unicode codepoints, not tokens; evidence_id is null and hit_ref is a dereferenceable result ordinal.",
            "Empty-material Pi scope is unchanged. Metadata adapters omit AST, text and derived counts; search/context are explicitly denied before reading material.",
            "Prior runtime tool schemas are incompatible with s3-private-tools-v1; no silent restoration.",
            "Production delegated model/material authorization remains unaccepted and available_tools stays empty.",
        ],
    }
    (Path(__file__).parent / "s3-research-capabilities.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
