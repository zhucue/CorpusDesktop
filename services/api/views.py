from uuid import UUID

from sqlalchemy.orm import object_session


def user_view(u):
    return {
        "id": u.id,
        "email": u.email,
        "display_name": u.display_name,
        "is_admin": u.is_admin,
    }


def project_view(p, role):
    return {"id": p.id, "name": p.name, "role": role, "created_at": p.created_at}


def corpus_view(c):
    return {
        "id": c.id,
        "project_id": c.project_id,
        "name": c.name,
        "language": c.language,
        "description": c.description,
        "parallel": c.parallel,
        "status": c.status,
        "error": c.error,
        "stats": c.stats,
        "index_version": c.index_version,
        "meta": c.meta or {},
        "created_at": c.created_at,
    }


def document_view(d):
    return {
        "id": d.id,
        "corpus_id": d.corpus_id,
        "title": d.title,
        "language": d.language,
        "metadata": d.meta,
        "sentences": d.sentence_count,
        "tokens": d.token_count,
        "created_at": d.created_at,
    }


METHOD_NAMES = {
    "frequency": "频次",
    "ngrams": "N 元组",
    "collocations": "搭配",
    "keywords": "关键词",
    "distribution": "分布",
}
EXPORT_SOURCES = {"evidence": "证据篮", "kb_terms": "术语表"}


def _name(db, model, oid, attr="name"):
    obj = db.get(model, UUID(str(oid))) if oid else None
    return getattr(obj, attr) if obj else "已删除"


def _scope_name(db, scope):
    from services.api.models import Corpus, Subcorpus

    scope = scope or {}
    if scope.get("subcorpus_id"):
        return _name(db, Subcorpus, scope["subcorpus_id"])
    name = _name(db, Corpus, scope.get("corpus_id"))
    return f"{name}（筛选）" if scope.get("filter") else name


def _stat_summary(db, p):
    method = METHOD_NAMES.get(p.get("method"), p.get("method") or "")
    if p.get("method") == "keywords":
        target = _scope_name(db, p.get("target"))
        return f"{method} · {target} 对 {_scope_name(db, p.get('reference'))}"
    return f"{method} · {_scope_name(db, p.get('scope'))}"


def job_summary(db, j) -> str:
    """Short text naming what a job works on: corpus and files, stat method and scope, layer, document."""
    from services.api.models import AnnotationLayer, Corpus, KbDocument, StatResult

    p = j.params or {}
    if j.kind == "import":
        files = p.get("files") or []
        names = "、".join(files[:3])
        if len(files) > 3:
            names += f" 等 {len(files)} 个文件"
        return f"{_name(db, Corpus, p.get('corpus_id'))}：{names}"
    if j.kind == "index":
        return _name(db, Corpus, p.get("corpus_id"))
    if j.kind == "stats":
        return _stat_summary(db, p)
    if j.kind == "preannotate":
        return _name(db, AnnotationLayer, p.get("layer_id"))
    if j.kind in ("kb_import", "kb_summarize"):
        return _name(db, KbDocument, p.get("document_id"), "title")
    if j.kind == "kb_extract":
        if p.get("source") == "corpus":
            return f"术语抽取 · {_scope_name(db, p.get('scope'))}"
        return f"术语抽取 · {len(p.get('document_ids') or [])} 篇文献"
    if j.kind == "export":
        source = p.get("source", "search")
        if source == "search":
            what = f"检索 {p.get('query', '')} · {_scope_name(db, p.get('scope'))}"
        elif source == "stats":
            stat = db.get(StatResult, UUID(p["stat_id"])) if p.get("stat_id") else None
            what = (
                f"{METHOD_NAMES.get(stat.method, stat.method)} · {(stat.scope or {}).get('name', '')}"
                if stat
                else "统计 · 已删除"
            )
        elif source == "layer":
            what = _name(db, AnnotationLayer, p.get("layer_id"))
        elif source == "kb_note":
            what = _name(db, KbDocument, p.get("document_id"), "title")
        else:
            what = EXPORT_SOURCES.get(source, source)
        return f"{what} · {str(p.get('format', '')).upper()}"
    return j.kind


def job_view(j):
    from services.api.models import User

    db = object_session(j)
    owner = db.get(User, j.owner_id) if db else None
    return {
        "id": j.id,
        "project_id": j.project_id,
        "owner_id": j.owner_id,
        "owner_email": owner.email if owner else None,
        "summary": job_summary(db, j) if db else j.kind,
        "kind": j.kind,
        "state": j.state,
        "progress": j.progress,
        "result": j.result,
        "error": j.error,
        "created_at": j.created_at,
        "finished_at": j.finished_at,
    }


def saved_query_view(q):
    return {
        "id": q.id,
        "project_id": q.project_id,
        "name": q.name,
        "query": q.query,
        "scope": q.scope,
        "created_at": q.created_at,
    }


def stat_view(s, rows=None):
    view = {
        "id": s.id,
        "project_id": s.project_id,
        "method": s.method,
        "params": s.params,
        "scope": s.scope,
        "index_version": s.index_version,
        "totals": s.totals,
        "created_at": s.created_at,
        "columns": s.columns,
        "row_count": s.row_count,
    }
    if rows is not None:
        view["rows"] = rows
    return view


def evidence_view(e):
    return {
        "id": e.id,
        "project_id": e.project_id,
        "kind": e.kind,
        "ref": e.ref,
        "text": e.text,
        "source": e.source,
        "note": e.note,
        "created_by": e.created_by,
        "created_at": e.created_at,
    }


def kb_document_view(d, **extra):
    return {
        "id": d.id,
        "project_id": d.project_id,
        "kind": d.kind,
        "title": d.title,
        "source": d.source,
        "meta": d.meta,
        "status": d.status,
        "error": d.error,
        "chunk_count": d.chunk_count,
        "created_by": d.created_by,
        "created_at": d.created_at,
        "updated_at": d.updated_at,
        **extra,
    }


def chunk_view(c, score=None):
    view = {
        "id": c.id,
        "document_id": c.document_id,
        "ordinal": c.ordinal,
        "text": c.text,
        "locator": c.locator,
    }
    if score is not None:
        view["score"] = score
    return view


def term_view(t):
    return {
        "id": t.id,
        "project_id": t.project_id,
        "term": t.term,
        "language": t.language,
        "translations": t.translations,
        "definition": t.definition,
        "domain": t.domain,
        "examples": t.examples,
        "source": t.source,
        "status": t.status,
        "created_by": t.created_by,
        "confirmed_by": t.confirmed_by,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def note_ref_view(r):
    return {
        "id": r.id,
        "note_id": r.note_id,
        "kind": r.kind,
        "ref": r.ref,
        "created_at": r.created_at,
    }
