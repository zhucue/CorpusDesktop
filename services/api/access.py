"""Project-role checks and list paging shared by all routers."""

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import func, select

from services.api.errors import forbidden, not_found
from services.api.models import Corpus, ProjectMember, Subcorpus

READ = ("owner", "editor", "annotator", "viewer")
WRITE = ("owner", "editor")
MANAGE = ("owner",)


def project_role(db, project_id, user):
    return db.scalar(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user.id
        )
    )


def require_project(db, project_id, user, roles=READ):
    """Non-members get 404 so project ids do not leak."""
    role = project_role(db, project_id, user)
    if role is None:
        raise not_found("项目")
    if role not in roles:
        raise forbidden()
    return role


def load_corpus(db, corpus_id, user, write=False) -> Corpus:
    corpus = db.get(Corpus, corpus_id)
    if not corpus:
        raise not_found("语料库")
    if corpus.project_id is None:
        if write and not user.is_admin:
            raise forbidden()
    else:
        require_project(db, corpus.project_id, user, WRITE if write else READ)
    return corpus


def load_subcorpus(db, subcorpus_id, user, write=False) -> Subcorpus:
    sub = db.get(Subcorpus, subcorpus_id)
    if not sub:
        raise not_found("子库")
    require_project(db, sub.project_id, user, WRITE if write else READ)
    return sub


class Page:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        self.page, self.size = page, page_size

    def run(self, db, stmt, view):
        total = db.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )
        rows = db.execute(stmt.limit(self.size).offset((self.page - 1) * self.size))
        return {"items": [view(*r) for r in rows], "total": total}


Paging = Annotated[Page, Depends()]
