"""Project-private TXT import and immutable revision metadata contracts."""

import json
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field

from contracts.releases import RecipeView, StrictView
from contracts.research import Digest, ResearchError, ResearchProgress, RunState


class ImportInput(StrictView):
    upload_id: UUID
    language: Literal["cmn", "eng"]


class MaterialCounts(StrictView):
    documents: Literal[1]
    segments: int = Field(ge=1)
    characters: int = Field(ge=1)


class MaterialQuality(StrictView):
    complete_text_preserved: Literal[True]
    rejected_segments: Literal[0]
    segmentation: Literal["deterministic_rules_not_linguistic_gold"]


class MaterialRevisionView(StrictView):
    id: UUID
    material_id: UUID
    project_id: UUID
    revision: int = Field(ge=1)
    upload_id: UUID
    language: Literal["cmn", "eng"]
    recipe: RecipeView
    manifest_sha256: Digest
    canonical_sha256: Digest
    counts: MaterialCounts
    quality: MaterialQuality
    created_at: datetime


class ImportActions(StrictView):
    cancel: bool
    retry: bool


class ImportView(StrictView):
    id: UUID
    job_id: UUID
    project_id: UUID
    actor_id: UUID
    upload_id: UUID
    material_id: UUID
    filename: str
    language: Literal["cmn", "eng"]
    recipe: RecipeView
    state: RunState
    stage: Literal[
        "QUEUED", "FETCHING", "PARSING", "STORING", "COMPLETE", "FAILED", "CANCELLED"
    ]
    attempt: int = Field(ge=1)
    progress: ResearchProgress
    error: ResearchError | None
    result: MaterialRevisionView | None
    allowed_actions: ImportActions
    created_at: datetime
    updated_at: datetime


class ImportAction(StrictView):
    action_id: UUID
    job_id: UUID
    import_id: UUID
    state: RunState
    run: ImportView


class ImportList(StrictView):
    items: list[ImportView]
    next_cursor: str | None


class MaterialView(StrictView):
    id: UUID
    project_id: UUID
    name: str
    language: Literal["cmn", "eng"]
    state: Literal["IMPORTING", "READY", "FAILED", "CANCELLED"]
    import_id: UUID
    latest_revision: MaterialRevisionView | None
    revisions: list[MaterialRevisionView]
    created_at: datetime


class MaterialList(StrictView):
    items: list[MaterialView]
    next_cursor: str | None


class ValidatedUploadView(StrictView):
    upload_id: UUID
    project_id: UUID
    state: Literal["VALIDATED"]
    filename: str
    size: int = Field(ge=1, le=100000000)
    sha256: Digest
    media_type: str
    expires_at: datetime
    job_id: UUID | None


class ValidatedUploadList(StrictView):
    items: list[ValidatedUploadView]
    next_cursor: str | None


MATERIAL_INPUTS = {
    "imports.start": "import-create",
    "imports.get": "import-ref",
    "materials.list": "material-list-input",
    "materials.get": "material-ref",
}


def build_materials(save, obj):
    for name, model in [
        ("import-create", ImportInput),
        ("import", ImportView),
        ("import-action", ImportAction),
        ("imports", ImportList),
        ("material", MaterialView),
        ("materials", MaterialList),
        ("material-revision", MaterialRevisionView),
        ("uploads", ValidatedUploadList),
    ]:
        save(f"s3-private-{name}", model.model_json_schema())
    uuid = {"type": "string", "format": "uuid"}
    save("s3-private-import-ref", obj({"import_id": uuid}))
    save("s3-private-material-ref", obj({"material_id": uuid}))
    save(
        "s3-private-material-list-input",
        obj(
            {
                "cursor": {"type": "string", "minLength": 1},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            [],
        ),
    )
    (Path(__file__).parent / "s3-private-capabilities.json").write_text(
        json.dumps(
            {
                "stage": "S3",
                "runtime_tool_schema": "s3-private-tools-v1",
                "available_tools": [],
                "manual_http": "scoped_http_and_browser_accepted",
                "coverage": [
                    {
                        "capability_id": name,
                        "input_schema": f"schemas/s3-private-{schema}.schema.json",
                        "scope_kind": ["project"],
                        "tool_availability": "planned",
                        "adapter_behavior": "metadata_projection_only",
                    }
                    for name, schema in MATERIAL_INPUTS.items()
                ],
                "limits": [
                    "TXT parsing creates immutable revisions, not a research index; snapshot preparation creates the index.",
                    "Private and mixed snapshots contain 1..16 fixed members; conflicting revisions of one document are rejected.",
                    "Canonical document codepoints are used; returned sentence context supplies context_start_cp.",
                    "Pi receives no filenames, text, segmentation or derived counts. Empty material scope remains unchanged; production available_tools remains empty.",
                    "Previous runtime tool schema checkpoints are rejected; no silent restoration.",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
