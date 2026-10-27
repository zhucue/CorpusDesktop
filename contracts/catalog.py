"""S1 source discovery metadata; no release publication or license approval."""

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from contracts.releases import ReleaseView

EntryKind = Literal["publisher", "aggregator", "dataset"]
IntegrationStatus = Literal[
    "catalog_only", "verification_pending", "experimental_evidence"
]
Capability = Literal[
    "discover", "remote_query", "fulltext_analysis", "export", "model_egress"
]
SOURCE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"


class CatalogMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=160)
    publisher: str = Field(min_length=1, max_length=200)
    entry_kind: EntryKind
    categories: list[str] = Field(min_length=1, max_length=12)
    languages: list[str] = Field(min_length=1, max_length=20)
    official_url: str = Field(min_length=1, max_length=2048)
    materials: str = Field(min_length=1, max_length=2000)
    access_route: str = Field(min_length=1, max_length=2000)
    boundary: str = Field(min_length=1, max_length=4000)

    @field_validator("official_url")
    @classmethod
    def url_valid(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or any(c.isspace() for c in value)
        ):
            raise ValueError("A public HTTP(S) reference URL is required")
        return value  # Stored as reference only; the API never fetches this URL.

    @field_validator("categories", "languages")
    @classmethod
    def tags_valid(cls, values):
        values = [v.strip() for v in values]
        if any(not v or len(v) > 48 or any(ord(c) < 32 for c in v) for v in values):
            raise ValueError("Invalid classification")
        if len(values) != len(set(values)):
            raise ValueError("Duplicate classification")
        return values


class CatalogCreate(CatalogMetadata):
    source_id: str = Field(pattern=SOURCE_ID_PATTERN)


class CatalogUpdate(CatalogMetadata):
    expected_revision: int = Field(ge=1)


class SourceCapabilities(BaseModel):
    discover: Literal[True] = True
    remote_query: Literal[False] = False
    fulltext_analysis: Literal[False] = False
    export: Literal[False] = False
    model_egress: Literal[False] = False


class SourceView(CatalogMetadata):
    source_id: str
    license_status: Literal["pending_review"] = "pending_review"
    integration_status: IntegrationStatus
    capabilities: SourceCapabilities = Field(default_factory=SourceCapabilities)
    evidence_refs: list[str]
    revision: int
    created_at: datetime
    updated_at: datetime


class CatalogWriteView(SourceView):
    action_id: UUID


class SourceList(BaseModel):
    items: list[SourceView]
    total: int
    next_cursor: str | None


class SourceVersionView(ReleaseView):
    pass

class SourceVersionList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SourceVersionView]
    total: int = Field(ge=0)
    next_cursor: str | None
