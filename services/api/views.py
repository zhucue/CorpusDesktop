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


def job_view(j):
    return {
        "id": j.id,
        "project_id": j.project_id,
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
