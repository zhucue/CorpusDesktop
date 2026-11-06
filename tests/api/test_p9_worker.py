"""P9 worker (contracts/p9.md): cancelling a running statistics job, model usage rows, daily maintenance and
the import language check (real parsers; NLP and CWB stay faked)."""

import itertools
import os
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text, update

from engine.parsers import parse as real_parse
from tests.api.conftest import drain, upload

IMP = Path(__file__).parents[1] / "fixtures" / "import"
TEXT = "Language is a system.\nThe language of science."


def _db():
    from services.api.db import transaction

    return transaction()


def _corpus(client, project, language="en", files=None):
    c = client.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "作文", "language": language},
    ).json()
    if files:
        upload(client, c["id"], files)
        drain()
    return c


# ---- cancel (§七) ----


def test_cancel_running_stats_frees_worker(owner, project, monkeypatch):
    """A statistics job inside one long engine call stops after a cancel; the worker takes the next job in 5 s."""
    from engine import stats
    from services.worker import main

    corpus = _corpus(owner, project, files={"a.txt": TEXT})
    monkeypatch.setattr(stats, "CHECK_EVERY", 5)
    started = threading.Event()

    def slow(*args, **kw):  # an engine loop over a huge scan
        started.set()
        for _ in stats._checked(itertools.count()):
            time.sleep(0.01)

    monkeypatch.setattr(stats, "frequency", slow)
    body = {"scope": {"corpus_id": corpus["id"]}, "unit": "word", "top": 2}
    first = owner.post("/api/stats/frequency", json=body).json()
    second = owner.post("/api/stats/frequency", json=body).json()

    worker = threading.Thread(target=main.run_once)
    worker.start()
    assert started.wait(10)
    r = owner.post(f"/api/jobs/{first['id']}/cancel")
    assert r.status_code == 200 and r.json()["state"] == "cancelled"
    t0 = time.monotonic()
    worker.join(10)
    assert not worker.is_alive()
    assert time.monotonic() - t0 < 5
    run = main.claim()
    assert run is not None and str(run.id) == second["id"]
    job = owner.get(f"/api/jobs/{first['id']}").json()
    assert job["state"] == "cancelled" and job["result"] is None
    assert owner.get(f"/api/projects/{project['id']}/stats").json()["total"] == 0


def test_run_check_and_poll(owner, project):
    from services.api.models import Job
    from services.worker import main

    corpus = _corpus(owner, project)
    upload(owner, corpus["id"], {"a.txt": TEXT})
    run = main.claim()
    run.check()  # running: nothing
    assert not run.poll()
    with _db() as db:
        db.execute(update(Job).where(Job.id == run.id).values(state="cancelled"))
    run.check()  # the flag is only set by poll / progress
    assert run.poll() and run.cancel.is_set()
    with pytest.raises(main.Cancelled):
        run.check()


# ---- model usage (§二) ----


@pytest.fixture
def usage_table():
    with _db() as db:
        if db.scalar(text("SELECT to_regclass('llm_usage')")) is None:
            pytest.skip("llm_usage table missing (migration 0010)")


def _usage_rows():
    with _db() as db:
        return [
            dict(r._mapping)
            for r in db.execute(
                text(
                    "SELECT user_id, project_id, job_id, source, model, prompt_tokens,"
                    " completion_tokens, total_tokens FROM llm_usage ORDER BY id"
                )
            )
        ]


def _model(monkeypatch, answers):
    from services.worker import llm

    monkeypatch.setenv("MODEL_BASE_URL", "http://model.test/v1")
    monkeypatch.setenv("MODEL_ID", "fake-chat")
    monkeypatch.delenv("MODEL_API", raising=False)
    answers = iter(answers)

    def post(url, json=None, headers=None, timeout=None):
        return SimpleNamespace(status_code=200, text="", json=lambda: next(answers))

    monkeypatch.setattr(llm.httpx, "post", post)
    return llm


def test_usage_rows_per_call(owner, project, monkeypatch, usage_table):
    llm = _model(
        monkeypatch,
        [
            {
                "choices": [{"message": {"content": "<think>x</think>摘要"}}],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "total_tokens": 150,
                },
            },
            {"choices": [{"message": {"content": "四个字符"}}]},  # no usage
            {"choices": [{"message": {"content": "对齐"}}], "usage": {}},
            {"choices": [{"message": {"content": "外部"}}]},
        ],
    )
    run = SimpleNamespace(
        id=uuid.uuid4(),
        kind="kb_summarize",
        owner_id=uuid.UUID(owner.user_id),
        project_id=uuid.UUID(project["id"]),
    )
    with llm.job(run):
        assert llm.chat("系统", "用户内容") == "摘要"
        assert llm.chat("ab", "cdef") == "四个字符"
        with llm.source("align"):
            llm.chat("s", "u")
    llm.chat("s", "u")
    rows = _usage_rows()
    common = {"user_id": run.owner_id, "project_id": run.project_id, "job_id": run.id}
    assert rows[0] == {
        **common,
        "source": "kb_summarize",
        "model": "fake-chat",
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "total_tokens": 150,
    }
    # characters / 2, rounded up: prompt "abcdef" 6 → 3, answer "四个字符" 4 → 2
    assert rows[1] == {
        **common,
        "source": "kb_summarize:estimated",
        "model": "fake-chat",
        "prompt_tokens": 3,
        "completion_tokens": 2,
        "total_tokens": 5,
    }
    assert rows[2]["source"] == "align:estimated" and rows[2]["job_id"] == run.id
    assert rows[3]["source"] == "other:estimated" and rows[3]["user_id"] is None


def test_usage_bound_by_execute(owner, project, monkeypatch, usage_table):
    """Jobs run by the worker record their kind, owner and project."""
    from services.api.jobs import enqueue
    from services.worker import main, tasks

    llm = _model(
        monkeypatch,
        [
            {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"input_tokens": 7, "output_tokens": 2, "total_tokens": 9},
            }
        ],
    )
    monkeypatch.setitem(
        tasks.HANDLERS, "kb_extract", lambda run: llm.chat("system", "user")
    )
    with _db() as db:
        job = enqueue(db, "kb_extract", {}, uuid.UUID(owner.user_id), project["id"])
        job_id = job.id
    main.run_once()
    [row] = _usage_rows()
    assert row["job_id"] == job_id and row["source"] == "kb_extract"
    assert (row["prompt_tokens"], row["completion_tokens"], row["total_tokens"]) == (
        7,
        2,
        9,
    )
    assert str(row["user_id"]) == owner.user_id
    assert str(row["project_id"]) == project["id"]


# ---- maintenance (§五) ----


def _backdate_job(job_id, **values):
    from services.api.models import Job

    with _db() as db:
        db.execute(update(Job).where(Job.id == job_id).values(**values))


def test_maintenance_purges_and_cleans(owner, project, make_user, monkeypatch):
    from services.api import projects
    from services.api.db import data_dir
    from services.api.jobs import enqueue
    from services.api.storage import corpus_dir, upload_dir
    from services.worker import maintenance

    if not hasattr(projects, "purge_project"):
        pytest.skip("services.api.projects.purge_project missing")
    old = datetime.now(UTC) - timedelta(days=31)
    # a project deleted 8 days ago, with a corpus on disk
    gone = owner.post("/api/projects", json={"name": "旧项目"}).json()
    gone_corpus = _corpus(owner, gone, files={"a.txt": TEXT})
    assert corpus_dir(gone_corpus["id"]).exists()
    with _db() as db:
        db.execute(
            text("UPDATE projects SET deleted_at = :at WHERE id = :id"),
            {"at": datetime.now(UTC) - timedelta(days=8), "id": gone["id"]},
        )
    # deleted 2 days ago: kept
    recent = owner.post("/api/projects", json={"name": "刚删除"}).json()
    with _db() as db:
        db.execute(
            text(
                "UPDATE projects SET deleted_at = now() - interval '2 days' WHERE id = :id"
            ),
            {"id": recent["id"]},
        )
    # exports: finished 31 days ago (removed) and today (kept)
    exports = data_dir() / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    user_id = uuid.UUID(owner.user_id)
    with _db() as db:
        old_export = enqueue(db, "export", {}, user_id, project["id"]).id
        new_export = enqueue(db, "export", {}, user_id, project["id"]).id
        imports = {}
        # upload folder → states and end times of the import jobs using it (a retry reuses the folder)
        cases = {
            "failed_retried": [("failed", old), ("failed", old)],  # removed
            "retry_queued": [("failed", old), ("queued", None)],  # kept: retry pending
            "retry_recent": [("cancelled", old), ("failed", datetime.now(UTC))],  # kept
            "fresh": [("cancelled", datetime.now(UTC))],  # kept
        }
        for name, states in cases.items():
            folder = upload_dir(uuid.uuid4())
            folder.mkdir(parents=True)
            (folder / "a.txt").write_text("x", encoding="utf-8")
            imports[name] = folder
            for state, at in states:
                job = enqueue(
                    db, "import", {"dir": str(folder)}, user_id, project["id"]
                )
                job.state, job.finished_at = state, at
    _backdate_job(old_export, state="succeeded", finished_at=old)
    _backdate_job(new_export, state="succeeded", finished_at=datetime.now(UTC))
    for jid in (old_export, new_export):
        (exports / f"{jid}.csv").write_text("x", encoding="utf-8")
    maintenance.last_run_path().unlink(missing_ok=True)

    assert maintenance.due()
    maintenance.run_if_due()

    with _db() as db:
        ids = {str(i) for i in db.scalars(text("SELECT id FROM projects"))}
        audit = db.execute(
            text(
                "SELECT actor_id, target_id, target_name FROM audit_logs"
                " WHERE action = 'project_purge'"
            )
        ).all()
    assert gone["id"] not in ids and recent["id"] in ids and project["id"] in ids
    assert [tuple(a) for a in audit] == [(None, gone["id"], "旧项目")]
    assert not corpus_dir(gone_corpus["id"]).exists()
    assert not (exports / f"{old_export}.csv").exists()
    assert (exports / f"{new_export}.csv").exists()
    assert {name: path.exists() for name, path in imports.items()} == {
        "failed_retried": False,
        "retry_queued": True,
        "retry_recent": True,
        "fresh": True,
    }
    assert not maintenance.due()  # last-run written
    path = maintenance.last_run_path()
    os.utime(path, (time.time() - 25 * 3600,) * 2)
    assert maintenance.due()


def test_maintenance_runs_on_worker_light(monkeypatch):
    from services.worker import main

    monkeypatch.delenv("WORKER_MAINTENANCE", raising=False)
    monkeypatch.setenv("WORKER_SMALL_IMPORTS", "1")
    assert main.maintenance_enabled()
    monkeypatch.setenv("WORKER_SMALL_IMPORTS", "0")
    assert not main.maintenance_enabled()
    monkeypatch.setenv("WORKER_MAINTENANCE", "1")
    assert main.maintenance_enabled()


# ---- languages (§九) ----


@pytest.fixture
def real_parsers(monkeypatch):
    from engine import parsers

    monkeypatch.setattr(parsers, "parse", real_parse)


def _import(client, project, name, data, language="auto"):
    c = client.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": name, "language": language},
    ).json()
    r = client.post(
        f"/api/corpora/{c['id']}/documents",
        files=[("files", (name, data, "application/octet-stream"))],
    )
    assert r.status_code == 200, r.text
    drain()
    return client.get(f"/api/jobs/{r.json()['id']}").json()


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [  # P10 (contracts/p10.md §八): fr / ja are supported; other languages still fail
        (
            "ko.txt",
            "한국어 말뭉치는 언어 연구에 널리 쓰인다. ".encode() * 20,
            "ko：文本的文字不属于支持的语言（zh、en、ja、fr、de、es、ru），请确认语言",
        ),
        (
            "en-ko.tmx",
            (IMP / "en-fr.tmx").read_bytes().replace(b'"fr-FR"', b'"ko-KR"'),
            "TMX 含暂不支持的语言：ko",
        ),
    ],
)
def test_import_rejects_other_languages(
    owner, project, real_parsers, name, data, message
):
    job = _import(owner, project, name, data)
    assert job["state"] == "failed"
    assert job["error"] == {"code": "LANGUAGE_UNSUPPORTED", "message": message}


def test_import_keeps_english_and_chinese(owner, project, real_parsers):
    en = _import(owner, project, "en.txt", (IMP / "en.txt").read_bytes())
    assert en["state"] == "succeeded", en
    zh = "社会语言学研究语言与社会的关系。\n语料库方法为翻译研究提供证据。"
    job = _import(owner, project, "zh.txt", zh.encode())
    assert job["state"] == "succeeded", job
    conllu = _import(
        owner, project, "mwt.conllu", (IMP / "mwt.conllu").read_bytes(), "es"
    )
    assert conllu["state"] == "succeeded", conllu  # CoNLL-U: stored as is, any language


def test_given_language_checked_at_start():
    from services.worker import tasks
    from services.worker.main import JobFailed

    with pytest.raises(JobFailed) as e:
        tasks._check_upload_language({"language": "ko", "files": ["a.txt"]})
    assert (e.value.code, e.value.message) == (
        "LANGUAGE_UNSUPPORTED",
        "暂不支持该语言：ko（支持 zh、en、ja、fr、de、es、ru）",
    )
    tasks._check_upload_language({"language": "ko", "files": ["a.conllu"]})
    tasks._check_upload_language({"language": "fr", "files": ["a.txt"]})
    tasks._check_upload_language({"language": "zh-Hans", "files": ["a.txt"]})
    tasks._check_upload_language({"language": None, "files": ["a.txt"]})


def test_index_leaves_out_documents_deleted_meanwhile(
    owner, project, fake_engine, monkeypatch
):
    """A document deleted while an index build runs is left out; the build succeeds and the corpus stays usable."""
    from engine import cwb
    from services.api.jobs import enqueue
    from services.api.models import Document
    from services.api.storage import corpus_key
    from services.worker import main, tasks

    corpus = _corpus(owner, project, files={"a.txt": TEXT, "b.txt": "Grammar rules."})
    with (
        _db() as db
    ):  # the order run_index reads them in; the second is read in the second load round
        order = [
            str(i)
            for i in db.scalars(
                select(Document.id)
                .where(Document.corpus_id == uuid.UUID(corpus["id"]))
                .order_by(Document.created_at, Document.id)
            )
        ]
    kept, gone = order
    with _db() as db:
        job = enqueue(
            db,
            "index",
            {"corpus_id": corpus["id"]},
            uuid.UUID(owner.user_id),
            project["id"],
        )
        job_id = job.id
    build = fake_engine.build

    def build_after_delete(index_dir, key, documents, doc_ids):
        with _db() as db:  # deleted after the job listed the documents
            db.execute(
                Document.__table__.delete().where(Document.id == uuid.UUID(gone))
            )
        return build(index_dir, key, documents, doc_ids)

    monkeypatch.setattr(cwb, "build", build_after_delete)
    monkeypatch.setattr(tasks, "LOAD_BATCH", 1)  # b is read in a later load round
    main.run_once()
    job = owner.get(f"/api/jobs/{job_id}").json()
    assert job["state"] == "succeeded", job
    c = owner.get(f"/api/corpora/{corpus['id']}").json()
    assert c["status"] == "ready" and not c.get("error")
    indexed = dict(fake_engine.indexes[corpus_key(corpus["id"])])
    assert list(indexed) == [kept]
