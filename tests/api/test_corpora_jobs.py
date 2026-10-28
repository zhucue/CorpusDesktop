import json

import pytest

from tests.api.conftest import drain, upload

TEXT_A = "Language is a system.\nThe language of science."
TEXT_B = "Grammar rules apply.\nNo match here."


@pytest.fixture
def corpus(owner, project):
    r = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "作文", "language": "en"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_import_index_ready(owner, project, corpus):
    r = upload(
        owner,
        corpus["id"],
        {"a.txt": TEXT_A},
        metadata=json.dumps({"year": 2001, "genre": "news"}),
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["kind"] == "import" and job["state"] == "queued"
    assert owner.get(f"/api/corpora/{corpus['id']}").json()["status"] == "importing"

    upload(
        owner,
        corpus["id"],
        {"b.txt": TEXT_B},
        metadata=json.dumps({"year": 2010, "genre": "fiction"}),
    )
    drain()

    c = owner.get(f"/api/corpora/{corpus['id']}").json()
    assert c["status"] == "ready", c
    assert c["stats"] == {"documents": 2, "sentences": 4, "tokens": 14}
    assert c["index_version"]

    jobs = owner.get(f"/api/projects/{project['id']}/jobs").json()
    kinds = sorted((j["kind"], j["state"]) for j in jobs["items"])
    # the second import found an index job already queued and did not add another
    assert kinds == [
        ("import", "succeeded"),
        ("import", "succeeded"),
        ("index", "succeeded"),
    ]
    first = owner.get(f"/api/jobs/{job['id']}").json()
    assert first["result"] == {
        "documents": 1,
        "sentences": 2,
        "tokens": 8,
        "alignments": 0,
    }
    assert first["finished_at"]

    docs = owner.get(f"/api/corpora/{corpus['id']}/documents").json()
    assert docs["total"] == 2
    a = next(d for d in docs["items"] if d["title"] == "a")
    assert (
        a["metadata"] == {"year": 2001, "genre": "news"}
        and a["sentences"] == 2
        and a["tokens"] == 8
    )
    assert (
        owner.get(f"/api/corpora/{corpus['id']}/documents", params={"q": "B"}).json()[
            "total"
        ]
        == 1
    )

    fields = owner.get(f"/api/corpora/{corpus['id']}/metadata-fields").json()
    assert fields == [
        {"field": "genre", "type": "string", "values": ["fiction", "news"]},
        {"field": "year", "type": "number", "values": [2001, 2010]},
    ]

    r = owner.patch(
        f"/api/corpora/{corpus['id']}/documents/{a['id']}",
        json={"title": "A 篇", "metadata": {"year": 2002}},
    )
    assert r.json()["title"] == "A 篇" and r.json()["metadata"] == {"year": 2002}
    assert owner.get(f"/api/corpora/{corpus['id']}").json()["status"] == "stale"

    assert owner.post(f"/api/corpora/{corpus['id']}/reindex").json()["kind"] == "index"
    assert owner.post(f"/api/corpora/{corpus['id']}/reindex").status_code == 409
    drain()
    assert owner.get(f"/api/corpora/{corpus['id']}").json()["status"] == "ready"

    assert (
        owner.delete(f"/api/corpora/{corpus['id']}/documents/{a['id']}").status_code
        == 204
    )
    assert owner.get(f"/api/corpora/{corpus['id']}").json()["status"] == "stale"
    assert owner.get(f"/api/corpora/{corpus['id']}/documents").json()["total"] == 1

    assert owner.delete(f"/api/corpora/{corpus['id']}").status_code == 204
    assert owner.get(f"/api/corpora/{corpus['id']}").status_code == 404


def test_upload_validation(owner, corpus, member):
    assert (
        upload(owner, corpus["id"], {"a.pdf": "x"}).json()["error"]["code"]
        == "UNSUPPORTED_FORMAT"
    )
    assert (
        upload(owner, corpus["id"], {"a.txt": "x"}, metadata="[1]").status_code == 422
    )
    assert upload(member("viewer"), corpus["id"], {"a.txt": "x"}).status_code == 403
    editor = member("editor")
    assert upload(editor, corpus["id"], {"a.txt": TEXT_A}).status_code == 200


def test_failed_import_and_retry(owner, corpus):
    job = upload(owner, corpus["id"], {"bad.txt": "FAIL here"}).json()
    drain()
    failed = owner.get(f"/api/jobs/{job['id']}").json()
    assert failed["state"] == "failed"
    assert failed["error"] == {"code": "PARSE_ERROR", "message": "bad.txt 无法解析"}
    c = owner.get(f"/api/corpora/{corpus['id']}").json()
    assert c["status"] == "failed" and c["error"] == "bad.txt 无法解析"

    retry = owner.post(f"/api/jobs/{job['id']}/retry").json()
    assert (
        retry["id"] != job["id"]
        and retry["state"] == "queued"
        and retry["kind"] == "import"
    )
    assert owner.get(f"/api/corpora/{corpus['id']}").json()["status"] == "importing"
    assert (
        owner.post(f"/api/jobs/{job['id']}/retry").status_code == 409
    )  # same batch already queued
    assert (
        owner.post(f"/api/jobs/{retry['id']}/retry").status_code == 409
    )  # not failed yet


def test_cancel_queued_and_finished(owner, corpus, member):
    job = upload(owner, corpus["id"], {"a.txt": TEXT_A}).json()
    assert member("viewer").post(f"/api/jobs/{job['id']}/cancel").status_code == 403
    r = owner.post(f"/api/jobs/{job['id']}/cancel").json()
    assert r["state"] == "cancelled" and r["finished_at"]
    assert owner.get(f"/api/corpora/{corpus['id']}").json()["status"] == "empty"
    drain()
    assert owner.get(f"/api/corpora/{corpus['id']}/documents").json()["total"] == 0
    assert owner.post(f"/api/jobs/{job['id']}/cancel").status_code == 409


def test_cancel_running_import_rolls_back(owner, corpus):
    from services.worker.main import claim, execute

    job = upload(owner, corpus["id"], {"a.txt": TEXT_A}).json()
    run = claim()
    assert str(run.id) == job["id"]
    assert owner.get(f"/api/jobs/{job['id']}").json()["state"] == "running"
    assert owner.post(f"/api/jobs/{job['id']}/cancel").json()["state"] == "cancelled"
    execute(run)
    assert owner.get(f"/api/jobs/{job['id']}").json()["state"] == "cancelled"
    assert owner.get(f"/api/corpora/{corpus['id']}/documents").json()["total"] == 0
    assert owner.get(f"/api/corpora/{corpus['id']}").json()["status"] == "empty"
    drain()  # nothing else was queued
    assert owner.get(f"/api/projects/{corpus['project_id']}/jobs").json()["total"] == 1


def test_worker_restart_fails_running_jobs(owner, corpus):
    from services.worker.main import claim, recover

    job = upload(owner, corpus["id"], {"a.txt": TEXT_A}).json()
    claim()
    recover()
    j = owner.get(f"/api/jobs/{job['id']}").json()
    assert j["state"] == "failed" and j["error"]["code"] == "WORKER_RESTARTED"
    assert owner.get(f"/api/corpora/{corpus['id']}").json()["status"] == "failed"


def test_subcorpora(owner, project, corpus, member):
    upload(
        owner,
        corpus["id"],
        {"a.txt": TEXT_A},
        metadata=json.dumps({"year": 2001, "genre": "news"}),
    )
    upload(
        owner,
        corpus["id"],
        {"b.txt": TEXT_B},
        metadata=json.dumps({"year": 2010, "genre": "fiction"}),
    )
    drain()
    pid = project["id"]
    body = {
        "name": "新闻 2000-2005",
        "corpus_id": corpus["id"],
        "filter": {"year": {"gte": 2000, "lte": 2005}},
    }
    assert (
        member("annotator")
        .post(f"/api/projects/{pid}/subcorpora", json=body)
        .status_code
        == 403
    )
    sub = owner.post(f"/api/projects/{pid}/subcorpora", json=body).json()
    assert sub["stats"] == {"documents": 1, "sentences": 2, "tokens": 8}
    assert sub["filter"] == {"year": {"gte": 2000, "lte": 2005}}

    lst = owner.post(
        f"/api/projects/{pid}/subcorpora",
        json={**body, "filter": {"genre": ["news", "fiction"]}},
    ).json()
    assert lst["stats"]["documents"] == 2
    one = owner.post(
        f"/api/projects/{pid}/subcorpora", json={**body, "filter": {"genre": "fiction"}}
    ).json()
    assert one["stats"] == {"documents": 1, "sentences": 2, "tokens": 6}

    for bad in (
        {"author": "x"},
        {"genre": {"gte": "a"}},
        {"year": "2001"},
        {"year": []},
    ):
        r = owner.post(f"/api/projects/{pid}/subcorpora", json={**body, "filter": bad})
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "INVALID_FILTER"

    listing = member("viewer").get(f"/api/projects/{pid}/subcorpora").json()
    assert listing["total"] == 3
    assert owner.get(f"/api/subcorpora/{sub['id']}").json()["stats"]["documents"] == 1
    assert owner.delete(f"/api/subcorpora/{sub['id']}").status_code == 204
    assert owner.get(f"/api/subcorpora/{sub['id']}").status_code == 404


def test_subcorpus_rejects_other_project_corpus(owner, make_user, corpus):
    other = make_user("x@example.edu")
    other_project = other.post("/api/projects", json={"name": "别人的"}).json()
    r = other.post(
        f"/api/projects/{other_project['id']}/subcorpora",
        json={"name": "x", "corpus_id": corpus["id"], "filter": {}},
    )
    assert r.status_code == 404


def test_builtin_jobs_for_admins(owner, project, corpus, make_user):
    admin = make_user("admin@example.edu", admin=True)
    builtin = admin.post("/api/corpora", json={"name": "Tatoeba", "language": "en"})
    files = {f"{n}.txt": TEXT_A for n in "abcd"}
    job = upload(admin, builtin.json()["id"], files).json()
    assert job["owner_email"] == "admin@example.edu"
    assert job["summary"] == "Tatoeba：a.txt、b.txt、c.txt 等 4 个文件"
    upload(owner, corpus["id"], {"x.txt": TEXT_B})  # project job: not listed

    r = admin.get("/api/jobs", params={"builtin": 1})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1 and r.json()["items"][0]["id"] == job["id"]
    assert admin.get("/api/jobs").status_code == 422
    assert owner.get("/api/jobs", params={"builtin": 1}).status_code == 403
    assert owner.get(f"/api/jobs/{job['id']}").status_code == 404
