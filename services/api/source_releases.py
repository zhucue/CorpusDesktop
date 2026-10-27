"""Explicit internal-research permission and atomic fixed-index publication."""

import hashlib
import json
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Header
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from contracts.releases import PolicyAction, PolicyView, ReleaseView
from contracts.releases import ReleaseAction as ReleaseActionView
from services.api import storage
from services.api.auth import CurrentActor
from services.api.catalog import digest, require_admin
from services.api.catalog_models import CatalogRelease, CatalogSource
from services.api.db import transaction
from services.api.index_builds import recipe
from services.api.index_models import IndexRun, SourceIndex
from services.api.jobs import fail, now
from services.api.release_models import (
    PolicyHead,
    ReleaseAction,
    ReleaseHead,
    SourcePolicy,
)
from services.api.source_sync import identity, lock_source
from services.api.source_sync_models import Acquisition

router = APIRouter(prefix="/api/v1")


class PolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=0)
    decision: Literal["allow", "deny"]
    export_decision: Literal["allow", "deny"] = "deny"
    review_note: str = Field(min_length=1, max_length=4000)
    evidence_urls: list[str] = Field(min_length=1, max_length=12)

    @field_validator("evidence_urls")
    @classmethod
    def evidence(cls, values):
        for value in values:
            parsed = urlsplit(value)
            if (
                len(value) > 2048
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or any(c.isspace() for c in value)
            ):
                raise ValueError("Public HTTP(S) reference required")
        return values  # References are never fetched from user input.


class PublishInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index_id: UUID
    expected_policy_revision: int = Field(ge=1)


def source(db, source_id):
    lock_source(db, source_id)
    row = db.scalar(
        select(CatalogSource)
        .where(CatalogSource.source_id == source_id)
        .execution_options(populate_existing=True)
    )
    if not row:
        fail("SOURCE_NOT_FOUND", "来源不存在。", 404)
    return row


def acquisition(db, source_id, ident):
    row = db.get(Acquisition, ident)
    if not row or row.source_id != source_id:
        fail("ACQUISITION_NOT_FOUND", "固定获取版本不存在。", 404)
    return row


def current_policy(db, acquisition_id):
    head = db.scalar(
        select(PolicyHead)
        .where(PolicyHead.acquisition_id == acquisition_id)
        .execution_options(populate_existing=True)
    )
    return db.get(SourcePolicy, head.policy_id) if head else None


def action(db, actor_id, operation, key, payload):
    if (
        not isinstance(key, str)
        or not key
        or len(key) > 128
        or not key.isascii()
        or any(ord(c) < 33 for c in key)
    ):
        fail("IDEMPOTENCY_KEY_REQUIRED", "提供有效的 Idempotency-Key。", 422)
    fingerprint = digest(jsonable_encoder(payload))
    old = db.scalar(
        select(ReleaseAction).where(
            ReleaseAction.actor_id == actor_id,
            ReleaseAction.operation == operation,
            ReleaseAction.idempotency_key == key,
        )
    )
    if old:
        if old.request_sha256 != fingerprint:
            fail("IDEMPOTENCY_CONFLICT", "相同操作标识不能用于不同请求。")
        return old, True
    row = ReleaseAction(
        id=uuid4(),
        actor_id=actor_id,
        operation=operation,
        idempotency_key=key,
        request_sha256=fingerprint,
        response={},
        created_at=now(),
    )
    db.add(row)
    return row, False


def policy_view(source_row, acquired, policy):
    license_data = acquired.manifest.get("license", {})
    return {
        "source_id": source_row.source_id,
        "acquisition_id": str(acquired.id),
        "revision": policy.revision if policy else 0,
        "decision": policy.decision if policy else "unknown",
        "policy_id": str(policy.id) if policy else None,
        "source_identity": policy.source_identity
        if policy
        else acquired.source_identity,
        "source_identity_revision": policy.source_identity_revision
        if policy
        else source_row.identity_revision,
        "identity_current": acquired.source_identity == identity(source_row)
        and (
            not policy
            or policy.source_identity_revision == source_row.identity_revision
        ),
        "acquisition_manifest_sha256": acquired.manifest_sha256,
        "license_sha256": digest(license_data),
        "license": license_data,
        "quality": acquired.manifest.get("quality", {}),
        "review_note": policy.review_note if policy else None,
        "evidence_urls": policy.evidence_urls if policy else [],
        "reviewed_by": str(policy.reviewed_by) if policy else None,
        "reviewed_at": policy.reviewed_at.isoformat() if policy else None,
        "scope": "internal_research",
        "export_decision": policy.export_decision if policy else "deny",
        "export": bool(
            policy
            and policy.decision == "allow"
            and policy.export_decision == "allow"
            and acquired.source_identity == identity(source_row)
            and policy.source_identity_revision == source_row.identity_revision
        ),
        "model_egress": False,
    }


def require_policy(source_row, acquired, policy, expected=None):
    if not policy or policy.decision != "allow":
        fail("SOURCE_POLICY_DENIED", "固定版本尚未获准用于本平台内部研究。", 403)
    if (
        policy.source_identity_revision != source_row.identity_revision
        or acquired.source_identity != identity(source_row)
    ):
        fail("SOURCE_IDENTITY_CHANGED", "来源身份已改变，须重新核准固定版本。", 403)
    if (
        policy.acquisition_manifest_sha256 != acquired.manifest_sha256
        or policy.license_sha256 != digest(acquired.manifest.get("license", {}))
    ):
        fail("SOURCE_POLICY_MISMATCH", "许可核准与固定获取版本不一致。", 403)
    if expected is not None and policy.revision != expected:
        fail("POLICY_REVISION_CONFLICT", "来源策略已更新，请重新读取。")


@router.get(
    "/admin/sources/{source_id}/policies/{acquisition_id}", response_model=PolicyView
)
def get_policy(source_id: str, acquisition_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        require_admin(db, actor)
        row = source(db, source_id)
        acquired = acquisition(db, source_id, acquisition_id)
        return policy_view(row, acquired, current_policy(db, acquired.id))


@router.post(
    "/admin/sources/{source_id}/policies/{acquisition_id}", response_model=PolicyAction
)
def update_policy(
    source_id: str,
    acquisition_id: UUID,
    body: PolicyInput,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as db:
        require_admin(db, actor)
        row = source(db, source_id)
        acquired = acquisition(db, source_id, acquisition_id)
        previous = current_policy(db, acquired.id)
        ledger, old = action(
            db,
            actor.id,
            "policies.update",
            idempotency_key,
            {
                "source_id": source_id,
                "acquisition_id": acquired.id,
                **body.model_dump(),
            },
        )
        if old:
            # Old allow cannot be replayed as a current approval after revocation.
            saved = ledger.response["policy"]
            if (
                not previous
                or str(previous.id) != saved["policy_id"]
                or previous.source_identity_revision != row.identity_revision
            ):
                fail(
                    "POLICY_REPLAY_STALE", "该核准操作已被后续策略或来源身份变更取代。"
                )
            return ledger.response
        if body.expected_revision != (previous.revision if previous else 0):
            fail("POLICY_REVISION_CONFLICT", "来源策略已更新，请重新读取。")
        if acquired.source_identity != identity(row):
            fail("SOURCE_IDENTITY_CHANGED", "固定获取版本不属于当前来源身份。", 403)
        policy = SourcePolicy(
            id=uuid4(),
            source_id=source_id,
            acquisition_id=acquired.id,
            revision=body.expected_revision + 1,
            source_identity_revision=row.identity_revision,
            source_identity=identity(row),
            acquisition_manifest_sha256=acquired.manifest_sha256,
            license_sha256=digest(acquired.manifest.get("license", {})),
            decision=body.decision,
            export_decision=body.export_decision,
            review_note=body.review_note,
            evidence_urls=body.evidence_urls,
            reviewed_by=actor.id,
            reviewed_at=now(),
        )
        db.add(policy)
        db.flush()
        head = db.get(PolicyHead, acquired.id)
        if head:
            head.policy_id, head.revision = policy.id, policy.revision
        else:
            db.add(
                PolicyHead(
                    acquisition_id=acquired.id,
                    source_id=source_id,
                    policy_id=policy.id,
                    revision=policy.revision,
                )
            )
        ledger.response = {
            "action_id": str(ledger.id),
            "policy": policy_view(row, acquired, policy),
        }
        return ledger.response


def release_availability(db, row, source_row):
    policy = current_policy(db, row.acquisition_id)
    reason = None
    if not policy or policy.decision != "allow":
        reason = "SOURCE_POLICY_DENIED"
    elif policy.source_identity_revision != source_row.identity_revision:
        reason = "SOURCE_IDENTITY_CHANGED"
    return policy, reason


def view_release(db, row, source_row=None):
    source_row = source_row or source(db, row.source_id)
    policy, reason = release_availability(db, row, source_row)
    return {
        "release_id": str(row.release_id),
        "source_id": row.source_id,
        "source_snapshot_id": str(row.source_snapshot_id),
        "index_id": str(row.index_id),
        "acquisition_id": str(row.acquisition_id),
        "version": row.version,
        "published_at": row.published_at.isoformat(),
        "manifest_sha256": row.manifest_sha256,
        "index_identity_sha256": row.index_identity_sha256,
        "recipe": row.recipe,
        "counts": row.counts,
        "quality": row.quality,
        "policy_revision": row.policy_revision,
        "current_policy_revision": policy.revision if policy else 0,
        "state": "PUBLISHED",
        "searchable": reason is None and row.recipe == recipe(),
        "available": reason is None,
        "unavailable_reason": reason,
    }


def require_available(db, release, source_row=None):
    view = view_release(db, release, source_row)
    if not view["available"]:
        fail(view["unavailable_reason"], "来源版本当前未获准读取或挂载。", 403)
    return view


def verified_manifest(index):
    """Small manifest SHA plus fixed-version HEAD; never re-download the tar here."""
    try:
        objects = {item["name"]: item for item in index.objects}
        if len(objects) != 2 or set(objects) != {"manifest.json", "index.tar"}:
            raise ValueError("Incomplete object set")
        for item in objects.values():
            if not item["version_id"] or item["version_id"] == "null":
                raise ValueError("Version missing")
            head = storage.client().head_object(
                Bucket=storage.bucket(),
                Key=item["object_key"],
                VersionId=item["version_id"],
            )
            if (
                head.get("VersionId") != item["version_id"]
                or head["ContentLength"] != item["bytes"]
                or head["ETag"] != item["etag"]
            ):
                raise ValueError("Object identity mismatch")
        item = objects["manifest.json"]
        if item["bytes"] > 1024 * 1024:
            raise ValueError("Manifest too large")
        stream = storage.read_private(
            item["object_key"], item["version_id"], item["etag"]
        )
        try:
            raw = stream.read(1024 * 1024 + 1)
        finally:
            stream.close()
        parsed = json.loads(raw)
        if (
            len(raw) != item["bytes"]
            or hashlib.sha256(raw).hexdigest() != item["sha256"]
            or item["sha256"] != index.manifest_sha256
            or parsed != index.manifest
        ):
            raise ValueError("Manifest mismatch")
        package = parsed["package"]
        if (
            package["bytes"] != objects["index.tar"]["bytes"]
            or package["sha256"] != objects["index.tar"]["sha256"]
        ):
            raise ValueError("Package receipt mismatch")
        return parsed
    except Exception:  # noqa: BLE001 - do not expose provider paths or credentials
        fail("RELEASE_OBJECT_UNAVAILABLE", "固定私有索引产物无法核验。", 503)


@router.post(
    "/admin/sources/{source_id}/releases",
    status_code=201,
    response_model=ReleaseActionView,
)
def publish(
    source_id: str,
    body: PublishInput,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as db:
        require_admin(db, actor)
        row = source(db, source_id)
        index = db.get(SourceIndex, body.index_id)
        if not index or index.source_id != source_id:
            fail("INDEX_NOT_FOUND", "固定来源索引不存在。", 404)
        acquired = acquisition(db, source_id, index.acquisition_id)
        policy = current_policy(db, acquired.id)
        require_policy(row, acquired, policy, body.expected_policy_revision)
        run = db.get(IndexRun, index.run_id)
        if (
            not run
            or run.state != "SUCCEEDED"
            or run.result.get("index_id") != str(index.id)
            or run.source_identity != acquired.source_identity
            or run.recipe != recipe()
            or index.recipe_sha256 != run.recipe_sha256
        ):
            fail("INDEX_NOT_PUBLISHABLE", "索引未完整完成或配置已不兼容。")
        manifest = verified_manifest(index)
        if (
            manifest["identity"]["acquisition_manifest_sha256"]
            != acquired.manifest_sha256
            or manifest["identity_sha256"] != index.identity_sha256
            or manifest["recipe_sha256"] != index.recipe_sha256
        ):
            fail("INDEX_NOT_PUBLISHABLE", "索引内容与固定获取版本不一致。")
        ledger, old = action(
            db,
            actor.id,
            "releases.publish",
            idempotency_key,
            {"source_id": source_id, **body.model_dump()},
        )
        if old:
            return ledger.response
        release = db.scalar(
            select(CatalogRelease).where(CatalogRelease.index_id == index.id)
        )
        existing = release is not None
        if not release:
            ordinal = (
                db.scalar(
                    select(func.count())
                    .select_from(CatalogRelease)
                    .where(CatalogRelease.source_id == source_id)
                )
                + 1
            )
            release = CatalogRelease(
                release_id=uuid4(),
                source_id=source_id,
                version=str(ordinal),
                published_at=now(),
                manifest_sha256=index.manifest_sha256,
                source_snapshot_id=uuid4(),
                index_id=index.id,
                acquisition_id=acquired.id,
                policy_id=policy.id,
                policy_revision=policy.revision,
                source_identity_revision=row.identity_revision,
                index_identity_sha256=index.identity_sha256,
                recipe=run.recipe,
                counts=manifest["counts"],
                quality=manifest["quality"],
            )
            db.add(release)
            db.flush()
            head = db.get(ReleaseHead, source_id)
            if head:
                head.release_id = release.release_id
            else:
                db.add(ReleaseHead(source_id=source_id, release_id=release.release_id))
        ledger.response = {
            "action_id": str(ledger.id),
            "existing": existing,
            "release": view_release(db, release, row),
        }
        return ledger.response


@router.get("/sources/{source_id}/releases/{release_id}", response_model=ReleaseView)
def get_release(source_id: str, release_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        row = source(db, source_id)
        release = db.get(CatalogRelease, release_id)
        if not release or release.source_id != source_id:
            fail("RELEASE_NOT_FOUND", "固定来源发布版本不存在。", 404)
        return view_release(db, release, row)
