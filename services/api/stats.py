"""Statistics (contracts/p2.md §三): requests are checked here and computed by the worker as `stats` jobs."""

import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from engine import query
from engine import stats as engine_stats
from services.api import effective
from services.api.access import WRITE, Paging, require_project, token_project
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, forbidden, not_found
from services.api.jobs import enqueue
from services.api.metadata import field_types
from services.api.models import StatResult, Subcorpus
from services.api.search import (
    LayersInput,
    Scope,
    compile_query,
    corpus_tagset,
    resolve_scope,
)
from services.api.views import job_view, stat_view

router = APIRouter(prefix="/api")

Unit = Literal["word", "lemma"]
Measure = Literal["mi", "logdice", "t", "ll"]


class StatsInput(BaseModel):
    project_id: UUID | None = None  # needed only for a built-in corpus scope
    top: int = Field(default=200, ge=1, le=2000)


class FrequencyInput(StatsInput):
    """unit deprel, or unit pos with layers.pos, is counted in PostgreSQL over effective annotations."""

    scope: Scope
    unit: Literal["word", "lemma", "pos", "deprel"] = "word"
    pos: str | None = Field(default=None, max_length=20)
    min_freq: int = Field(default=1, ge=1)
    layers: LayersInput | None = None


class NgramsInput(StatsInput):
    scope: Scope
    n: int = Field(default=2, ge=2, le=4)
    unit: Unit = "word"
    pos_pattern: list[str | None] | None = None
    min_freq: int = Field(default=2, ge=1)

    @model_validator(mode="after")
    def pattern_length(self):
        if self.pos_pattern is not None and len(self.pos_pattern) != self.n:
            raise ValueError("pos_pattern 长度须等于 n")
        return self


class CollocationsInput(StatsInput):
    scope: Scope
    node: str = Field(min_length=1, max_length=1000)
    window: int = Field(default=5, ge=1, le=20)
    unit: Unit = "word"
    pos: str | None = Field(default=None, max_length=20)
    measures: list[Measure] = Field(
        default=["mi", "logdice", "t", "ll"], min_length=1, max_length=4
    )
    min_freq: int = Field(default=3, ge=1)


class KeywordsInput(StatsInput):
    target: Scope
    reference: Scope
    unit: Unit = "word"
    measure: Literal["ll", "log_ratio"] = "ll"
    min_freq: int = Field(default=3, ge=1)


class DistributionInput(StatsInput):
    scope: Scope
    query: str | None = Field(default=None, max_length=1000)
    field: str = Field(min_length=1, max_length=200)
    bins: int = Field(default=10, ge=1, le=100)


class ExportInput(BaseModel):
    format: Literal["csv", "xlsx"]


def _tagset(db, scope, user):
    corpus, _ = resolve_scope(db, scope, user)
    return corpus_tagset(corpus)


def _check_pos(tagset, *tags):
    for tag in tags:
        if tag:
            try:
                engine_stats.pos_tags(tag, tagset)
            except query.QueryError as e:
                raise ApiError(422, "VALIDATION_ERROR", e.message)


def _plain_query(text, tagset):
    """Statistics run queries in CWB only; `{…}` attributes are rejected."""
    if query.attrs(compile_query(text, tagset)):
        raise ApiError(422, "QUERY_INVALID", "统计中的查询式不支持 {…} 属性约束")


def _submit(db, user, method, body, scope):
    corpus, _ = resolve_scope(db, scope, user)
    if scope.subcorpus_id:
        project_id = db.get(Subcorpus, scope.subcorpus_id).project_id
    elif corpus.project_id:
        project_id = corpus.project_id
    else:
        project_id = body.project_id or token_project(user)
        if project_id is None:
            raise ApiError(422, "PROJECT_REQUIRED", "内置语料的统计须指定 project_id")
        require_project(db, project_id, user)
    params = {"method": method, **body.model_dump(mode="json", exclude={"project_id"})}
    job = enqueue(db, "stats", params, user.id, project_id)
    db.commit()
    return job_view(job)


@router.post("/stats/frequency")
def frequency(body: FrequencyInput, user: CurrentUser, db: Db):
    _check_pos(_tagset(db, body.scope, user), body.pos)
    corpus, _ = resolve_scope(db, body.scope, user)
    effective.check_layers(db, body.layers, corpus, user)
    return _submit(db, user, "frequency", body, body.scope)


@router.post("/stats/ngrams")
def ngrams(body: NgramsInput, user: CurrentUser, db: Db):
    _check_pos(_tagset(db, body.scope, user), *(body.pos_pattern or []))
    return _submit(db, user, "ngrams", body, body.scope)


@router.post("/stats/collocations")
def collocations(body: CollocationsInput, user: CurrentUser, db: Db):
    tagset = _tagset(db, body.scope, user)
    _plain_query(body.node, tagset)
    _check_pos(tagset, body.pos)
    return _submit(db, user, "collocations", body, body.scope)


@router.post("/stats/keywords")
def keywords(body: KeywordsInput, user: CurrentUser, db: Db):
    resolve_scope(db, body.reference, user)
    return _submit(db, user, "keywords", body, body.target)


@router.post("/stats/distribution")
def distribution(body: DistributionInput, user: CurrentUser, db: Db):
    if body.query:
        _plain_query(body.query, _tagset(db, body.scope, user))
    if body.field != "position":
        corpus, _ = resolve_scope(db, body.scope, user)
        if body.field not in field_types(db, corpus.id):
            raise ApiError(422, "INVALID_FIELD", f"未知元数据字段：{body.field}")
    return _submit(db, user, "distribution", body, body.scope)


def _load(db, stat_id, user, write=False) -> StatResult:
    stat = db.get(StatResult, stat_id)
    if not stat:
        raise not_found("统计结果")
    role = require_project(db, stat.project_id, user)
    if write and role not in WRITE and stat.created_by != user.id:
        raise forbidden()
    return stat


@router.get("/stats/{stat_id}")
def get_stat(stat_id: UUID, user: CurrentUser, db: Db):
    stat = _load(db, stat_id, user)
    try:
        rows = json.loads(Path(stat.rows_path).read_text(encoding="utf-8"))["rows"]
    except FileNotFoundError:
        raise not_found("统计结果文件") from None
    return stat_view(stat, rows[: stat.params.get("top", len(rows))])


@router.get("/projects/{project_id}/stats")
def list_stats(project_id: UUID, user: CurrentUser, db: Db, paging: Paging):
    require_project(db, project_id, user)
    stmt = (
        select(StatResult)
        .where(StatResult.project_id == project_id)
        .order_by(StatResult.created_at.desc(), StatResult.id)
    )
    return paging.run(db, stmt, stat_view)


@router.post("/stats/{stat_id}/export")
def export_stat(stat_id: UUID, body: ExportInput, user: CurrentUser, db: Db):
    stat = _load(db, stat_id, user)
    params = {"source": "stats", "stat_id": str(stat.id), "format": body.format}
    job = enqueue(db, "export", params, user.id, stat.project_id)
    db.commit()
    return job_view(job)


@router.delete("/stats/{stat_id}", status_code=204)
def delete_stat(stat_id: UUID, user: CurrentUser, db: Db):
    stat = _load(db, stat_id, user, write=True)
    path = Path(stat.rows_path)
    db.delete(stat)
    db.commit()
    path.unlink(missing_ok=True)
