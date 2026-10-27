"""API tests run against a real PostgreSQL (TEST_DATABASE_URL); engine parsing, NLP and CWB are faked.

Local: docker compose -f deploy/compose.yaml --env-file deploy/.env up -d postgres
       TEST_DATABASE_URL=postgresql+psycopg://corpus:<password>@127.0.0.1:15432/corpus_test uv run pytest tests/api
Docker: docker compose -f deploy/compose.yaml run --rm test
"""

import importlib
import os
import re
import sys
import types
from pathlib import Path

import pytest

TEST_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_URL:
    collect_ignore_glob = ["test_*.py"]
else:
    os.environ["DATABASE_URL"] = TEST_URL
    os.environ["PUBLIC_ORIGIN"] = "http://testserver"

import engine

# engine modules still under construction must not block API tests; every function used is faked below.
for _name in ("cwb", "nlp", "parsers", "query"):
    try:
        importlib.import_module(f"engine.{_name}")
    except ImportError:
        _mod = types.ModuleType(f"engine.{_name}")
        sys.modules[f"engine.{_name}"] = _mod
        setattr(engine, _name, _mod)

from engine import cwb, nlp, parsers
from engine import model as em

ORIGIN = "http://testserver"
PASSWORD = "correct horse battery"


@pytest.fixture(scope="session")
def database(tmp_path_factory):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    url = make_url(TEST_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if not conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
        ):
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    eng.dispose()
    command.upgrade(Config("services/api/alembic.ini"), "head")
    os.environ["DATA_DIR"] = str(tmp_path_factory.mktemp("data"))
    return TEST_URL


@pytest.fixture(autouse=True)
def clean(database):
    from sqlalchemy import text

    from services.api.db import engine as db_engine
    from services.api.db import transaction
    from services.api.label_sets import seed_builtin
    from services.api.search import searches

    with db_engine().begin() as conn:
        conn.execute(
            text(
                "TRUNCATE users, login_sessions, projects, project_members, corpora, documents,"
                " sentences, tokens, sentence_alignments, subcorpora, saved_queries, jobs,"
                " stat_results, evidence, agent_sessions, agent_messages, agent_tokens,"
                " label_sets, annotation_layers, annotations, kb_documents, kb_chunks, kb_terms,"
                " note_refs CASCADE"
            )
        )
    with transaction() as db:
        seed_builtin(db)
    searches.entries.clear()


# ---- fake engine ----


class FakeEngine:
    def __init__(self):
        self.indexes = {}
        self.calls = []
        self.needle = "language"
        self.complete = True

    def parse(self, path, *, language, metadata):
        path = Path(path)
        content = path.read_text(encoding="utf-8")
        if content.startswith("FAIL"):
            raise parsers.ParseError(f"{path.name} 无法解析")
        if path.suffix == ".tmx":  # fake parallel format: "en\tzh" per line
            en_lines, zh_lines, alignments = [], [], []
            for i, line in enumerate(content.strip().splitlines()):
                en, zh = line.split("\t")
                en_lines.append((en, f"en{i}"))
                zh_lines.append((zh, f"zh{i}"))
                alignments.append(em.Alignment(f"en{i}", f"zh{i}"))
            docs = [
                self._doc(path.stem + "-en", "en", en_lines, metadata),
                self._doc(path.stem + "-zh", "zh", zh_lines, metadata),
            ]
            return docs, alignments
        return [
            em.Document(path.stem, language, content.strip(), dict(metadata), [])
        ], []

    @staticmethod
    def _doc(title, language, lines, metadata):
        text, sentences = "", []
        for line, ext in lines:
            start = len(text)
            text += line + "\n"
            sentences.append(em.Sentence(start, start + len(line), [], ext))
        return em.Document(title, language, text, dict(metadata), sentences)

    def annotate(self, doc):
        if not doc.sentences:
            for m in re.finditer(r"[^\n]+", doc.text):
                doc.sentences.append(em.Sentence(m.start(), m.end(), []))
        for s in doc.sentences:
            if not s.tokens:
                for m in re.finditer(r"\S+", doc.text[s.start : s.end]):
                    s.tokens.append(
                        em.Token(s.start + m.start(), s.start + m.end(), m.group())
                    )

    def build(self, index_dir, corpus_key, documents, doc_ids):
        docs = list(zip(doc_ids, documents))
        self.indexes[corpus_key] = docs
        n = len(self.indexes)
        return em.IndexInfo(
            tokens=sum(len(s.tokens) for _, d in docs for s in d.sentences),
            sentences=sum(len(d.sentences) for _, d in docs),
            documents=len(docs),
            index_version=f"v{n}",
        )

    def search(
        self,
        index_dir,
        corpus_key,
        cqp,
        *,
        restrict,
        sort,
        seed,
        page,
        page_size,
        context,
        count_timeout=20,
        attr_filter=None,
    ):
        """Hits = occurrences of self.needle; with attr_filter, the token holding the hit start is
        checked as anchor slot 0 (as cwb.search does with `#target 0`)."""
        self.calls.append(
            {
                "cqp": cqp,
                "restrict": restrict,
                "sort": sort,
                "seed": seed,
                "page": page,
                "page_size": page_size,
                "context": context,
            }
        )
        hits = []
        for doc_id, d in self.indexes.get(corpus_key, []):
            for n, s in enumerate(d.sentences):
                for m in re.finditer(
                    re.escape(self.needle), d.text[s.start : s.end], re.IGNORECASE
                ):
                    start, end = s.start + m.start(), s.start + m.end()
                    hits.append(
                        em.Hit(
                            f"{doc_id}:{start}-{end}",
                            doc_id,
                            n,
                            start,
                            end,
                            d.text[max(0, start - 10) : start],
                            m.group(),
                            d.text[end : end + 10],
                        )
                    )
        if attr_filter:
            docs = dict(self.indexes.get(corpus_key, []))

            def key(h):
                toks = docs[h.doc_id].sentences[h.sentence_index].tokens
                j = next(j for j, t in enumerate(toks) if t.start <= h.start_cp < t.end)
                return (h.doc_id, h.sentence_index, j)

            allowed = attr_filter(0, {key(h) for h in hits})
            hits = [h for h in hits if key(h) in allowed]
        counts = em.Counts(
            hits=len(hits) if self.complete else None,
            sentences=len({(h.doc_id, h.sentence_index) for h in hits})
            if self.complete
            else None,
            documents=len({h.doc_id for h in hits}) if self.complete else None,
            complete=self.complete,
        )
        items = hits[(page - 1) * page_size : page * page_size]
        return em.SearchResult(counts, items, page, page_size)


@pytest.fixture(autouse=True)
def fake_engine(monkeypatch):
    fake = FakeEngine()
    if not hasattr(parsers, "ParseError"):
        monkeypatch.setattr(
            parsers, "ParseError", type("ParseError", (ValueError,), {}), raising=False
        )
    monkeypatch.setattr(parsers, "parse", fake.parse, raising=False)
    monkeypatch.setattr(nlp, "annotate", fake.annotate, raising=False)
    monkeypatch.setattr(cwb, "build", fake.build, raising=False)
    monkeypatch.setattr(cwb, "search", fake.search, raising=False)
    return fake


# ---- users and clients ----


@pytest.fixture
def make_user():
    from fastapi.testclient import TestClient

    from services.api.auth import HASHER
    from services.api.db import transaction
    from services.api.main import app
    from services.api.models import User

    def make(email, admin=False, login=True):
        with transaction() as db:
            user = User(
                email=email,
                display_name=email.split("@")[0],
                password_hash=HASHER.hash(PASSWORD),
                is_admin=admin,
            )
            db.add(user)
        client = TestClient(app, headers={"Origin": ORIGIN})
        client.user_id = str(user.id)
        if login:
            r = client.post(
                "/api/auth/login", json={"email": email, "password": PASSWORD}
            )
            assert r.status_code == 200, r.text
        return client

    return make


@pytest.fixture
def owner(make_user):
    return make_user("owner@example.edu")


@pytest.fixture
def project(owner):
    return owner.post("/api/projects", json={"name": "毕业论文"}).json()


@pytest.fixture
def member(make_user, owner, project):
    """member(role) → logged-in client holding that role in `project`."""

    def make(role):
        client = make_user(f"{role}@example.edu")
        r = owner.put(
            f"/api/projects/{project['id']}/members/{client.user_id}",
            json={"role": role},
        )
        assert r.status_code == 200, r.text
        return client

    return make


def drain():
    """Run queued jobs in-process until the queue is empty."""
    from services.worker.main import run_once

    for _ in range(50):
        if not run_once():
            return
    raise AssertionError("job queue did not drain")


def upload(client, corpus_id, files, **form):
    """files: {name: text}"""
    return client.post(
        f"/api/corpora/{corpus_id}/documents",
        files=[
            ("files", (name, body.encode(), "text/plain"))
            for name, body in files.items()
        ],
        data=form,
    )
