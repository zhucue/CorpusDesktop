"""PostgreSQL transactions with authenticated, transaction-local RLS identity."""

import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from uuid import UUID

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    metadata = MetaData(schema="app")


_bound_transaction = ContextVar("corpus_bound_transaction", default=None)


@contextmanager
def bound_transaction(actor_id, session):
    """Reuse one fenced business transaction only within the current context."""
    actor = UUID(str(actor_id))
    if _bound_transaction.get() is not None or not session.in_transaction():
        raise RuntimeError("A live, unbound transaction is required")
    actual = session.scalar(text("SELECT current_setting('app.actor_id',true)"))
    if actual != str(actor):
        raise RuntimeError("Bound transaction database identity mismatch")
    marker = _bound_transaction.set((actor, session))
    try:
        yield
    finally:
        _bound_transaction.reset(marker)


@lru_cache(maxsize=4)
def _engine(url):
    return create_engine(
        url, pool_pre_ping=True, pool_size=5, max_overflow=5, hide_parameters=True
    )


def engine():
    url = os.environ["DATABASE_URL"]
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("PostgreSQL psycopg DATABASE_URL is required")
    return _engine(url)


def validate_runtime_role(session):
    unsafe = session.scalar(
        text("""
        SELECT r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb
          OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                     WHERE n.nspname='app' AND pg_has_role(current_user,c.relowner,'MEMBER'))
          OR pg_has_role(current_user, 'corpus_owner', 'MEMBER')
        FROM pg_roles r WHERE r.rolname=current_user
    """)
    )
    if unsafe is not False:
        raise RuntimeError(
            "Runtime database identity must be non-owner and unprivileged"
        )


@contextmanager
def transaction(actor_id: UUID | None = None):
    bound = _bound_transaction.get()
    if bound is not None:
        if actor_id is None or UUID(str(actor_id)) != bound[0]:
            raise RuntimeError("Bound transaction actor mismatch")
        yield bound[1]
        return
    with Session(engine(), expire_on_commit=False) as session, session.begin():
        validate_runtime_role(session)
        actor = str(UUID(str(actor_id))) if actor_id is not None else ""
        session.execute(
            text("SELECT set_config('app.actor_id', :actor, true)"), {"actor": actor}
        )
        yield session


def lock_actor(session, actor_id):
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": "actor:" + str(actor_id)},
    )


def lock_project(session, project_id):
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": "project:" + str(project_id)},
    )
