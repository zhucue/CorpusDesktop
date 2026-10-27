"""Fixed research evidence and versioned notes with inherited authorization."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query
from sqlalchemy import select

from contracts.outcomes import (
    EvidenceAction,
    EvidenceInput,
    EvidenceList,
    EvidenceView,
    NoteAccept,
    NoteAction,
    NoteInput,
    NoteList,
    NoteUpdate,
    NoteView,
)
from services.api import research, source_mounts, source_releases
from services.api.auth import CurrentActor
from services.api.catalog import digest, make_cursor, read_cursor
from services.api.db import transaction
from services.api.errors import ApiError
from services.api.jobs import action_lookup, fail, now
from services.api.models import LoginSession
from services.api.outcome_models import Evidence, Note, NoteAcceptance, NoteRevision
from services.api.projects import project_role
from services.api.research_models import QueryRun, Snapshot

router = APIRouter(prefix="/api/v1/projects/{project_id}")


def ids(values):
    return sorted({str(UUID(str(v))) for v in values})


def authorize_dependencies(
    db, actor_id, project_id, evidence_ids=(), query_run_ids=(), *, export=False
):
    """Lock all involved source namespaces before resolving any individual snapshot."""
    source_mounts.project(db, actor_id, project_id)
    evidence = []
    for ident in ids(evidence_ids):
        item = db.get(Evidence, UUID(ident))
        if not item or item.project_id != project_id:
            fail("EVIDENCE_UNAVAILABLE", "证据不存在或引用材料已不可访问。", 403)
        evidence.append(item)
    run_ids = ids([*query_run_ids, *(e.query_run_id for e in evidence)])
    runs, snapshots = [], {}
    for ident in run_ids:
        run = db.get(QueryRun, UUID(ident))
        if not run or run.project_id != project_id:
            fail("RESULT_UNAVAILABLE", "固定查询不存在或材料已不可访问。", 403)
        if run.state != "SUCCEEDED" or run.counts is None or not run.result_object:
            fail("RESULT_NOT_COMPLETE", "须使用完整完成的固定查询结果。")
        snapshot = db.get(Snapshot, run.snapshot_id)
        if not snapshot or snapshot.project_id != project_id:
            fail("SNAPSHOT_NOT_FOUND", "固定研究快照不可访问。", 403)
        snapshots[snapshot.id] = snapshot
        runs.append(run)
    for source_id in sorted(
        {
            m["source_id"]
            for s in snapshots.values()
            for m in s.manifest["members"]
            if m["kind"] == "whole_source_mount"
        }
    ):
        source_releases.lock_source(db, source_id)
    for snapshot in snapshots.values():
        research.resolve_snapshot(db, actor_id, project_id, snapshot.id, ready=True)
        if export:
            for member in snapshot.manifest["members"]:
                if member["kind"] != "whole_source_mount":
                    continue
                _, _, release, _ = source_mounts.resolve_mount(
                    db, actor_id, project_id, UUID(member["mount_id"])
                )
                policy = source_releases.current_policy(db, release.acquisition_id)
                if not policy or policy.export_decision != "allow":
                    fail("EXPORT_POLICY_DENIED", "固定来源版本未获准导出。", 403)
    return runs


def method(db, actor_id, run):
    _, snapshot, index = research.resolve_snapshot(
        db, actor_id, run.project_id, run.snapshot_id, ready=True
    )
    return {
        "query_run_id": str(run.id),
        "result_set_id": str(run.result_set_id),
        "snapshot_id": str(run.snapshot_id),
        "query": run.query,
        "query_sha256": run.query_sha256,
        "recipe": research.project_recipe()
        if research.is_project(snapshot)
        else snapshot.manifest["members"][0]["recipe"],
        "counts": {"count_state": "complete", **research.query_counts(run, snapshot)},
        "result_sha256": run.result_object["sha256"],
        "index_identity_sha256": index.identity_sha256,
    }


def context_data(db, actor_id, run, ordinal):
    from pipelines.query.source_cache import open_cached

    _, _, index = research.resolve_snapshot(
        db, actor_id, run.project_id, run.snapshot_id, ready=True
    )
    if ordinal < 0 or ordinal >= run.counts["total_hits"]:
        fail("HIT_NOT_FOUND", "命中引用不存在。", 404)
    page = research.read_cached(run, index, ordinal, 1)
    if not page["hits"]:
        fail("HIT_NOT_FOUND", "固定命中不可访问。", 404)
    hit = page["hits"][0]
    try:
        with open_cached(
            research.cache_root() / "indexes",
            index.manifest["package"]["sha256"],
            index.identity_sha256,
        ) as reader:
            text = reader.text(hit["sentence_ordinal"])
    except (OSError, ValueError):
        fail("CACHE_NOT_READY", "固定结果缓存不可用，请准备缓存。", 503)
    value = research.format_hit(run, hit, ordinal, db)
    for key in ("left", "match", "right"):
        value.pop(key)
    return {
        **value,
        "project_id": str(run.project_id),
        "snapshot_id": str(run.snapshot_id),
        "result_set_id": str(run.result_set_id),
        "text": text,
    }


def evidence_summary(item):
    return {
        "id": str(item.id),
        "project_id": str(item.project_id),
        "created_by": str(item.created_by),
        "created_at": item.created_at.isoformat(),
        "query_run_id": str(item.query_run_id),
        "result_set_id": str(item.result_set_id),
        "snapshot_id": str(item.snapshot_id),
        "hit_ref": {"result_set_id": str(item.result_set_id), "ordinal": item.ordinal},
    }


def evidence_view(db, actor_id, item):
    runs = authorize_dependencies(db, actor_id, item.project_id, [item.id])
    context = context_data(db, actor_id, runs[0], item.ordinal)
    if (
        digest(context) != item.context_sha256
        or method(db, actor_id, runs[0]) != item.method
    ):
        fail("EVIDENCE_IDENTITY_MISMATCH", "固定证据与结果身份不一致。")
    return {
        **evidence_summary(item),
        "context": context,
        "method": item.method,
        "context_sha256": item.context_sha256,
    }


@router.post("/evidence", status_code=201, response_model=EvidenceAction)
def create_evidence(
    project_id: UUID,
    body: EvidenceInput,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as db:
        source_mounts.project(db, actor.id, project_id, write=True)
        run = research.load_run(
            db, actor.id, project_id, body.result_set_id, result=True
        )
        authorize_dependencies(db, actor.id, project_id, query_run_ids=[run.id])
        ledger, old = action_lookup(
            db,
            actor.id,
            project_id,
            idempotency_key,
            "evidence.create",
            body.model_dump(mode="json"),
        )
        item = db.scalar(
            select(Evidence).where(
                Evidence.project_id == project_id,
                Evidence.result_set_id == run.result_set_id,
                Evidence.ordinal == body.ordinal,
            )
        )
        existing = item is not None
        if old:
            item = db.get(Evidence, UUID(ledger.response["evidence_id"]))
        elif not item:
            context = context_data(db, actor.id, run, body.ordinal)
            item = Evidence(
                id=uuid4(),
                project_id=project_id,
                created_by=actor.id,
                query_run_id=run.id,
                result_set_id=run.result_set_id,
                snapshot_id=run.snapshot_id,
                ordinal=body.ordinal,
                coordinates={k: v for k, v in context.items() if k != "text"},
                method=method(db, actor.id, run),
                context_sha256=digest(context),
                created_at=now(),
            )
            db.add(item)
            db.flush()
        ledger.response = {"evidence_id": str(item.id)}
        return {
            "action_id": str(ledger.id),
            "existing": old or existing,
            "evidence": evidence_view(db, actor.id, item),
        }


@router.get("/evidence/{evidence_id}", response_model=EvidenceView)
def get_evidence(project_id: UUID, evidence_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        source_mounts.project(db, actor.id, project_id)
        item = db.get(Evidence, evidence_id)
        if not item or item.project_id != project_id:
            fail("EVIDENCE_UNAVAILABLE", "证据不存在或不可访问。", 404)
        return evidence_view(db, actor.id, item)


def paginate(rows, cursor, page_size, kind, project_id):
    filters = {"kind": kind, "project_id": str(project_id)}
    last = read_cursor(cursor, filters)
    total = len(rows)
    if last is not None:
        try:
            ident = UUID(last)
        except ValueError:
            fail("INVALID_CURSOR", "分页游标无效。", 422)
        rows = [r for r in rows if UUID(r["id"]) > ident]
    return {
        "items": rows[:page_size],
        "total": total,
        "next_cursor": make_cursor(rows[page_size - 1]["id"], filters)
        if len(rows) > page_size
        else None,
    }


@router.get("/evidence", response_model=EvidenceList)
def list_evidence(
    project_id: UUID,
    actor: CurrentActor,
    cursor: str | None = Query(None, max_length=512),
    page_size: int = Query(50, ge=1, le=100),
):
    with transaction(actor.id) as db:
        project = source_mounts.project(db, actor.id, project_id)
        rows = list(
            db.scalars(
                select(Evidence)
                .where(Evidence.project_id == project_id)
                .order_by(Evidence.id)
            )
        )
        authorize_dependencies(db, actor.id, project_id, [e.id for e in rows])
        return {
            **paginate(
                [evidence_summary(e) for e in rows],
                cursor,
                page_size,
                "evidence",
                project_id,
            ),
            "allowed_actions": {
                "create": project_role(db, actor.id, project) in {"owner", "editor"}
            },
        }


def load_note(db, actor_id, project_id, note_id, revision=None):
    source_mounts.project(db, actor_id, project_id)
    note = db.get(Note, note_id)
    if not note or note.project_id != project_id:
        fail("NOTE_NOT_FOUND", "笔记不存在或不可访问。", 404)
    row = db.get(NoteRevision, (note.id, revision or note.current_revision))
    if not row:
        fail("NOTE_UNAVAILABLE", "笔记修订不存在或引用材料已不可访问。", 403)
    authorize_dependencies(
        db,
        actor_id,
        project_id,
        row.authorization_evidence_ids,
        row.authorization_query_run_ids,
    )
    return note, row


def note_view(db, actor_id, note, row, *, summary=False):
    project = source_mounts.project(db, actor_id, note.project_id)
    authorize_dependencies(
        db,
        actor_id,
        note.project_id,
        row.authorization_evidence_ids,
        row.authorization_query_run_ids,
    )
    accepted = db.get(NoteAcceptance, (note.id, row.revision))
    writable = project_role(db, actor_id, project) in {"owner", "editor"}
    exportable = True
    try:
        authorize_dependencies(
            db,
            actor_id,
            note.project_id,
            row.authorization_evidence_ids,
            row.authorization_query_run_ids,
            export=True,
        )
    except ApiError:
        exportable = False
    result = {
        "id": str(note.id),
        "project_id": str(note.project_id),
        "created_by": str(note.created_by),
        "created_at": note.created_at.isoformat(),
        "updated_at": row.created_at.isoformat(),
        "revision": row.revision,
        "title": row.title,
        "body": row.body,
        "evidence_ids": row.evidence_ids,
        "query_run_ids": row.query_run_ids,
        "authorization_evidence_ids": row.authorization_evidence_ids,
        "authorization_query_run_ids": row.authorization_query_run_ids,
        "status": "accepted" if accepted else "draft",
        "accepted_by": str(accepted.accepted_by) if accepted else None,
        "accepted_at": accepted.accepted_at.isoformat() if accepted else None,
        "allowed_actions": {
            "update": writable and row.revision == note.current_revision,
            "accept": writable
            and row.revision == note.current_revision
            and not accepted,
            "export": exportable,
        },
    }
    if summary:
        result.pop("body")
    return result


def add_revision(db, note, actor_id, body, previous=None):
    evidence = ids(
        [*body.evidence_ids, *(previous.authorization_evidence_ids if previous else [])]
    )
    queries = ids(
        [
            *body.query_run_ids,
            *(previous.authorization_query_run_ids if previous else []),
        ]
    )
    if len(evidence) + len(queries) > 100:
        fail("NOTE_DEPENDENCY_LIMIT", "笔记继承的材料引用总数不能超过100。", 422)
    authorize_dependencies(db, actor_id, note.project_id, evidence, queries)
    row = NoteRevision(
        note_id=note.id,
        project_id=note.project_id,
        revision=note.current_revision,
        created_by=actor_id,
        title=body.title,
        body=body.body,
        evidence_ids=ids(body.evidence_ids),
        query_run_ids=ids(body.query_run_ids),
        authorization_evidence_ids=evidence,
        authorization_query_run_ids=queries,
        created_at=now(),
    )
    db.add(row)
    db.flush()
    return row


@router.post("/notes", status_code=201, response_model=NoteAction)
def create_note(
    project_id: UUID,
    body: NoteInput,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as db:
        source_mounts.project(db, actor.id, project_id, write=True)
        authorize_dependencies(
            db, actor.id, project_id, body.evidence_ids, body.query_run_ids
        )
        ledger, old = action_lookup(
            db,
            actor.id,
            project_id,
            idempotency_key,
            "notes.create",
            body.model_dump(mode="json"),
        )
        if old:
            note, row = load_note(
                db,
                actor.id,
                project_id,
                UUID(ledger.response["note_id"]),
                ledger.response["revision"],
            )
        else:
            note = Note(
                id=uuid4(),
                project_id=project_id,
                created_by=actor.id,
                current_revision=1,
                created_at=now(),
                updated_at=now(),
            )
            db.add(note)
            db.flush()
            row = add_revision(db, note, actor.id, body)
            ledger.response = {"note_id": str(note.id), "revision": row.revision}
        return {"action_id": str(ledger.id), "note": note_view(db, actor.id, note, row)}


@router.get("/notes/{note_id}", response_model=NoteView)
def get_note(
    project_id: UUID,
    note_id: UUID,
    actor: CurrentActor,
    revision: int | None = Query(None, ge=1),
):
    with transaction(actor.id) as db:
        note, row = load_note(db, actor.id, project_id, note_id, revision)
        return note_view(db, actor.id, note, row)


@router.patch("/notes/{note_id}", response_model=NoteAction)
def update_note(
    project_id: UUID,
    note_id: UUID,
    body: NoteUpdate,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as db:
        source_mounts.project(db, actor.id, project_id, write=True)
        # Prelock the union of current and proposed dependencies before any individual read.
        note = db.get(Note, note_id)
        previous = (
            db.get(NoteRevision, (note_id, note.current_revision))
            if note and note.project_id == project_id
            else None
        )
        if not previous:
            fail("NOTE_UNAVAILABLE", "笔记不存在或材料已不可访问。", 403)
        authorize_dependencies(
            db,
            actor.id,
            project_id,
            [*previous.authorization_evidence_ids, *body.evidence_ids],
            [*previous.authorization_query_run_ids, *body.query_run_ids],
        )
        ledger, old = action_lookup(
            db,
            actor.id,
            project_id,
            idempotency_key,
            "notes.update",
            {"note_id": str(note_id), **body.model_dump(mode="json")},
        )
        if old:
            note, row = load_note(
                db, actor.id, project_id, note_id, ledger.response["revision"]
            )
        else:
            if note.current_revision != body.expected_revision:
                fail("NOTE_REVISION_CONFLICT", "笔记已更新，请读取当前修订。")
            note.current_revision += 1
            note.updated_at = now()
            row = add_revision(db, note, actor.id, body, previous)
            ledger.response = {"note_id": str(note.id), "revision": row.revision}
        return {"action_id": str(ledger.id), "note": note_view(db, actor.id, note, row)}


@router.post("/notes/{note_id}/accept", response_model=NoteAction)
def accept_note(
    project_id: UUID,
    note_id: UUID,
    body: NoteAccept,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as db:
        source_mounts.project(db, actor.id, project_id, write=True)
        login = db.get(LoginSession, actor.session_hash) if actor.session_hash else None
        if not login or login.user_id != actor.id or login.expires_at <= now():
            fail(
                "HUMAN_AUTHORIZATION_REQUIRED",
                "须由当前登录用户手动采纳指定修订。",
                403,
            )
        note, row = load_note(db, actor.id, project_id, note_id)
        if note.current_revision != body.expected_revision:
            fail("NOTE_REVISION_CONFLICT", "仅可采纳当前指定修订。")
        ledger, old = action_lookup(
            db,
            actor.id,
            project_id,
            idempotency_key,
            "notes.accept",
            {"note_id": str(note_id), **body.model_dump(mode="json")},
        )
        if not old and not db.get(NoteAcceptance, (note.id, row.revision)):
            db.add(
                NoteAcceptance(
                    note_id=note.id,
                    revision=row.revision,
                    project_id=project_id,
                    accepted_by=actor.id,
                    session_hash=actor.session_hash,
                    accepted_at=now(),
                )
            )
            db.flush()
        ledger.response = {"note_id": str(note.id), "revision": row.revision}
        return {"action_id": str(ledger.id), "note": note_view(db, actor.id, note, row)}


def notes_listing(db, actor, project_id, cursor, page_size, note_id=None):
    project = source_mounts.project(db, actor.id, project_id)
    stmt = select(NoteRevision).where(NoteRevision.project_id == project_id)
    if note_id:
        stmt = stmt.where(NoteRevision.note_id == note_id)
    rows = list(db.scalars(stmt.order_by(NoteRevision.note_id, NoteRevision.revision)))
    # RLS filters unavailable revisions; prelock the complete visible dependency union.
    authorize_dependencies(
        db,
        actor.id,
        project_id,
        [e for r in rows for e in r.authorization_evidence_ids],
        [q for r in rows for q in r.authorization_query_run_ids],
    )
    values = []
    for row in rows:
        note = db.get(Note, row.note_id)
        if note_id or note.current_revision == row.revision:
            values.append(note_view(db, actor.id, note, row, summary=True))
    if note_id:
        filters = {
            "kind": "note_revisions",
            "project_id": str(project_id),
            "note_id": str(note_id),
        }
        last = read_cursor(cursor, filters)
        try:
            offset = int(last or 0)
            if offset < 0:
                raise ValueError
        except ValueError:
            fail("INVALID_CURSOR", "分页游标无效。", 422)
        result = {
            "items": values[offset : offset + page_size],
            "total": len(values),
            "next_cursor": make_cursor(str(offset + page_size), filters)
            if len(values) > offset + page_size
            else None,
        }
    else:
        result = paginate(values, cursor, page_size, "notes", project_id)
    return {
        **result,
        "allowed_actions": {
            "create": project_role(db, actor.id, project) in {"owner", "editor"}
        },
    }


@router.get("/notes", response_model=NoteList)
def list_notes(
    project_id: UUID,
    actor: CurrentActor,
    cursor: str | None = Query(None, max_length=512),
    page_size: int = Query(50, ge=1, le=100),
):
    with transaction(actor.id) as db:
        return notes_listing(db, actor, project_id, cursor, page_size)


@router.get("/notes/{note_id}/revisions", response_model=NoteList)
def note_revisions(
    project_id: UUID,
    note_id: UUID,
    actor: CurrentActor,
    cursor: str | None = Query(None, max_length=512),
    page_size: int = Query(50, ge=1, le=100),
):
    with transaction(actor.id) as db:
        return notes_listing(db, actor, project_id, cursor, page_size, note_id)
