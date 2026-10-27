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
