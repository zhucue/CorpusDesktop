import os
from contextlib import contextmanager
from functools import cache
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def database_url():
    return os.environ["DATABASE_URL"]


def data_dir():
    return Path(os.environ.get("DATA_DIR", "data"))


@cache
def engine():
    return create_engine(database_url(), pool_pre_ping=True)


@cache
def _factory():
    return sessionmaker(engine(), expire_on_commit=False)


def session() -> Session:
    return _factory()()


@contextmanager
def transaction():
    with session() as s, s.begin():
        yield s


def get_db():
    with session() as s:
        yield s
