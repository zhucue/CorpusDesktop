"""Method appendix (contracts/p8.md §六): collect statistics results, searches, annotation layers and evidence of a
project, then write the appendix with engine.methods. JSON {markdown, citations}, or ?format=docx (synchronous)."""

import io
import os
import re
from datetime import UTC, datetime
from importlib import metadata as pkg
from types import SimpleNamespace
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from engine import methods as em
from engine.nlp import lang_code
from services.api import agreement as agreement_api
from services.api import search as search_api
from services.api import spans as spans_api
from services.api.access import require_project
from services.api.annotators import layer_annotators
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, not_found
from services.api.metadata import subcorpus_stats
from services.api.models import (
    AlignmentAnnotation,
    Annotation,
    AnnotationLayer,
    Corpus,
    Document,
    Evidence,
    LabelSet,
    RelationAnnotation,
    SpanAnnotation,
    StatResult,
    Subcorpus,
)

router = APIRouter(prefix="/api")

CWB_VERSION = "3.5.0"  # deploy/Dockerfile.api and Dockerfile.worker install cwb 3.5.0
LAYER_ROWS = {
    "pos": Annotation,
    "dep": Annotation,
    "span": SpanAnnotation,
    "relation": RelationAnnotation,
    "alignment": AlignmentAnnotation,
}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class SearchSpec(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    scope: search_api.Scope
    aligned: dict | None = None


class AppendixInput(BaseModel):
    stat_ids: list[UUID] = Field(default=[], max_length=50)
    searches: list[SearchSpec] = Field(default=[], max_length=20)
    layer_ids: list[UUID] = Field(default=[], max_length=20)
    evidence: bool = False
    style: Literal["gbt7714", "apa"] = "gbt7714"


def _time(t):
    return f"{t.astimezone(UTC):%Y-%m-%d %H:%M} UTC" if t else None


def _version(name):
    try:
        return pkg.version(name)
    except pkg.PackageNotFoundError:
        return None


class _Corpora:
    """Corpora and subcorpora the appendix mentions, in order of first use."""

    def __init__(self, db):
        self.db = db
        self.items = {}

    def _corpus(self, corpus_id):
        cid = str(corpus_id)
        if cid not in self.items:
            corpus = self.db.get(Corpus, UUID(cid))
            if corpus is None:
                return None
            self.items[cid] = (corpus, {})
        return self.items[cid]

    def scope(self, scope) -> str:
        """Register a scope dict ({corpus_id} | {subcorpus_id} | {corpus_id, filter}); return its display name."""
        scope = scope or {}
        if scope.get("subcorpus_id"):
            sub = self.db.get(Subcorpus, UUID(str(scope["subcorpus_id"])))
            if sub is None:
                return "（子库已删除）"
            entry = self._corpus(sub.corpus_id)
            if entry is None:
                return sub.name
            entry[1].setdefault(f"sub:{sub.id}", (sub.name, sub))
            return f"{entry[0].name} / {sub.name}"
        if not scope.get("corpus_id"):
            return "—"
        entry = self._corpus(scope["corpus_id"])
        if entry is None:
            return "（语料库已删除）"
        if scope.get("filter"):
            name = "临时筛选"
            key = f"filter:{em.as_json(scope['filter'])}"
            entry[1].setdefault(
                key,
                (name, SimpleNamespace(corpus_id=entry[0].id, filter=scope["filter"])),
            )
            return f"{entry[0].name}（筛选 {em.as_json(scope['filter'])}）"
        return entry[0].name

    def view(self):
        out = []
        for corpus, subs in self.items.values():
            item = {
                "name": corpus.name,
                "language": corpus.language,
                **(corpus.stats or {}),
                "index_version": corpus.index_version,
                "meta": corpus.meta or {},
                "builtin": corpus.project_id is None,
                "subcorpora": [],
            }
            for name, sub in subs.values():
                try:
                    size = subcorpus_stats(self.db, sub)
                except ValueError:
                    size = {}
                item["subcorpora"].append({"name": name, "filter": sub.filter, **size})
            out.append(item)
        return out

    def tools(self):
        """Annotation tools by the document languages of the corpora (UD treebanks keep their own annotation)."""
        ud, auto = False, []
        for corpus, _ in self.items.values():
            if "UniversalDependencies" in str(
                (corpus.meta or {}).get("source_url", "")
            ):
                ud = True
            else:
                auto.append(corpus.id)
        langs = set()
        if auto:
            rows = self.db.scalars(
                select(Document.language).where(Document.corpus_id.in_(auto)).distinct()
            )
            langs = {lang_code(x) for x in rows}
            langs |= {
                lang_code(c.language) for c, _ in self.items.values() if c.id in auto
            }
        return {
            "platform": (os.environ.get("APP_VERSION") or "").strip() or "dev",
            "jieba": _version("jieba"),
            "stanza": _version("stanza"),
            "cwb": CWB_VERSION,
            "zh": "zh" in langs,
            "en": "en" in langs,
            "ud": ud,
        }


def _scope_in_project(db, scope: search_api.Scope, project_id) -> bool:
    """A search scope the appendix may describe: a subcorpus of this project, or a built-in corpus or a corpus
    of this project (with or without a temporary filter)."""
    if scope.subcorpus_id:
        sub = db.get(Subcorpus, scope.subcorpus_id)
        return sub is not None and sub.project_id == project_id
    corpus = db.get(Corpus, scope.corpus_id)
    return corpus is not None and corpus.project_id in (None, project_id)


def _count_search(db, user, spec: SearchSpec, corpora: _Corpora):
    """Count a search whose scope passed _scope_in_project; search() repeats the user's access checks."""
    item = {
        "query": spec.query,
        "scope": corpora.scope(spec.scope.model_dump(mode="json", exclude_none=True)),
        "aligned": spec.aligned,
        "searched_at": _time(datetime.now(UTC)),
    }
    fields = {"scope": spec.scope, "query": spec.query, "page_size": 1}
    if spec.aligned:
        if "aligned" not in search_api.SearchInput.model_fields:
            item["error"] = "译文条件检索不可用"
            return item
        fields["aligned"] = spec.aligned
    try:
        req = search_api.SearchInput.model_validate(fields)
        item["counts"] = search_api.search(req, user, db)["counts"]
    except ApiError as e:
        item["error"] = e.message
    except ValueError as e:
        item["error"] = str(e)
    return item


def _stat_view(stat: StatResult, corpora: _Corpora):
    p = stat.params or {}
    reference = p.get("reference")
    return {
        "method": stat.method,
        "params": p,
        "scope": corpora.scope(stat.scope),
        "reference": corpora.scope(reference) if reference else None,
        "totals": stat.totals,
        "columns": [c["key"] for c in stat.columns or []],
        "index_version": stat.index_version,
        "created_at": _time(stat.created_at),
    }


def _items(db, layer):
    model = LAYER_ROWS[layer.kind]
    where = [model.layer_id == layer.id]
    if layer.kind == "span":
        where += [SpanAnnotation.label != "", SpanAnnotation.status != "rejected"]
    elif layer.kind == "relation":
        where.append(RelationAnnotation.status != "rejected")
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


def _agreement(db, layer, user):
    if layer.mode != "multi" or len(layer_annotators(layer)) < 2:
        return None
    try:
        out = agreement_api.agreement(layer.id, user, db)
    except ApiError:
        return None
    kappas = [
        p["kappa"] for p in out.get("pairwise") or [] if p.get("kappa") is not None
    ]
    return {
        "kappa": sum(kappas) / len(kappas) if kappas else None,
        "alpha": out.get("alpha"),
        "n": out.get("n", 0),
    }


def _sample(db, layer, user, corpora):
    """meta.sample of a sampling layer (contracts/p8.md §五) and its coding summary when available."""
    sample = dict((getattr(layer, "meta", None) or {}).get("sample") or {})
    if not sample:
        return None, None
    sample["scope"] = corpora.scope(sample.get("scope"))
    summary = None
    summarize = getattr(spans_api, "sample_summary", None)
    if summarize is not None:
        try:
            summary = summarize(layer_id=layer.id, user=user, db=db)
        except ApiError:
            summary = None
    return sample, summary


def _layer_view(db, layer, user, corpora):
    corpora.scope({"corpus_id": layer.corpus_id})
    if layer.tgt_corpus_id:
        corpora.scope({"corpus_id": layer.tgt_corpus_id})
    label_set = db.get(LabelSet, layer.label_set_id) if layer.label_set_id else None
    sample, summary = _sample(db, layer, user, corpora)
    return {
        "name": layer.name,
        "kind": layer.kind,
        "label_set": label_set.name if label_set else None,
        "labels": len(label_set.labels or []) if label_set else None,
        "mode": layer.mode,
        "annotators": len(layer_annotators(layer)),
        "items": _items(db, layer),
        "agreement": _agreement(db, layer, user),
        "sample": sample,
        "sample_summary": summary,
    }


def _search_key(spec: SearchSpec):
    # Sampling layers store `aligned` via model_dump() (None keys kept); agent-passed ones usually omit them.
    aligned = {k: v for k, v in (spec.aligned or {}).items() if v is not None}
    return (
        spec.query,
        em.as_json(spec.scope.model_dump(mode="json")),
        em.as_json(aligned or None),
    )


def collect(db, project_id, body: AppendixInput, user) -> dict:
    corpora = _Corpora(db)
    stat_ids = list(dict.fromkeys(body.stat_ids))
    for spec in body.searches:
        if not _scope_in_project(db, spec.scope, project_id):
            raise not_found("检索范围")
    searches = list(body.searches)
    seen = {_search_key(s) for s in searches}

    def add_search(spec):
        """A search the appendix found itself (evidence, sampling layer); skipped when out of the project."""
        key = _search_key(spec)
        if key not in seen and _scope_in_project(db, spec.scope, project_id):
            seen.add(key)
            searches.append(spec)

    if body.evidence:
        rows = db.scalars(
            select(Evidence)
            .where(Evidence.project_id == project_id)
            .order_by(Evidence.created_at, Evidence.id)
        )
        for e in rows:
            ref = e.ref or {}
            if e.kind == "stat_row" and ref.get("stat_id"):
                sid = UUID(str(ref["stat_id"]))
                stat = db.get(StatResult, sid)  # deleted results are skipped
                if sid not in stat_ids and stat and stat.project_id == project_id:
                    stat_ids.append(sid)
            elif e.kind == "hit" and ref.get("search_query") and ref.get("scope"):
                try:
                    spec = SearchSpec(query=ref["search_query"], scope=ref["scope"])
                except ValueError:
                    continue
                add_search(spec)
    stats = []
    for sid in stat_ids:
        stat = db.get(StatResult, sid)
        if stat is None or stat.project_id != project_id:
            raise not_found("统计结果")
        stats.append(_stat_view(stat, corpora))
    layers = []
    for lid in dict.fromkeys(body.layer_ids):
        layer = db.get(AnnotationLayer, lid)
        if layer is None or layer.project_id != project_id:
            raise not_found("标注层")
        layers.append(_layer_view(db, layer, user, corpora))
        sample = (layer.meta or {}).get("sample") or {}
        if sample.get("query") and sample.get("scope"):
            try:  # the sampled search, counted now like any other search (hits / sentences / documents)
                spec = SearchSpec(
                    query=sample["query"],
                    scope=sample["scope"],
                    aligned=sample.get("aligned") or None,
                )
            except ValueError:
                continue
            add_search(spec)
    counted = [_count_search(db, user, s, corpora) for s in searches]
    return {
        "corpora": corpora.view(),
        "tools": corpora.tools(),
        "searches": counted,
        "stats": stats,
        "layers": layers,
    }


# ---- DOCX ----

_INLINE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")


def _runs(paragraph, text):
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            paragraph.add_run(text[pos : m.start()])
        run = paragraph.add_run(m.group(1) or m.group(2))
        run.bold = m.group(1) is not None
        pos = m.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


def _songti(style):
    style.font.name = "宋体"
    fonts = style.element.rPr.rFonts
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        fonts.attrib.pop(qn(attr), None)
    fonts.set(qn("w:eastAsia"), "宋体")


def to_docx(markdown: str) -> bytes:
    """Headings, bullet lists, tables and paragraphs of engine.methods Markdown. 宋体 throughout, no fills."""
    doc = DocxDocument()
    _songti(doc.styles["Normal"])
    for level in (1, 2, 3):
        style = doc.styles[f"Heading {level}"]
        _songti(style)
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.font.size = Pt({1: 16, 2: 14, 3: 12}[level])
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            doc.add_heading(line[level:].strip(), level=min(level, 3))
        elif line.startswith("|"):
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in cells):
                    block.append(cells)
                i += 1
            table = doc.add_table(rows=len(block), cols=len(block[0]))
            table.style = "Table Grid"
            for r, cells in enumerate(block):
                for c, text in enumerate(cells):
                    cell = table.cell(r, c)
                    _runs(cell.paragraphs[0], text)
                    if r == 0:
                        for run in cell.paragraphs[0].runs:
                            run.bold = True
            continue
        elif line.lstrip().startswith("- "):
            nested = line.startswith("  ")
            p = doc.add_paragraph(style="List Bullet 2" if nested else "List Bullet")
            _runs(p, line.lstrip()[2:])
        else:
            _runs(doc.add_paragraph(), line)
        i += 1
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


@router.post("/projects/{project_id}/method-appendix")
def method_appendix(
    project_id: UUID,
    body: AppendixInput,
    user: CurrentUser,
    db: Db,
    format: Literal["json", "docx"] = "json",
):
    require_project(db, project_id, user)
    result = em.build(collect(db, project_id, body, user), body.style)
    if format == "json":
        return result
    name = f"方法附录-{datetime.now():%Y%m%d-%H%M}.docx"
    return Response(
        to_docx(result["markdown"]),
        media_type=DOCX_MIME,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )
