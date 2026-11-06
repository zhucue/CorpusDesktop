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
from engine.metrics import lang_code
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


def _project_for(db, user, scope, project_id=None):
    """The project a statistic of a scope belongs to (a built-in corpus needs project_id)."""
    corpus, _ = resolve_scope(db, scope, user)
    if scope.subcorpus_id:
        return db.get(Subcorpus, scope.subcorpus_id).project_id
    if corpus.project_id:
        return corpus.project_id
    project_id = project_id or token_project(user)
    if project_id is None:
        raise ApiError(422, "PROJECT_REQUIRED", "内置语料的统计须指定 project_id")
    require_project(db, project_id, user)
    return project_id


def _submit(db, user, method, body, scope, extra=None):
    project_id = _project_for(db, user, scope, body.project_id)
    params = {"method": method, **body.model_dump(mode="json", exclude={"project_id"})}
    params.update(extra or {})
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


def _scope_project(db, user, scope):
    """Project of a scope (after access checks); None for a built-in corpus."""
    corpus, _ = resolve_scope(db, scope, user)
    if scope.subcorpus_id:
        return db.get(Subcorpus, scope.subcorpus_id).project_id
    return corpus.project_id


def _same_project(db, user, scopes, message):
    """Scopes compared in one statistic belong to one project (built-in corpora go with any)."""
    projects = {p for sc in scopes if (p := _scope_project(db, user, sc)) is not None}
    if len(projects) > 1:
        raise ApiError(422, "VALIDATION_ERROR", message)


@router.post("/stats/keywords")
def keywords(body: KeywordsInput, user: CurrentUser, db: Db):
    resolve_scope(db, body.reference, user)
    if body.reference == body.target:
        raise ApiError(422, "VALIDATION_ERROR", "参照与目标相同，请选择另一个参照")
    _same_project(
        db, user, [body.target, body.reference], "目标与参照范围须在同一项目内"
    )
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
        plan_aligned(
            db, corpus, user, body.aligned, layers
        )  # 422 NOT_PARALLEL / QUERY_INVALID
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


# ---------------------------------------------------------------- P10 (contracts/p10.md §一~§五)

PER_RELATION = ("word_sketch", "sketch_diff")
TextMetric = Literal[
    "words",
    "sentences",
    "ttr",
    "sttr",
    "mtld",
    "lexical_density",
    "mean_sentence_length",
    "mean_dependency_distance",
    "flesch_reading_ease",
    "flesch_kincaid_grade",
]
FieldName = Annotated[str, Field(min_length=1, max_length=200)]
HitQuery = Annotated[str, Field(min_length=1, max_length=1000)]


class TextMetricsInput(StatsInput):
    scope: Scope
    metrics: list[TextMetric] | None = Field(default=None, min_length=1)
    group_by: FieldName | None = None
    sttr_window: int = Field(default=1000, ge=10, le=100_000)
    top: int = Field(default=2000, ge=1, le=100_000)  # documents shown


class VocabProfileInput(StatsInput):
    scope: Scope
    list_id: UUID
    by: FieldName = "corpus"  # corpus | document | <metadata field>
    top: int = Field(default=2000, ge=1, le=100_000)


class TidyExportInput(BaseModel):
    project_id: UUID | None = None  # built-in corpus scope
    scope: Scope
    queries: list[HitQuery] = Field(default=[], max_length=10)
    metrics: bool = False
    format: Literal["csv", "xlsx"] = "csv"


class CompareItem(BaseModel):
    label: Annotated[str, Field(min_length=1, max_length=100)]
    scope: Scope
    query: HitQuery


class CompareInput(StatsInput):
    items: list[CompareItem] = Field(min_length=2, max_length=10)
    by: FieldName | None = None
    test: Literal["none", "mann_whitney", "spearman"] = "none"

    @model_validator(mode="after")
    def test_fits(self):
        if self.test == "mann_whitney" and len(self.items) != 2:
            raise ValueError("Mann-Whitney 检验需要恰好两项")
        if self.test == "spearman" and not self.by:
            raise ValueError("Spearman 检验需要 by（数值字段）")
        return self


class SketchInput(StatsInput):
    scope: Scope
    pos: str | None = Field(default=None, max_length=20)
    layers: LayersInput | None = None  # layers.dep: the dependency layer
    min_freq: int = Field(default=2, ge=1)
    top: int = Field(default=25, ge=1, le=500)  # per relation column


class WordSketchInput(SketchInput):
    lemma: FieldName


class SketchDiffInput(SketchInput):
    lemma_a: FieldName
    lemma_b: FieldName

    @model_validator(mode="after")
    def different(self):
        if self.lemma_a.strip().lower() == self.lemma_b.strip().lower():
            raise ValueError("两个词元相同")
        return self


def _query_layers(db, user, corpus, text):
    """Check a hit query of a tidy export / comparison as search does; {span: id} when it needs a span layer
    (the corpus default), else None. A whole query of one `{…}` or `[…]` is counted in PostgreSQL by the
    worker, as search answers it."""
    ast, cqp = plan_query(text, corpus_tagset(corpus))
    layers = effective.check_layers(db, None, corpus, user)
    with_span_layer(db, cqp, layers, corpus, user)
    check_layer_problem(db, corpus, user, ast, layers)
    return {"span": str(layers["span"].id)} if layers.get("span") else None


@router.post("/stats/text_metrics")
def text_metrics(body: TextMetricsInput, user: CurrentUser, db: Db):
    corpus, _ = resolve_scope(db, body.scope, user)
    if body.group_by:
        _check_field(db, corpus, body.group_by)
    return _submit(db, user, "text_metrics", body, body.scope)


def _corpus_languages(corpus) -> set:
    """Language codes of a corpus: the index profile's languages, else its declared language."""
    langs = (corpus.meta or {}).get("languages") or [corpus.language]
    return {lang_code(x) for x in langs if x}


@router.post("/stats/vocab_profile")
def vocab_profile(body: VocabProfileInput, user: CurrentUser, db: Db):
    from services.api.vocab import load_list

    corpus, _ = resolve_scope(db, body.scope, user)
    if body.by not in ("corpus", "document"):
        _check_field(db, corpus, body.by)
    project_id = _project_for(db, user, body.scope, body.project_id)
    v = load_list(db, body.list_id, user, project_id)
    if v.language and lang_code(v.language) not in _corpus_languages(corpus):
        raise ApiError(422, "VALIDATION_ERROR", "词表语言与语料不一致")
    db.commit()  # the built-in list, inserted on first use
    return _submit(db, user, "vocab_profile", body, body.scope)


@router.post("/stats/tidy_export")
def tidy_export(body: TidyExportInput, user: CurrentUser, db: Db):
    corpus, _ = resolve_scope(db, body.scope, user)
    project_id = _project_for(db, user, body.scope, body.project_id)
    layers = [_query_layers(db, user, corpus, q) for q in body.queries]
    params = {
        "source": "tidy",
        **body.model_dump(mode="json", exclude={"project_id", "format"}),
        "query_layers": layers,
        # csv: the table and its codebook in one zip
        "format": "zip" if body.format == "csv" else "xlsx",
        "table_format": body.format,
    }
    job = enqueue(db, "export", params, user.id, project_id)
    db.commit()
    return job_view(job)


@router.post("/stats/compare")
def compare(body: CompareInput, user: CurrentUser, db: Db):
    layers = []
    for item in body.items:
        corpus, _ = resolve_scope(db, item.scope, user)
        layers.append(_query_layers(db, user, corpus, item.query))
        if body.by:
            types = field_types(db, corpus.id)
            if body.by not in types:
                raise ApiError(
                    422, "INVALID_FIELD", f"{item.label}：未知元数据字段 {body.by}"
                )
            if body.test == "spearman" and types[body.by] != "number":
                raise ApiError(
                    422, "VALIDATION_ERROR", f"Spearman 检验需要数值字段：{body.by}"
                )
    _same_project(db, user, [i.scope for i in body.items], "对比的范围须在同一项目内")
    first = body.items[0].scope
    extra = {"scope": first.model_dump(mode="json"), "query_layers": layers}
    return _submit(db, user, "compare", body, first, extra)


def _ready_dep_layer(db, corpus, user):
    """The corpus's most recently updated finished (status ready) dependency layer in the user's projects."""
    from services.api.models import AnnotationLayer, Project, ProjectMember

    stmt = (
        select(AnnotationLayer)
        .join(
            ProjectMember,
            (ProjectMember.project_id == AnnotationLayer.project_id)
            & (ProjectMember.user_id == user.id),
        )
        .join(Project, Project.id == AnnotationLayer.project_id)
        .where(
            AnnotationLayer.kind == "dep",
            AnnotationLayer.corpus_id == corpus.id,
            AnnotationLayer.status == "ready",
            Project.deleted_at.is_(None),
        )
        .order_by(AnnotationLayer.updated_at.desc(), AnnotationLayer.id)
        .limit(1)
    )
    if token_project(user) is not None:
        stmt = stmt.where(AnnotationLayer.project_id == token_project(user))
    return db.scalar(stmt)


def _dependencies(db, user, body):
    """Where the dependencies come from: layers.dep, else the index's system dependencies (Stanza at
    import), else the corpus's latest finished dependency layer; none → 422 NO_DEPENDENCIES. Returns the body
    with layers.dep set when a layer is used."""
    from engine import cwb
    from services.api.storage import corpus_key, index_dir

    corpus, _ = resolve_scope(db, body.scope, user)
    _check_pos(corpus_tagset(corpus), body.pos)
    layers = effective.check_layers(db, body.layers, corpus, user)
    if layers["dep"] is not None:
        return body
    if cwb.has_values(index_dir(corpus.id), corpus_key(corpus.id), "deprel"):
        return body
    layer = _ready_dep_layer(db, corpus, user)
    if layer is None:
        raise ApiError(
            422, "NO_DEPENDENCIES", "该语料没有依存标注，请先在标注页建依存层"
        )
    return body.model_copy(update={"layers": LayersInput(dep=layer.id)})


@router.post("/stats/word_sketch")
def word_sketch(body: WordSketchInput, user: CurrentUser, db: Db):
    body = _dependencies(db, user, body)
    return _submit(db, user, "word_sketch", body, body.scope)


@router.post("/stats/sketch_diff")
def sketch_diff(body: SketchDiffInput, user: CurrentUser, db: Db):
    body = _dependencies(db, user, body)
    return _submit(db, user, "sketch_diff", body, body.scope)


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
    # word sketch / sketch diff: `top` is per relation column, every stored row is shown
    limit = None if stat.method in PER_RELATION else stat.params.get("top")
    return stat_view(stat, rows[:limit])


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
