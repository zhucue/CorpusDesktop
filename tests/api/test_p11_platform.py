"""P11 platform (contracts/p11.md §三): account lookup for adding members, model request retries, batched job
list, upload source / license fields, help metrics."""

import json
import uuid

import httpx
import pytest
from sqlalchemy import event, text

from tests.api.conftest import ORIGIN, drain, upload


def _db():
    from services.api.db import transaction

    return transaction()


# ---- GET /users?email= (§三 4) ----


def test_user_lookup_owner_only_exact_and_same_shape(owner, project, member, make_user):
    other = make_user("other@example.edu")
    pid = project["id"]
    r = owner.get(
        "/api/users", params={"email": " OTHER@example.edu ", "project_id": pid}
    )
    assert r.status_code == 200
    assert r.json() == {
        "items": [
            {"id": other.user_id, "email": "other@example.edu", "display_name": "other"}
        ]
    }
    # no partial matches; a missing account answers with the same shape
    for email in ("other@example", "ther@example.edu", "none@example.edu"):
        r = owner.get("/api/users", params={"email": email, "project_id": pid})
        assert (r.status_code, r.json()) == (200, {"items": []})
    # editors and other members: 403; not a member: 404; no project: 422
    editor = member("editor")
    assert (
        editor.get(
            "/api/users", params={"email": "x@y.z", "project_id": pid}
        ).status_code
        == 403
    )
    assert (
        other.get(
            "/api/users", params={"email": "x@y.z", "project_id": pid}
        ).status_code
        == 404
    )
    assert owner.get("/api/users", params={"email": "x@y.z"}).status_code == 422


def test_user_lookup_rate_limited_per_user(owner, project, make_user):
    from services.api import auth

    pid = project["id"]
    for _ in range(auth.LOOKUPS_PER_MINUTE):
        assert (
            owner.get(
                "/api/users", params={"email": "a@b.cd", "project_id": pid}
            ).status_code
            == 200
        )
    r = owner.get("/api/users", params={"email": "a@b.cd", "project_id": pid})
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"
    # another owner is not affected
    second = make_user("second@example.edu")
    p2 = second.post("/api/projects", json={"name": "另一个"}).json()["id"]
    assert (
        second.get(
            "/api/users", params={"email": "a@b.cd", "project_id": p2}
        ).status_code
        == 200
    )


def test_user_lookup_refuses_agent_tokens(owner, project):
    from fastapi.testclient import TestClient

    from services.api.main import app

    token = owner.post(
        "/api/auth/agent-token", json={"project_id": project["id"]}
    ).json()["token"]
    bot = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    r = bot.get("/api/users", params={"email": "a@b.cd", "project_id": project["id"]})
    assert r.status_code == 403


# ---- model retries (§三 6) ----


class _Response:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.text = json.dumps(body) if body is not None else "error"

    def json(self):
        return self._body


def _fake_model(monkeypatch, replies):
    from services.worker import llm

    monkeypatch.setenv("MODEL_BASE_URL", "http://model.test/v1")
    monkeypatch.setenv("MODEL_ID", "fake-chat")
    monkeypatch.delenv("MODEL_API", raising=False)
    calls, sleeps = [], []
    replies = iter(replies)

    def post(url, json=None, headers=None, timeout=None):
        calls.append(url)
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(llm.httpx, "post", post)
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)
    return llm, calls, sleeps


ANSWER = {
    "choices": [{"message": {"content": "好"}}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
}


def _usage_count():
    with _db() as db:
        return db.execute(text("SELECT count(*) FROM llm_usage")).scalar()


def test_model_503_twice_then_success(monkeypatch):
    llm, calls, sleeps = _fake_model(
        monkeypatch, [_Response(503), _Response(503), _Response(200, ANSWER)]
    )
    assert llm.chat("s", "u") == "好"
    assert len(calls) == 3 and sleeps == [2, 6]
    assert _usage_count() == 1  # recorded once, for the call that answered


def test_model_retry_after_and_connection_errors(monkeypatch):
    llm, _, sleeps = _fake_model(
        monkeypatch,
        [
            _Response(429, headers={"retry-after": "4"}),
            httpx.ConnectError("refused"),
            _Response(200, ANSWER),
        ],
    )
    assert llm.chat("s", "u") == "好"
    assert sleeps == [4.0, 6]


def test_model_gives_up_after_two_retries_with_the_actual_error(monkeypatch):
    from services.worker.main import JobFailed

    llm, calls, sleeps = _fake_model(
        monkeypatch, [_Response(502), _Response(503), _Response(500)]
    )
    with pytest.raises(JobFailed) as e:
        llm.chat("s", "u")
    assert len(calls) == 3 and sleeps == [2, 6]
    assert e.value.code == "MODEL_ERROR" and "HTTP 500" in e.value.message
    assert _usage_count() == 0
    # 4xx other than 429 is not retried
    llm, calls, sleeps = _fake_model(monkeypatch, [_Response(400)])
    with pytest.raises(JobFailed):
        llm.chat("s", "u")
    assert len(calls) == 1 and sleeps == []


# ---- job list without N+1 (§三 7) ----


def _count_queries(fn):
    from services.api.db import engine

    seen = []

    def before(conn, cursor, statement, *args):
        seen.append(statement)

    eng = engine()
    event.listen(eng, "before_cursor_execute", before)
    try:
        result = fn()
    finally:
        event.remove(eng, "before_cursor_execute", before)
    return result, len(seen)


def _jobs(owner, project, corpus_id, n):
    from services.api.jobs import enqueue

    uid = uuid.UUID(owner.user_id)
    with _db() as db:
        for i in range(n):
            kind, params = [
                ("import", {"corpus_id": corpus_id, "files": [f"{i}.txt"]}),
                ("index", {"corpus_id": corpus_id}),
                ("stats", {"method": "frequency", "scope": {"corpus_id": corpus_id}}),
                (
                    "export",
                    {
                        "source": "search",
                        "query": "x",
                        "scope": {"corpus_id": corpus_id},
                        "format": "csv",
                    },
                ),
            ][i % 4]
            enqueue(db, kind, params, uid, project["id"])


def test_job_list_query_count_does_not_grow_with_the_page(owner, project, make_user):
    corpus = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "作文", "language": "en"},
    ).json()
    url = f"/api/projects/{project['id']}/jobs"
    _jobs(owner, project, corpus["id"], 4)
    _, n_small = _count_queries(lambda: owner.get(url, params={"page_size": 50}).json())
    _jobs(owner, project, corpus["id"], 36)
    big, n_big = _count_queries(lambda: owner.get(url, params={"page_size": 50}).json())
    assert big["total"] == 40 and len(big["items"]) == 40
    assert n_big == n_small
    # the batched values match the single-job view
    for item in big["items"][:8]:
        one = owner.get(f"/api/jobs/{item['id']}").json()
        assert {k: item[k] for k in ("summary", "owner_email", "queue_ahead")} == {
            k: one[k] for k in ("summary", "owner_email", "queue_ahead")
        }
    assert {i["summary"] for i in big["items"]} >= {
        "作文",
        "作文：0.txt",
        "频次 · 作文",
    }


# ---- upload source and license (§三 5) ----


def test_upload_sets_corpus_source_and_exports_use_it(owner, project):
    from services.worker.tasks import source_notice

    corpus = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "作文", "language": "en"},
    ).json()
    source = {
        "license": "CC BY 4.0",
        "attribution": "某某大学",
        "source_url": "https://example.edu/c",
    }
    r = upload(
        owner,
        corpus["id"],
        {"a.txt": "Language is a system."},
        source=json.dumps(source),
    )
    assert r.status_code == 200, r.text
    drain()
    meta = owner.get(f"/api/corpora/{corpus['id']}").json()["meta"]
    assert {k: meta.get(k) for k in source} == source
    with _db() as db:
        assert source_notice(db, [corpus["id"]]) == [
            "来源：作文；许可：CC BY 4.0；署名：某某大学；链接：https://example.edu/c"
        ]
    # an empty field removes it, a missing field stays
    r = upload(
        owner,
        corpus["id"],
        {"b.txt": "Another text."},
        source=json.dumps({"source_url": ""}),
    )
    assert r.status_code == 200
    meta = owner.get(f"/api/corpora/{corpus['id']}").json()["meta"]
    assert "source_url" not in meta and meta["license"] == "CC BY 4.0"
    bad = upload(
        owner, corpus["id"], {"c.txt": "x"}, source=json.dumps({"license": "x" * 201})
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_SOURCE"


# ---- help metrics (§三 1) ----


def test_help_metrics_from_the_method_table(owner, make_user):
    from fastapi.testclient import TestClient

    from engine import methods
    from services.api.main import app

    assert (
        TestClient(app, headers={"Origin": ORIGIN}).get("/api/help/metrics").status_code
        == 401
    )
    data = owner.get("/api/help/metrics").json()
    assert [m["key"] for m in data["items"]] == list(methods.METRICS)
    dp = next(m for m in data["items"] if m["key"] == "dp")
    assert dp["formula"] == methods.METRICS["dp"][1]
    assert dp["references"] == [
        {
            "key": "gries2008",
            "label": methods.REFERENCES["gries2008"][1],
            "text": methods.reference("gries2008", "gbt7714"),
        }
    ]
    apa = owner.get("/api/help/metrics", params={"style": "apa"}).json()
    assert next(m for m in apa["items"] if m["key"] == "dp")["references"][0][
        "text"
    ] == methods.reference("gries2008", "apa")
    assert owner.get("/api/help/metrics", params={"style": "mla"}).status_code == 422


def test_model_read_timeout_is_not_retried(monkeypatch):
    from services.worker.main import JobFailed

    llm, calls, sleeps = _fake_model(monkeypatch, [httpx.ReadTimeout("slow")])
    with pytest.raises(JobFailed, match="秒内没有响应"):
        llm.chat("s", "u")
    assert len(calls) == 1 and sleeps == []


def test_model_retry_wait_stops_when_the_job_is_cancelled(monkeypatch):
    import threading
    import time
    from types import SimpleNamespace

    from services.worker.main import Cancelled

    llm, calls, _ = _fake_model(
        monkeypatch,
        [_Response(429, headers={"retry-after": "60"}), _Response(200, ANSWER)],
    )
    polls = []
    run = SimpleNamespace(
        id=uuid.uuid4(),
        kind="kb_summarize",
        owner_id=None,
        project_id=None,
        cancel=threading.Event(),
    )
    run.poll = lambda: (
        polls.append(1) or len(polls) >= 2
    )  # cancelled seen on the second check
    started = time.monotonic()
    with llm.job(run), pytest.raises(Cancelled):
        llm.chat("s", "u")
    assert len(calls) == 1 and 1 <= time.monotonic() - started < 5
