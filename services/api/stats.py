"""Statistics (contracts/p2.md §三): requests are checked here and computed by the worker as `stats` jobs."""

import json
import re
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from engine import query
from engine import stats as engine_stats
from services.api import effective
from services.api.access import (
    WRITE,
    Paging,
    human_only,
    require_project,
    token_project,
)
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, forbidden, not_found
from services.api.jobs import enqueue
from services.api.metadata import field_types
from services.api.models import Document, StatResult, Subcorpus
from services.api.search import (
    AlignedInput,
    LayersInput,
    Scope,
    check_layer_problem,
    corpus_tagset,
    pg_answered,
    plan_aligned,
    plan_query,
    resolve_scope,
    with_span_layer,
)
from services.api.views import job_view, stat_view

router = APIRouter(prefix="/api")

Unit = Literal["word", "lemma"]
Measure = Literal["mi", "logdice", "t", "ll", "mi3", "delta_p", "z"]
_PARTS = re.compile(r"^(document|segments|field:.+)$")
_BY = re.compile(r"^(word|lemma|pos|left1|right1|meta:.+)$")


class StatsInput(BaseModel):
    project_id: UUID | None = None  # needed only for a built-in corpus scope
    top: int = Field(default=200, ge=1, le=2000)


class PunctInput(BaseModel):
    # word / lemma items made only of punctuation, symbols and digits are left out (engine.stats);
    # token totals and measures still count them.
    exclude_punct: bool = True


class FrequencyInput(StatsInput, PunctInput):
    """unit deprel, or unit pos with layers.pos, is counted in PostgreSQL over effective annotations;
    span_label / relation_label count effective spans of layers.span / relations of layers.relation (default:
    the corpus's most recently updated layer of that kind)."""

    scope: Scope
    unit: Literal["word", "lemma", "pos", "deprel", "span_label", "relation_label"] = (
        "word"
    )
    pos: str | None = Field(default=None, max_length=20)
    min_freq: int = Field(default=1, ge=1)
    layers: LayersInput | None = None
    # dispersion over parts (contracts/p8.md §二): document | segments | field:<字段>
    parts: str = Field(default="document", max_length=210, pattern=_PARTS.pattern)
    dispersion: bool = True


class NgramsInput(StatsInput, PunctInput):
    scope: Scope
    n: int = Field(default=2, ge=2, le=4)
    unit: Unit = "word"
    pos_pattern: list[str | None] | None = None
    contains: str | None = Field(
        default=None, max_length=200
    )  # word / lemma in some slot
    min_freq: int = Field(default=2, ge=1)

    @model_validator(mode="after")
    def pattern_length(self):
        if self.pos_pattern is not None and len(self.pos_pattern) != self.n:
            raise ValueError("pos_pattern 长度须等于 n")
        return self


class CollocationsInput(StatsInput, PunctInput):
    scope: Scope
    node: str = Field(min_length=1, max_length=1000)
    window: int = Field(default=5, ge=1, le=20)
    unit: Unit = "word"
    pos: str | None = Field(default=None, max_length=20)
    measures: list[Measure] = Field(
        default=["mi", "logdice", "t", "ll"], min_length=1, max_length=7
    )
    min_freq: int = Field(default=3, ge=1)


class KeywordsInput(StatsInput, PunctInput):
    target: Scope
    reference: Scope
    unit: Unit = "word"
    measure: Literal["ll", "log_ratio", "pct_diff", "odds_ratio"] = "ll"
    min_freq: int = Field(default=3, ge=1)
    direction: Literal["positive", "negative", "both"] = "positive"
    # only these words, whatever min_freq and direction (single-item comparison)
    items: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(
        default=None, min_length=1, max_length=50
    )


class DistributionInput(StatsInput):
    scope: Scope
    query: str | None = Field(default=None, max_length=1000)
    field: str = Field(min_length=1, max_length=200)
    bins: int = Field(default=10, ge=1, le=100)
    layers: LayersInput | None = None  # span layer of a `[标签]` query
    aligned: AlignedInput | None = None  # translation condition (contracts/p8.md §四)


class BreakdownInput(StatsInput):
    scope: Scope
    query: str = Field(min_length=1, max_length=1000)
    by: str = Field(default="word", max_length=210, pattern=_BY.pattern)
    min_freq: int = Field(default=1, ge=1)
    layers: LayersInput | None = None


class TranslationsInput(StatsInput, PunctInput):
    scope: Scope
    query: str = Field(min_length=1, max_length=1000)
    unit: Unit = "word"
    target_language: str | None = Field(default=None, min_length=1, max_length=20)
    measure: Literal["dice", "ll"] = "dice"
    top: int = Field(default=100, ge=1, le=2000)
    min_freq: int = Field(default=2, ge=1)
    layers: LayersInput | None = None


class ExportInput(BaseModel):
    format: Literal["csv", "xlsx", "docx"]


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


def _plain_query(text, tagset, allow_span=False):
    """Statistics run queries in CWB; `{…}` attributes are rejected, `[标签]` only as a whole query
    (distribution, answered from PostgreSQL)."""
    ast, cqp = plan_query(text, tagset)
    if query.attrs(cqp):
        raise ApiError(422, "QUERY_INVALID", "统计中的查询式不支持 {…} 属性约束")
    if query.spans(cqp) and not (allow_span and query.pure_span(ast)):
        raise ApiError(422, "QUERY_INVALID", "统计中的片段标签只能单独使用，如 [时态]")
    return cqp


def _check_field(db, corpus, field):
    if field not in field_types(db, corpus.id):
        raise ApiError(422, "INVALID_FIELD", f"未知元数据字段：{field}")


def _hit_query(db, user, body):
    """Check the query of a breakdown / translation statistic as search does; `{…}` / `[…]` slots are
    answered from the layers (stored in the job), a whole query of one `{…}` or `[…]` is rejected (those
    hits come from PostgreSQL, not CWB). Returns (corpus, body with the span layer filled in)."""
    corpus, _ = resolve_scope(db, body.scope, user)
    ast, cqp = plan_query(body.query, corpus_tagset(corpus))
    if pg_answered(ast, cqp):
        raise ApiError(
            422, "QUERY_INVALID", "该统计不支持单独的 {…} 或 […] 查询，请加上词或词性"
        )
    layers = effective.check_layers(db, body.layers, corpus, user)
    with_span_layer(db, cqp, layers, corpus, user)
    check_layer_problem(db, corpus, user, ast, layers)
    if layers.get("span"):
        body = body.model_copy(
            update={
                "layers": (body.layers or LayersInput()).model_copy(
                    update={"span": layers["span"].id}
                )
            }
        )
    return corpus, body


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
    if body.parts.startswith("field:"):
        _check_field(db, corpus, body.parts[6:])
    layers = effective.check_layers(db, body.layers, corpus, user)
    if body.unit in ("span_label", "relation_label"):
        kind = body.unit.split("_")[0]
        layer = layers[kind] or effective.default_layer(db, corpus, user, kind)
        if layer is None:
            raise ApiError(422, "INVALID_LAYER", f"该语料库没有 {kind} 标注层")
        body = body.model_copy(
            update={
                "layers": (body.layers or LayersInput()).model_copy(
                    update={kind: layer.id}
                )
            }
        )
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
    if body.reference == body.target:
        raise ApiError(422, "VALIDATION_ERROR", "参照与目标相同，请选择另一个参照")
    return _submit(db, user, "keywords", body, body.target)


@router.post("/stats/breakdown")
def breakdown(body: BreakdownInput, user: CurrentUser, db: Db):
    corpus, body = _hit_query(db, user, body)
    if body.by.startswith("meta:"):
        _check_field(db, corpus, body.by[5:])
    return _submit(db, user, "breakdown", body, body.scope)


@router.post("/stats/translations")
def translations(body: TranslationsInput, user: CurrentUser, db: Db):
    corpus, _ = resolve_scope(db, body.scope, user)
    if not corpus.parallel:
        raise ApiError(422, "NOT_PARALLEL", "译法统计只能用于平行语料")
    corpus, body = _hit_query(db, user, body)
    if body.target_language is not None:
        languages = db.scalars(
            select(Document.language).where(Document.corpus_id == corpus.id).distinct()
        ).all()
        if body.target_language not in languages:
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                f"该平行语料没有 {body.target_language} 一侧（现有：{'、'.join(sorted(languages))}）",
            )
    return _submit(db, user, "translations", body, body.scope)


@router.post("/stats/distribution")
def distribution(body: DistributionInput, user: CurrentUser, db: Db):
    if body.query:
        cqp = _plain_query(body.query, _tagset(db, body.scope, user), allow_span=True)
        corpus, _ = resolve_scope(db, body.scope, user)
        layers = effective.check_layers(db, body.layers, corpus, user)
        with_span_layer(db, cqp, layers, corpus, user)
        plan_aligned(db, corpus, user, body.aligned, layers)  # 422 NOT_PARALLEL / QUERY_INVALID
        if layers.get("span"):
            body = body.model_copy(
                update={
                    "layers": (body.layers or LayersInput()).model_copy(
                        update={"span": layers["span"].id}
                    )
                }
            )
    elif body.aligned:
        raise ApiError(422, "VALIDATION_ERROR", "译文条件须与查询式一起使用")
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
    human_only(user)
    stat = _load(db, stat_id, user, write=True)
    path = Path(stat.rows_path)
    db.delete(stat)
    db.commit()
    path.unlink(missing_ok=True)
