"""Vocabulary level lists (contracts/p10.md §二): the built-in NGSL 1.2 and lists uploaded to a project.

The built-in list has a fixed id and is inserted on first use (ensure_builtin) from engine/data/ngsl.csv.
Upload: multipart name, language, file (CSV / TXT, `词,等级` per line, engine.vocab.parse), optional source and
license; owner / editor in a browser session. Delete: the list's project owner / editor; built-in lists 403.
"""

import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from engine import vocab as engine_vocab
from services.api.access import WRITE, human_only, require_project
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, forbidden, not_found
from services.api.models import VocabEntry, VocabList

router = APIRouter(prefix="/api")

NGSL_ID = uuid.UUID("5e7f0c1a-0b5a-4c1e-9a10-000000000012")
NGSL = {
    "name": "NGSL 1.2",
    "language": "en",
    "source": (
        "Browne, C., Culligan, B., & Phillips, J. The New General Service List (NGSL 1.2, 2023). "
        "https://www.newgeneralservicelist.com/new-general-service-list. "
        "等级为本平台按 SFI 频率排名分段（1–1000、1001–2000、2001–2809），不是 NGSL 官方分级"
    ),
    "license": "CC BY-SA 4.0",
}
MAX_BYTES = 5 * 1024 * 1024


def ensure_builtin(db):
    """Insert the built-in NGSL list once (ON CONFLICT: concurrent first requests insert it once)."""
    if db.get(VocabList, NGSL_ID):
        return
    entries, levels = engine_vocab.builtin()
    db.execute(
        pg_insert(VocabList)
        .values(id=NGSL_ID, project_id=None, levels=levels, **NGSL)
        .on_conflict_do_nothing()
    )
    for i in range(0, len(entries), 5000):
        db.execute(
            pg_insert(VocabEntry)
            .values(
                [
                    {"list_id": NGSL_ID, "form": f, "level": lv}
                    for f, lv in entries[i : i + 5000]
                ]
            )
            .on_conflict_do_nothing()
        )
    db.flush()


def list_view(v: VocabList, entries: int) -> dict:
    return {
        "id": v.id,
        "project_id": v.project_id,
        "builtin": v.project_id is None,
        "name": v.name,
        "language": v.language,
        "levels": v.levels,
        "source": v.source,
        "license": v.license,
        "entries": entries,
        "created_by": v.created_by,
        "created_at": v.created_at,
    }


def load_list(db, list_id, user, project_id=None) -> VocabList:
    """A list the user may use: built-in, or one of a project they belong to (that project when given)."""
    if list_id == NGSL_ID:
        ensure_builtin(db)
    v = db.get(VocabList, list_id)
    if not v:
        raise not_found("词表")
    if v.project_id is not None:
        if project_id is not None and v.project_id != project_id:
            raise not_found("词表")
        require_project(db, v.project_id, user)
    return v


@router.get("/projects/{project_id}/vocab-lists")
def list_lists(project_id: UUID, user: CurrentUser, db: Db):
    require_project(db, project_id, user)
    ensure_builtin(db)
    db.commit()
    counts = (
        select(VocabEntry.list_id, func.count().label("n"))
        .group_by(VocabEntry.list_id)
        .subquery()
    )
    rows = db.execute(
        select(VocabList, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.list_id == VocabList.id)
        .where(or_(VocabList.project_id.is_(None), VocabList.project_id == project_id))
        .order_by(VocabList.project_id.is_not(None), VocabList.created_at, VocabList.id)
    ).all()
    return {"items": [list_view(v, n) for v, n in rows]}


@router.post("/projects/{project_id}/vocab-lists", status_code=201)
def create_list(
    project_id: UUID,
    user: CurrentUser,
    db: Db,
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form(min_length=1, max_length=200)],
    language: Annotated[str, Form(min_length=1, max_length=20)],
    source: Annotated[str, Form(max_length=1000)] = "",
    license: Annotated[str, Form(max_length=200)] = "",
):
    human_only(user)
    require_project(db, project_id, user, WRITE)
    raw = file.file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ApiError(413, "TOO_LARGE", "词表文件不超过 5 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ApiError(
            422, "INVALID_FILE", "词表须为 UTF-8 编码的 CSV 或 TXT"
        ) from None
    language = language.strip()
    try:
        entries, levels, duplicates = engine_vocab.parse(text, language)
    except engine_vocab.ListError as e:
        raise ApiError(422, "INVALID_FILE", str(e)) from None
    v = VocabList(
        project_id=project_id,
        name=name.strip(),
        language=language,
        levels=levels,
        source=source.strip() or (file.filename or ""),
        license=license.strip(),
        created_by=user.id,
    )
    db.add(v)
    db.flush()
    for i in range(0, len(entries), 5000):
        db.execute(
            pg_insert(VocabEntry).values(
                [
                    {"list_id": v.id, "form": f, "level": lv}
                    for f, lv in entries[i : i + 5000]
                ]
            )
        )
    db.commit()
    return {**list_view(v, len(entries)), "duplicates": duplicates}


@router.delete("/vocab-lists/{list_id}", status_code=204)
def delete_list(list_id: UUID, user: CurrentUser, db: Db):
    human_only(user)
    v = db.get(VocabList, list_id)
    if not v:
        raise not_found("词表")
    if v.project_id is None:
        raise forbidden()
    require_project(db, v.project_id, user, WRITE)
    db.delete(v)
    db.commit()
