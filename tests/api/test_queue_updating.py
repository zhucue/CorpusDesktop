"""Job queue lanes (small imports are not stuck behind a large one) and searchable corpora during updates."""

import pytest

from tests.api.conftest import drain, upload

LONG = "Language is a system.\nThe language of science and of every language."
SHORT = "language"


@pytest.fixture
def corpus(owner, project):
    r = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "作文", "language": "en"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _corpus(owner, project, name):
    r = owner.post(
        f"/api/projects/{project['id']}/corpora", json={"name": name, "language": "en"}
    )
    return r.json()


def test_short_imports_first_and_on_light_worker(owner, project, monkeypatch):
    from services.worker.main import claim

    monkeypatch.setenv(
        "LIGHT_IMPORT_BYTES", "20"
    )  # LONG is a long import, SHORT a short one
    a, b, c = (_corpus(owner, project, n) for n in ("a", "b", "c"))
    big1 = upload(owner, a["id"], {"big.txt": LONG}).json()
    big2 = upload(owner, b["id"], {"big.txt": LONG}).json()
    small = upload(owner, c["id"], {"small.txt": SHORT}).json()

    # queue position within each lane
    assert owner.get(f"/api/jobs/{big1['id']}").json()["queue_ahead"] == 0
    assert owner.get(f"/api/jobs/{big2['id']}").json()["queue_ahead"] == 1
    assert owner.get(f"/api/jobs/{small['id']}").json()["queue_ahead"] == 0

    # worker-light (short kinds + small imports) takes only the small import
    light = claim(["stats", "export"], small_imports=True)
    assert str(light.id) == small["id"]
    assert claim(["stats", "export"], small_imports=True) is None
    assert owner.get(f"/api/jobs/{small['id']}").json()["queue_ahead"] is None

    # a heavy worker takes the long imports oldest first; the running one counts as ahead
    run = claim([])
    assert str(run.id) == big1["id"]
    assert owner.get(f"/api/jobs/{big2['id']}").json()["queue_ahead"] == 1


def test_heavy_worker_takes_short_jobs_first(owner, project, monkeypatch):
    from services.worker.main import claim

    monkeypatch.setenv("LIGHT_IMPORT_BYTES", "20")
    a, c = _corpus(owner, project, "a"), _corpus(owner, project, "c")
    upload(owner, a["id"], {"big.txt": LONG}).json()
    small = upload(owner, c["id"], {"small.txt": SHORT}).json()
    assert str(claim([]).id) == small["id"]


def test_small_index_job_follows_small_import(owner, corpus):
    from services.worker.main import claim, execute

    upload(owner, corpus["id"], {"a.txt": LONG})
    execute(claim(["stats"], small_imports=True))  # import on worker-light
    index = claim(["stats"], small_imports=True)  # its index build is small too
    assert index is not None and index.kind == "index"
    assert index.params["tokens"] == 12


def test_one_index_build_per_corpus(owner, corpus):
    from services.api.db import transaction
    from services.api.jobs import enqueue
    from services.api.models import Corpus
    from services.worker.main import claim

    me = owner.get("/api/auth/me").json()["id"]
    with transaction() as db:
        c = db.get(Corpus, corpus["id"])
        for _ in range(2):
            enqueue(db, "index", {"corpus_id": corpus["id"]}, me, c.project_id)
    first = claim([])
    assert first.kind == "index"
    assert claim([]) is None  # the second waits for the running build


def test_updating_corpus_stays_searchable(owner, corpus, fake_engine):
    upload(owner, corpus["id"], {"a.txt": LONG})
    drain()
    before = owner.get(f"/api/corpora/{corpus['id']}").json()
    assert before["status"] == "ready" and before["updating"] is False
    assert before["meta"]["tagset"] == "upos" and before["meta"]["languages"] == ["en"]
    assert before["meta"]["indexed_at"]

    job = upload(owner, corpus["id"], {"b.txt": "Another language text."}).json()
    during = owner.get(f"/api/corpora/{corpus['id']}").json()
    assert during["status"] == "ready" and during["updating"] is True
    r = owner.post(
        "/api/search", json={"scope": {"corpus_id": corpus["id"]}, "query": "language"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["hits"] == 3  # the old index serves

    drain()
    after = owner.get(f"/api/corpora/{corpus['id']}").json()
    assert after["status"] == "ready" and after["updating"] is False
    assert after["stats"]["documents"] == 2  # the new index replaced the old one
    r = owner.post(
        "/api/search", json={"scope": {"corpus_id": corpus["id"]}, "query": "language"}
    )
    assert r.json()["counts"]["hits"] == 4
    assert owner.get(f"/api/jobs/{job['id']}").json()["state"] == "succeeded"


def test_failed_update_keeps_index(owner, corpus):
    upload(owner, corpus["id"], {"a.txt": LONG})
    drain()
    upload(owner, corpus["id"], {"bad.txt": "FAIL here"})
    drain()
    c = owner.get(f"/api/corpora/{corpus['id']}").json()
    assert c["status"] == "ready" and c["error"] == "bad.txt 无法解析"
    assert c["updating"] is False


def test_auto_language_and_progress_units(owner, project):
    r = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "auto", "language": "auto"},
    )
    cid = r.json()["id"]
    job = upload(owner, cid, {"en.txt": LONG}, language="auto").json()
    from services.api.db import session
    from services.api.models import Job

    with session() as db:
        assert db.get(Job, job["id"]).params["language"] is None
    drain()
    c = owner.get(f"/api/corpora/{cid}").json()
    assert c["language"] == "en"  # detected from the text, not left as zh/auto
    docs = owner.get(f"/api/corpora/{cid}/documents").json()["items"]
    assert docs[0]["language"] == "en"
    done = owner.get(f"/api/jobs/{job['id']}").json()
    assert done["progress"]["unit"] == "字"


def test_document_sentences(owner, project):
    r = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "平行", "language": "en"},
    )
    cid = r.json()["id"]
    upload(owner, cid, {"p.tmx": "Hello world\t你好世界\nGood language\t好的语言\n"})
    drain()
    c = owner.get(f"/api/corpora/{cid}").json()
    assert c["parallel"] and c["stats"]["pairs"] == 2
    docs = owner.get(f"/api/corpora/{cid}/documents").json()["items"]
    en = next(d for d in docs if d["language"] == "en")
    assert (
        owner.get(f"/api/corpora/{cid}/documents/{en['id']}").json()["title"]
        == en["title"]
    )
    page = owner.get(
        f"/api/corpora/{cid}/documents/{en['id']}/sentences", params={"page_size": 1}
    ).json()
    assert page["total"] == 2
    [s] = page["items"]
    assert s["idx"] == 0 and s["text"] == "Hello world"
    assert s["aligned"] == [{"language": "zh", "text": "你好世界"}]
    zh = next(d for d in docs if d["language"] == "zh")
    assert (
        owner.get(f"/api/corpora/{cid}/documents/{zh['id']}/sentences").json()["items"][
            1
        ]["aligned"][0]["text"]
        == "Good language"
    )
    other = owner.get(
        f"/api/corpora/{cid}/documents/{zh['id']}".replace(cid, project["id"])
    )
    assert other.status_code == 404
