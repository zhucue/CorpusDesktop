"""Evidence basket (contracts/p2.md §四): pinned hits, stat rows and text, kept per project."""

import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from services.api.access import (
    WRITE,
    Paging,
    human_only,
    load_corpus,
    require_project,
)
from services.api.auth import CurrentUser, Db
from services.api.errors import forbidden, not_found
from services.api.jobs import enqueue
from services.api.models import Corpus, Document, Evidence, Sentence, StatResult
from services.api.search import aligned_texts
from services.api.views import evidence_view, job_view

router = APIRouter(prefix="/api")

PIN = ("owner", "editor", "annotator")


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search_query: str | None = Field(default=None, max_length=1000)
    scope: dict | None = None
    hit_id: str | None = Field(default=None, max_length=200)
    document_id: UUID | None = None
    start_cp: int | None = Field(default=None, ge=0)
    end_cp: int | None = Field(default=None, ge=0)
    stat_id: UUID | None = None
    row_key: str | None = Field(default=None, max_length=2000)
    sentence_index: int | None = Field(default=None, ge=0)


class EvidenceInput(BaseModel):
    kind: Literal["hit", "stat_row", "text"]
    ref: EvidenceRef = EvidenceRef()
    text: str = Field(min_length=1, max_length=20000)
    source: str = Field(max_length=1000)
    note: str | None = Field(default=None, max_length=5000)


class ExportInput(BaseModel):
    format: Literal["csv", "xlsx", "docx"]


def hit_sentence(db, doc, ref):
    """The sentence holding a pinned hit: by ref.sentence_index, else the one containing start_cp."""
    if ref.sentence_index is not None:
        return db.scalar(
            select(Sentence).where(
                Sentence.document_id == doc.id, Sentence.idx == ref.sentence_index
            )
        )
    return db.scalar(
        select(Sentence)
        .where(
            Sentence.document_id == doc.id,
            Sentence.start_cp <= ref.start_cp,
            Sentence.end_cp > ref.start_cp,
        )
        .order_by(Sentence.idx)
        .limit(1)
    )


def _flat(s: str) -> str:
    """Whitespace runs → one space (edge spaces kept, so the pieces around the match join correctly)."""
    return re.sub(r"\s+", " ", s)


def sentence_evidence(db, doc, ref):
    """A pinned hit is kept as its own sentence (parallel corpora: its sentence pair), never the KWIC window,
    which can run into unrelated neighbouring sentences. Returns (text, source, ref fields) or None:
    text = the sentence with the match in **bold** plus one `XX：…` line per aligned translation;
    ref gets sentence_index, sentence (plain), match [start, end) code points in it, aligned, document_title."""
    if ref.start_cp is None or ref.end_cp is None:
        return None
    s = hit_sentence(db, doc, ref)
    if s is None or not (s.start_cp <= ref.start_cp < s.end_cp):
        return None
    a = ref.start_cp - s.start_cp
    b = min(max(ref.end_cp - s.start_cp, a), len(s.text))
    before = _flat(s.text[:a]).lstrip()
    match = _flat(s.text[a:b])
    after = _flat(s.text[b:]).rstrip()
    aligned = aligned_texts(db, [s.id]).get(s.id, [])
    sentence = before + match + after
    lines = [f"{before}**{match}**{after}"] + [
        f"{x['language'].upper()}：{_flat(x['text'])}" for x in aligned
    ]
    corpus = db.get(Corpus, doc.corpus_id)
    source = f"{doc.title} · 句 {s.idx + 1} · {corpus.name}"
    fields = {
        "sentence_index": s.idx,
        "sentence": sentence,
        "match": [len(before), len(before) + len(match)],
        "aligned": aligned,
        "document_title": doc.title,
    }
    return "\n".join(lines), source, fields


@router.get("/projects/{project_id}/evidence")
def list_evidence(project_id: UUID, user: CurrentUser, db: Db, paging: Paging):
    require_project(db, project_id, user)
    stmt = (
        select(Evidence)
        .where(Evidence.project_id == project_id)
        .order_by(Evidence.created_at.desc(), Evidence.id)
    )
    return paging.run(db, stmt, evidence_view)


@router.post("/projects/{project_id}/evidence")
def create_evidence(project_id: UUID, body: EvidenceInput, user: CurrentUser, db: Db):
    require_project(db, project_id, user, PIN)
    ref = body.ref
    text, source, extra = body.text, body.source, {}
    if body.kind == "hit" and not ref.document_id and ref.hit_id:
        # hit_id is "<document id>:<start_cp>-<end_cp>" (engine.model.Hit); assistant cards send only that
        m = re.fullmatch(
            r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
            r":(\d+)-(\d+)",
            ref.hit_id,
        )
        if m:
            ref = ref.model_copy(
                update={
                    "document_id": UUID(m[1]),
                    "start_cp": int(m[2]),
                    "end_cp": int(m[3]),
                }
            )
    if ref.document_id:  # the pinned document must be readable by this user
        doc = db.get(Document, ref.document_id)
        if not doc:
            raise not_found("文档")
        load_corpus(db, doc.corpus_id, user)
        if body.kind == "hit" and (built := sentence_evidence(db, doc, ref)):
            text, source, extra = built
    if ref.stat_id:
        stat = db.get(StatResult, ref.stat_id)
        if not stat or stat.project_id != project_id:
            raise not_found("统计结果")
    if (
        body.kind == "hit"
        and ref.document_id
        and ref.start_cp is not None
        and ref.end_cp is not None
        and not ref.hit_id
    ):  # one key for the same hit, however it was sent (the basket matches pins by hit_id)
        ref = ref.model_copy(
            update={"hit_id": f"{ref.document_id}:{ref.start_cp}-{ref.end_cp}"}
        )
    if existing := _existing(db, project_id, body.kind, ref):
        return evidence_view(existing) | {"existing": True}
    item = Evidence(
        project_id=project_id,
        kind=body.kind,
        ref=ref.model_dump(mode="json", exclude_none=True) | extra,
        text=text,
        source=source,
        note=body.note,
        created_by=user.id,
    )
    db.add(item)
    db.commit()
    return evidence_view(item) | {"existing": False}


def _existing(db, project_id, kind, ref):
    """The basket keeps one item per hit (document + match offsets) and per stat row: pinning it again from the
    search page or the assistant returns that item instead of adding a duplicate."""
    if kind == "hit" and ref.document_id and None not in (ref.start_cp, ref.end_cp):
        key = {
            "document_id": str(ref.document_id),
            "start_cp": ref.start_cp,
            "end_cp": ref.end_cp,
        }
    elif kind == "stat_row" and ref.stat_id and ref.row_key is not None:
        key = {"stat_id": str(ref.stat_id), "row_key": ref.row_key}
    else:
        return None
    return db.scalar(
        select(Evidence)
        .where(
            Evidence.project_id == project_id,
            Evidence.kind == kind,
            Evidence.ref.contains(key),
        )
        .order_by(Evidence.created_at)
        .limit(1)
    )


@router.delete("/evidence/{evidence_id}", status_code=204)
def delete_evidence(evidence_id: UUID, user: CurrentUser, db: Db):
    human_only(user)
    item = db.get(Evidence, evidence_id)
    if not item:
        raise not_found("证据")
    role = require_project(db, item.project_id, user)
    if role not in WRITE and item.created_by != user.id:
        raise forbidden()
    db.delete(item)
    db.commit()


@router.post("/projects/{project_id}/evidence/export")
def export_evidence(project_id: UUID, body: ExportInput, user: CurrentUser, db: Db):
    require_project(db, project_id, user)
    params = {
        "source": "evidence",
        "project_id": str(project_id),
        "format": body.format,
    }
    job = enqueue(db, "export", params, user.id, project_id)
    db.commit()
    return job_view(job)
