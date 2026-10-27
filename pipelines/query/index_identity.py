"""Executable S0 contract for immutable index reuse and storage admission.

This is not a production index catalogue or authorization/quota service. Requests
and source catalogue entries must come from trusted persisted backend state. The
authorization callback must check current project access, mounts and the exact
snapshot/identity binding on EVERY call; no caller-supplied boolean grants access.

Metadata is conservatively index-bound in this subset: any manifest change
requires a different key. Independently filterable metadata is not implemented.
"""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


def content_digest(value):
    """Hash JSON content without reordering arrays or normalizing Unicode."""
    def validate_keys(item):
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("JSON_OBJECT_KEYS_MUST_BE_STRINGS")
            for child in item.values():
                validate_keys(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                validate_keys(child)

    validate_keys(value)
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IndexMember:
    revision_id: str
    text_sha256: str
    token_layer_sha256: str
    segment_map_sha256: str


def member_from_revision(revision):
    """Digest actual prototype content, token attributes/coordinates and segments."""
    return IndexMember(revision.revision_id, content_digest(revision.text),
                       content_digest(revision.tokens),
                       content_digest({"sentences": revision.sentences, "paragraphs": revision.paragraphs}))


@dataclass(frozen=True)
class IndexIdentity:
    engine: str
    engine_version: str
    unit: Literal["character", "token"]
    normalization: dict
    recipe_sha256: str
    members: tuple[IndexMember, ...]
    metadata_manifest_ref: str
    metadata_sha256: str

    def key(self):
        if self.unit not in ("character", "token") or not isinstance(self.normalization, dict):
            raise ValueError("INVALID_INDEX_CONFIGURATION")
        names = (self.engine, self.engine_version, self.metadata_manifest_ref)
        if any(not isinstance(value, str) or not value.strip() for value in names):
            raise ValueError("MISSING_INDEX_VERSION")
        seen = set()
        digests = [self.recipe_sha256, self.metadata_sha256]
        for member in self.members:
            if not isinstance(member.revision_id, str) or not member.revision_id or member.revision_id in seen:
                raise ValueError("REVISIONS_MUST_BE_ORDERED_AND_UNIQUE")
            seen.add(member.revision_id)
            digests.extend((member.text_sha256, member.token_layer_sha256, member.segment_map_sha256))
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in digests):
            raise ValueError("INVALID_CONTENT_SHA256")
        return content_digest({"identity_version": "index-identity/s0-v1", **asdict(self)})


@dataclass(frozen=True)
class IndexRequest:
    project_id: str
    snapshot_id: str
    kind: Literal["source_full", "subset", "mixed", "private"]
    source_release_id: str | None
    identity: IndexIdentity


@dataclass(frozen=True)
class SourceIndex:
    """Trusted catalogue entry for a complete, already published source index."""
    index_id: str
    release_id: str
    identity: IndexIdentity


@dataclass(frozen=True)
class IndexDecision:
    action: Literal["reuse", "build_required"]
    project_id: str
    snapshot_id: str
    key: str
    index_id: str | None = None


def decide_index(request: IndexRequest, *, authorize: Callable[[IndexRequest], None],
                 lookup_source: Callable[[str], SourceIndex | None]):
    """Authorize before catalogue lookup; only an exact complete source can reuse.

The callback raises on denial. Its return value is intentionally not a boolean
permission parameter. This function neither opens files nor grants query access.
"""
    if authorize(request) is not None:
        raise ValueError("AUTHORIZATION_CALLBACK_MUST_RAISE_OR_RETURN_NONE")
    if not request.project_id or not request.snapshot_id or request.kind not in ("source_full", "subset", "mixed", "private"):
        raise ValueError("INVALID_INDEX_REQUEST")
    key = request.identity.key()
    index_id = None
    if request.kind == "source_full":
        if not request.source_release_id:
            raise ValueError("FULL_SOURCE_REQUIRES_RELEASE")
        source = lookup_source(request.source_release_id)
        if source is not None:
            if source.release_id != request.source_release_id:
                raise ValueError("SOURCE_CATALOGUE_RELEASE_MISMATCH")
            if not source.index_id:
                raise ValueError("SOURCE_CATALOGUE_INDEX_ID_MISSING")
            if source.identity.key() == key:
                index_id = source.index_id
    return IndexDecision("reuse" if index_id is not None else "build_required",
                         request.project_id, request.snapshot_id, key, index_id)


class IndexQuotaExceeded(ValueError):
    def __init__(self, cost_bytes, remaining_bytes, basis):
        self.cost_bytes = cost_bytes
        self.remaining_bytes = remaining_bytes
        self.basis = basis
        super().__init__(f"INDEX_QUOTA_EXCEEDED: {basis} cost {cost_bytes} bytes exceeds remaining {remaining_bytes} bytes")


def check_storage_quota(*, cost_bytes, used_bytes, limit_bytes, basis: Literal["estimate", "measured"]):
    """Pure admission check: estimate before build, actual file bytes before publish.

No quota mutation/reservation, concurrent accounting, runtime disk/memory cap,
temporary-file peak measurement or publication is implemented. Passing an
estimate never substitutes for checking measured output before publication.
"""
    if basis not in ("estimate", "measured") or any(type(value) is not int or value < 0 for value in (cost_bytes, used_bytes, limit_bytes)):
        raise ValueError("INVALID_QUOTA_INPUT")
    remaining = max(0, limit_bytes - used_bytes)
    if used_bytes > limit_bytes or cost_bytes > remaining:
        raise IndexQuotaExceeded(cost_bytes, remaining, basis)
    return {"basis": basis, "cost_bytes": cost_bytes, "remaining_after_bytes": remaining - cost_bytes}


def measured_artifact_bytes(directory):
    """Sum actual regular-file lengths; excludes filesystem overhead and build peak."""
    root = Path(directory)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("EXPECTED_ARTIFACT_DIRECTORY")
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("ARTIFACT_SYMLINK_UNSUPPORTED")
        if path.is_file():
            total += path.stat().st_size
    return total
