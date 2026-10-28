"""P3 annotation layers, review, attribute queries and CoNLL-U export (contracts/p3.md)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.api.conftest import drain, upload

TEXT = "Language is a system.\nThe language of science.\nA language again."
# system values per sentence: (pos, deprel, head) for each whitespace token (fake engine tokenisation)
SYSTEM = {
    0: [
        ("NOUN", "nsubj", 4),
        ("AUX", "cop", 4),
        ("DET", "det", 4),
        ("NOUN", "root", 0),
    ],
    1: [
        ("DET", "det", 2),
        ("NOUN", "root", 0),
        ("ADP", "case", 4),
        ("NOUN", "nmod", 2),
    ],
    2: [("DET", "det", 2), ("NOUN", "nsubj", 3), ("ADV", "root", 0)],
}
TOKENS = sum(len(v) for v in SYSTEM.values())

EFFECTIVE_SQL = """
SELECT count(*) FROM tokens t
JOIN sentences s ON s.id = t.sentence_id
JOIN documents d ON d.id = s.document_id
LEFT JOIN annotations ap ON ap.layer_id = CAST(:pos AS uuid) AND ap.document_id = d.id
     AND ap.sentence_index = s.idx AND ap.token_index = t.idx + 1
LEFT JOIN annotations ad ON ad.layer_id = CAST(:dep AS uuid) AND ad.document_id = d.id
     AND ad.sentence_index = s.idx AND ad.token_index = t.idx + 1
WHERE d.corpus_id = CAST(:corpus AS uuid) AND {where}
"""
EFF_POS = (
    "(CASE WHEN ap.status IN ('confirmed', 'modified') THEN ap.label"
    " WHEN ap.status = 'rejected' THEN NULL ELSE t.pos END)"
)
EFF_DEP = (
    "(CASE WHEN ad.status IN ('confirmed', 'modified') THEN ad.label ELSE t.deprel END)"
)


def sql_count(corpus_id, where, pos=None, dep=None):
    """Independent PostgreSQL count of effective token values."""
    from services.api.db import transaction

    with transaction() as db:
        return db.scalar(
            text(EFFECTIVE_SQL.format(where=where)),
            {"corpus": corpus_id, "pos": pos, "dep": dep},
        )


def set_system(doc_id, values):
    from services.api.db import transaction

    with transaction() as db:
        for s, toks in values.items():
            for j, (pos, dep, head) in enumerate(toks):
                db.execute(
                    text(
                        "UPDATE tokens t SET pos = :p, deprel = :d, head = :h, lemma = lower(t.form)"
                        " FROM sentences s WHERE t.sentence_id = s.id AND s.document_id = :doc"
                        " AND s.idx = :s AND t.idx = :j"
                    ),
                    {"p": pos, "d": dep, "h": head, "doc": doc_id, "s": s, "j": j},
                )


@pytest.fixture
def corpus(owner, project):
    c = owner.post(
        f"/api/projects/{project['id']}/corpora", json={"name": "UD", "language": "en"}
    ).json()
    upload(owner, c["id"], {"a.txt": TEXT})
    drain()
    doc = owner.get(f"/api/corpora/{c['id']}/documents").json()["items"][0]
    set_system(doc["id"], SYSTEM)
    c["document_id"] = doc["id"]
    return c


def label_set(client, name):
    items = client.get("/api/label-sets").json()["items"]
    return next(s for s in items if s["name"] == name)


def make_layer(client, project, corpus, kind, name=None, **extra):
    set_name = {"pos": "upos", "dep": "ud-deprel"}[kind]
    r = client.post(
        f"/api/projects/{project['id']}/layers",
        json={
            "corpus_id": corpus["id"],
            "kind": kind,
            "name": name or kind,
            "label_set_id": label_set(client, set_name)["id"],
            **extra,
        },
    )
    assert r.status_code == 200, r.text
    drain()
    return client.get(f"/api/layers/{r.json()['id']}").json()


def act(client, layer, s, t, action, **kw):
    return client.post(
        f"/api/layers/{layer['id']}/annotations",
        json={
            "document_id": layer["_doc"],
            "sentence_index": s,
            "token_index": t,
            "action": action,
            **kw,
        },
    )


def bearer(owner, project):
    from services.api.main import app

    token = owner.post("/api/auth/agent-token", json={"project_id": project["id"]})
    return TestClient(app, headers={"Authorization": f"Bearer {token.json()['token']}"})


def search(client, corpus, q, **kw):
    r = client.post(
        "/api/search", json={"scope": {"corpus_id": corpus["id"]}, "query": q, **kw}
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---- label sets ----


def test_label_sets(owner, project, member):
    builtin = owner.get("/api/label-sets").json()["items"]
    assert {s["name"]: (s["kind"], s["project_id"]) for s in builtin} == {
        "upos": ("pos", None),
        "jieba": ("pos", None),
        "ud-deprel": ("dep", None),
        "learner-errors": ("span", None),
        "translation-strategies": ("span", None),
        "error-correction": ("relation", None),
    }
    upos = label_set(owner, "upos")
    assert len(upos["labels"]) == 17 and upos["labels"][7] == {
        "id": "NOUN",
        "name": "NOUN",
        "description": "名词",
    }
    deprel = {x["id"]: x for x in label_set(owner, "ud-deprel")["labels"]}
    assert sum("parent" not in x for x in deprel.values()) == 37
    assert deprel["nsubj:pass"]["parent"] == "nsubj"

    r = owner.post(
        f"/api/projects/{project['id']}/label-sets",
        json={"name": "我的词性", "kind": "pos", "copy_from": upos["id"]},
    )
    assert r.status_code == 200 and len(r.json()["labels"]) == 17
    mine = r.json()
    r = owner.patch(
        f"/api/label-sets/{mine['id']}",
        json={"labels": [{"id": "N", "name": "名"}, {"id": "V", "name": "动"}]},
    )
    assert [x["id"] for x in r.json()["labels"]] == ["N", "V"]
    dup = owner.patch(
        f"/api/label-sets/{mine['id']}",
        json={"labels": [{"id": "N", "name": "a"}, {"id": "N", "name": "b"}]},
    )
    assert dup.status_code == 422
    listed = owner.get(f"/api/label-sets?project_id={project['id']}&kind=pos").json()
    assert [s["name"] for s in listed["items"]] == ["upos", "jieba", "我的词性"]
    assert (
        owner.patch(f"/api/label-sets/{upos['id']}", json={"name": "x"}).status_code
        == 403
    )
    viewer = member("viewer")
    assert viewer.get(f"/api/label-sets?project_id={project['id']}").status_code == 200
    r = viewer.post(
        f"/api/projects/{project['id']}/label-sets",
        json={"name": "x", "kind": "pos", "labels": []},
    )
    assert r.status_code == 403
    assert owner.delete(f"/api/label-sets/{mine['id']}").status_code == 204


# ---- layers and pre-annotation ----


def test_layer_lifecycle_and_preannotation(owner, project, corpus):
    pos = make_layer(owner, project, corpus, "pos")
    assert pos["status"] == "ready" and pos["source_model"] == "system"
    assert pos["corpus_name"] == "UD" and pos["job_id"]
    assert pos["progress"] == {
        "total": TOKENS,
        "suggested": TOKENS,
        "confirmed": 0,
        "modified": 0,
        "rejected": 0,
    }
    assert pos["documents"] == {"total": 1, "done": 0}
    job = owner.get(f"/api/jobs/{pos['job_id']}").json()
    assert job["kind"] == "preannotate" and job["state"] == "succeeded"
    assert job["progress"]["done"] == job["progress"]["total"] == 1

    dep = make_layer(owner, project, corpus, "dep")
    doc = corpus["document_id"]
    for layer, pick in ((pos, lambda v: (v[0], None)), (dep, lambda v: (v[1], v[2]))):
        for s, toks in SYSTEM.items():
            sent = owner.get(f"/api/layers/{layer['id']}/sentences/{doc}/{s}").json()
            assert [t["index"] for t in sent["tokens"]] == list(range(1, len(toks) + 1))
            got = [(a["model_label"], a["model_head"]) for a in sent["annotations"]]
            assert got == [
                pick(v) for v in toks
            ]  # pre-annotation equals the system layer
            assert all(
                a["status"] == "suggested"
                and a["source"] == "system"
                and a["revision"] == 0
                for a in sent["annotations"]
            )
            assert sent["status"] == "pending"
    sent = owner.get(f"/api/layers/{dep['id']}/sentences/{doc}/0").json()
    assert sent["tokens"][0]["system"] == {"pos": "NOUN", "head": 4, "deprel": "nsubj"}

    listed = owner.get(f"/api/projects/{project['id']}/layers?corpus_id={corpus['id']}")
    assert [x["kind"] for x in listed.json()["items"]] == ["dep", "pos"]

    # re-run keeps reviewed tokens
    dep["_doc"] = doc
    assert act(owner, dep, 0, 1, "modify", label="obj").status_code == 200
    job = owner.post(f"/api/layers/{dep['id']}/preannotate", json={}).json()
    assert job["kind"] == "preannotate"
    drain()
    a = owner.get(f"/api/layers/{dep['id']}/sentences/{doc}/0").json()["annotations"]
    assert (a[0]["label"], a[0]["status"]) == ("obj", "modified")
    assert a[1]["revision"] == 1  # suggested tokens were rewritten

    other = owner.post("/api/projects", json={"name": "别的"}).json()
    r = owner.post(
        f"/api/projects/{other['id']}/layers",
        json={
            "corpus_id": corpus["id"],
            "kind": "pos",
            "name": "x",
            "label_set_id": label_set(owner, "upos")["id"],
        },
    )
    assert r.status_code == 404
    r = owner.post(
        f"/api/projects/{project['id']}/layers",
        json={
            "corpus_id": corpus["id"],
            "kind": "pos",
            "name": "x",
            "label_set_id": label_set(owner, "ud-deprel")["id"],
        },
    )
    assert r.status_code == 422
    in_use = owner.delete(f"/api/label-sets/{label_set(owner, 'upos')['id']}")
    assert in_use.status_code == 403  # built-in
    assert owner.delete(f"/api/layers/{pos['id']}").status_code == 204
    assert owner.get(f"/api/layers/{pos['id']}").status_code == 404


def test_label_set_in_use(owner, project, corpus):
    upos = label_set(owner, "upos")
    mine = owner.post(
        f"/api/projects/{project['id']}/label-sets",
        json={"name": "p", "kind": "pos", "copy_from": upos["id"]},
    ).json()
    r = owner.post(
        f"/api/projects/{project['id']}/layers",
        json={
            "corpus_id": corpus["id"],
            "kind": "pos",
            "name": "p",
            "label_set_id": mine["id"],
        },
    )
    assert r.status_code == 200
    r = owner.delete(f"/api/label-sets/{mine['id']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "LABEL_SET_IN_USE"


def test_chinese_dependency_preannotation(owner, project, monkeypatch):
    from engine import nlp

    calls = []

    def fake_parse(doc):
        calls.append([[t.form for t in s.tokens] for s in doc.sentences])
        for s in doc.sentences:
            for i, t in enumerate(s.tokens):
                t.head, t.deprel = (0, "root") if i == 0 else (1, "dep")

    monkeypatch.setattr(nlp, "annotate_dependencies_zh", fake_parse)
    c = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "中文", "language": "zh"},
    ).json()
    upload(owner, c["id"], {"z.txt": "语言 是 工具\n我们 研究 语言"})
    drain()
    layer = make_layer(owner, project, c, "dep")
    assert layer["status"] == "ready" and layer["source_model"].startswith("stanza ")
    assert calls == [[["语言", "是", "工具"], ["我们", "研究", "语言"]]]
    doc = owner.get(f"/api/corpora/{c['id']}/documents").json()["items"][0]["id"]
    sent = owner.get(f"/api/layers/{layer['id']}/sentences/{doc}/1").json()
    assert [(a["label"], a["head"], a["source"]) for a in sent["annotations"]] == [
        ("root", 0, "model:stanza-zh"),
        ("dep", 1, "model:stanza-zh"),
        ("dep", 1, "model:stanza-zh"),
    ]
    # written back to the system layer
    assert [t["system"]["deprel"] for t in sent["tokens"]] == ["root", "dep", "dep"]
    assert sent["tokens"][1]["system"]["head"] == 1
    # a second dep layer finds dependencies in `tokens` and does not parse again
    second = make_layer(owner, project, c, "dep", name="第二层")
    assert second["source_model"] == "system" and len(calls) == 1

    reset = owner.post(f"/api/layers/{layer['id']}/sentences/{doc}/1/reset", json={})
    assert {a["source"] for a in reset.json()["annotations"]} == {"model:stanza-zh"}


# ---- review ----


def test_review_actions(owner, project, corpus):
    doc = corpus["document_id"]
    pos = make_layer(owner, project, corpus, "pos") | {"_doc": doc}
    r = act(owner, pos, 0, 1, "confirm")
    assert r.status_code == 200, r.text
    a = r.json()
    assert (a["status"], a["revision"], a["label"], a["token_index"]) == (
        "confirmed",
        1,
        "NOUN",
        1,
    )
    assert a["source"] == f"human:{owner.user_id}" and a["updated_by"] == owner.user_id
    a = act(owner, pos, 0, 2, "modify", label="VERB").json()
    assert (a["status"], a["label"], a["model_label"], a["revision"]) == (
        "modified",
        "VERB",
        "AUX",
        1,
    )
    a = act(owner, pos, 0, 2, "modify", label="AUX").json()  # back to the model value
    assert (a["status"], a["revision"]) == ("confirmed", 2)
    assert act(owner, pos, 0, 3, "reject").json()["status"] == "rejected"
    bad = act(owner, pos, 0, 4, "modify", label="FOO")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_LABEL"
    assert act(owner, pos, 0, 9, "confirm").status_code == 404
    assert act(owner, pos, 0, 4, "modify").status_code == 422

    layer = owner.get(f"/api/layers/{pos['id']}").json()
    assert layer["progress"] == {
        "total": TOKENS,
        "suggested": TOKENS - 3,
        "confirmed": 2,
        "modified": 0,
        "rejected": 1,
    }

    sent = owner.post(
        f"/api/layers/{pos['id']}/sentences/{doc}/0/confirm", json={}
    ).json()
    assert sent["status"] == "done"
    assert [x["status"] for x in sent["annotations"]] == [
        "confirmed",
        "confirmed",
        "rejected",
        "confirmed",
    ]
    assert [x["revision"] for x in sent["annotations"]] == [1, 2, 1, 1]

    # cursor paging in corpus order; status=pending skips the finished sentence
    seen, cursor = [], None
    while True:
        params = {"page_size": 1, **({"cursor": cursor} if cursor else {})}
        page = owner.get(f"/api/layers/{pos['id']}/sentences", params=params).json()
        seen += [(x["sentence_index"], x["status"]) for x in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == [(0, "done"), (1, "pending"), (2, "pending")]
    pending = owner.get(f"/api/layers/{pos['id']}/sentences?status=pending").json()
    assert [x["sentence_index"] for x in pending["items"]] == [1, 2]
    assert pending["next_cursor"] is None
    bad = owner.get(f"/api/layers/{pos['id']}/sentences?cursor=nope")
    assert bad.status_code == 422

    docs = owner.get(f"/api/layers/{pos['id']}/documents").json()["items"]
    assert docs == [
        {"document_id": doc, "title": "a", "sentences": 3, "done": 1, "pending": 2}
    ]

    reset = owner.post(
        f"/api/layers/{pos['id']}/sentences/{doc}/0/reset", json={}
    ).json()
    assert [(x["status"], x["label"], x["source"]) for x in reset["annotations"]] == [
        ("suggested", p, "system") for p, _, _ in SYSTEM[0]
    ]
    assert [x["revision"] for x in reset["annotations"]] == [2, 3, 2, 2]
    assert (
        owner.get(f"/api/layers/{pos['id']}").json()["progress"]["suggested"] == TOKENS
    )

    dep = make_layer(owner, project, corpus, "dep") | {"_doc": doc}
    r = act(owner, dep, 1, 2, "reject")
    assert r.status_code == 422 and r.json()["error"]["code"] == "REJECT_NOT_ALLOWED"
    assert (
        act(owner, dep, 1, 2, "modify", head=5).json()["error"]["code"]
        == "INVALID_HEAD"
    )
    assert (
        act(owner, dep, 1, 2, "modify", head=2).json()["error"]["code"]
        == "INVALID_HEAD"
    )
    a = act(owner, dep, 1, 2, "modify", label="nsubj", head=4).json()
    assert (a["label"], a["head"], a["model_label"], a["model_head"], a["status"]) == (
        "nsubj",
        4,
        "root",
        0,
        "modified",
    )
    assert act(owner, dep, 1, 1, "modify", head=4).json()["status"] == "modified"
    act(owner, dep, 2, 1, "confirm")

    diff = owner.get(f"/api/layers/{dep['id']}/diff").json()
    assert diff["counts"] == {
        "changed": 2,
        "confirmed": 1,
        "rejected": 0,
        "pending": TOKENS - 3,
    }
    assert [x["sentence_index"] for x in diff["items"]] == [1]
    everything = owner.get(f"/api/layers/{dep['id']}/diff?only_changed=false").json()
    assert len(everything["items"]) == 3

    stats = owner.get(f"/api/layers/{dep['id']}/stats").json()
    labels = {x["label"]: x for x in stats["labels"]}
    assert labels["nsubj"] == {
        "label": "nsubj",
        "count": 3,
        "confirmed": 0,
        "modified": 1,
    }
    assert labels["det"]["count"] == 3 and labels["det"]["confirmed"] == 1
    assert stats["progress"]["modified"] == 2
    assert stats["per_document"][0]["total"] == TOKENS


def test_permissions(owner, project, corpus, member, make_user):
    doc = corpus["document_id"]
    pos = make_layer(owner, project, corpus, "pos") | {"_doc": doc}
    viewer, annotator, outsider = (
        member("viewer"),
        member("annotator"),
        make_user("x@example.edu"),
    )
    agent = bearer(owner, project)
    url = f"/api/layers/{pos['id']}"

    for client in (viewer, annotator, agent):
        assert client.get(url).status_code == 200
        assert client.get(f"{url}/sentences").status_code == 200
        assert client.get(f"{url}/diff").status_code == 200
    assert outsider.get(url).status_code == 404
    assert act(viewer, pos, 0, 1, "confirm").status_code == 403
    assert act(agent, pos, 0, 1, "confirm").status_code == 403
    assert agent.post(f"{url}/sentences/{doc}/0/confirm", json={}).status_code == 403
    assert agent.delete(url).status_code == 403
    # single mode: only the layer creator (or a listed annotator) writes; other members read
    editor = member("editor")
    for client in (annotator, editor):
        r = act(client, pos, 0, 1, "confirm")
        assert r.status_code == 403 and r.json()["error"]["code"] == "NOT_ANNOTATOR"
        r = client.post(f"{url}/sentences/{doc}/1/confirm", json={})
        assert r.status_code == 403
        assert client.get(f"{url}/sentences").status_code == 200
    assert act(owner, pos, 0, 1, "confirm").status_code == 200
    assert owner.post(f"{url}/sentences/{doc}/1/confirm", json={}).status_code == 200
    body = {
        "corpus_id": corpus["id"],
        "kind": "pos",
        "name": "x",
        "label_set_id": label_set(owner, "upos")["id"],
    }
    assert (
        annotator.post(f"/api/projects/{project['id']}/layers", json=body).status_code
        == 403
    )
    assert annotator.delete(url).status_code == 403
    assert viewer.post(f"{url}/export", json={"format": "conllu"}).status_code == 200

    # agent: suggestions only change tokens still suggested
    ref = {"document_id": doc, "sentence_index": 2, "token_index": 3}
    r = agent.post(f"{url}/suggest", json={**ref, "label": "NOUN", "model": "qwen-3"})
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["source"], r.json()["label"]) == (
        "suggested",
        "model:qwen-3",
        "NOUN",
    )
    assert r.json()["model_label"] == "ADV"
    locked = {
        "document_id": doc,
        "sentence_index": 0,
        "token_index": 1,
        "label": "VERB",
    }
    r = agent.post(f"{url}/suggest", json=locked)
    assert r.status_code == 409 and r.json()["error"]["code"] == "ANNOTATION_REVIEWED"
    r = agent.post(f"{url}/suggest", json={"items": [locked, {**ref, "label": "X"}]})
    assert [a["label"] for a in r.json()["items"]] == ["X"]
    assert r.json()["skipped"] == [
        {
            "document_id": doc,
            "sentence_index": 0,
            "token_index": 1,
            "reason": "confirmed",
        }
    ]
    bad = agent.post(f"{url}/suggest", json={**ref, "label": "FOO"})
    assert bad.status_code == 422
    assert viewer.post(f"{url}/suggest", json={**ref, "label": "X"}).status_code == 403
    a = owner.get(f"{url}/sentences/{doc}/0").json()["annotations"][0]
    assert (a["status"], a["label"]) == ("confirmed", "NOUN")
    # the agent may create layers (annot.create_layer) but not edit label sets
    assert (
        agent.post(f"/api/projects/{project['id']}/layers", json=body).status_code
        == 200
    )
    r = agent.post(
        f"/api/projects/{project['id']}/label-sets",
        json={"name": "x", "kind": "pos", "labels": []},
    )
    assert r.status_code == 403


# ---- attribute queries ----


def test_attribute_queries(owner, project, corpus, fake_engine):
    doc = corpus["document_id"]
    cid = corpus["id"]
    pos = make_layer(owner, project, corpus, "pos") | {"_doc": doc}
    dep = make_layer(owner, project, corpus, "dep") | {"_doc": doc}
    act(owner, pos, 0, 3, "reject")  # "a" no longer DET
    act(owner, pos, 2, 3, "modify", label="NOUN")  # "again." ADV → NOUN
    act(owner, dep, 1, 2, "modify", label="nsubj", head=4)  # "language" root → nsubj
    act(owner, dep, 0, 1, "confirm")
    act(owner, pos, 1, 2, "confirm")

    calls = len(fake_engine.calls)
    r = search(owner, corpus, "{dep=nsubj}")
    assert len(fake_engine.calls) == calls  # answered from PostgreSQL
    assert r["counts"] == {"hits": 2, "sentences": 2, "documents": 1, "complete": True}
    assert r["counts"]["hits"] == sql_count(cid, "t.deprel = 'nsubj'")
    assert [(h["sentence_index"], h["match"]) for h in r["items"]] == [
        (0, "Language"),
        (2, "language"),
    ]
    text = TEXT
    for h in r["items"]:
        assert text[h["start_cp"] : h["end_cp"]] == h["match"]
        assert h["hit_id"] == f"{doc}:{h['start_cp']}-{h['end_cp']}"
        assert h["left"] == text[max(0, h["start_cp"] - 40) : h["start_cp"]]
        assert h["document_title"] == "a"

    layers = {"pos": pos["id"], "dep": dep["id"]}
    r = search(owner, corpus, "{dep=nsubj}", layers=layers)
    expected = sql_count(cid, f"{EFF_DEP} = 'nsubj'", pos["id"], dep["id"])
    assert r["counts"]["hits"] == expected == 3
    r = search(owner, corpus, "{pos=NOUN,dep=root}", layers=layers)
    expected = sql_count(
        cid, f"{EFF_POS} = 'NOUN' AND {EFF_DEP} = 'root'", pos["id"], dep["id"]
    )
    assert r["counts"]["hits"] == expected == 2  # "system.", and "again." now NOUN
    assert search(owner, corpus, "{pos=NOUN,dep=root}")["counts"]["hits"] == 2
    r = search(owner, corpus, "{pos=DET|ADV}", layers=layers)
    assert (
        r["counts"]["hits"]
        == sql_count(cid, f"{EFF_POS} IN ('DET', 'ADV')", pos["id"], dep["id"])
        == 2
    )
    assert search(owner, corpus, "{lemma=LANGUAGE}")["counts"]["hits"] == 3
    r = search(owner, corpus, "/NOUN{dep=nsubj|root}", layers=layers)
    assert r["counts"]["hits"] == sql_count(
        cid, f"t.pos = 'NOUN' AND {EFF_DEP} IN ('nsubj', 'root')", pos["id"], dep["id"]
    )
    r = search(owner, corpus, "{dep=nsubj}", layers=layers, sort="right")
    # by the following words: "again." < "is a" < "of science."
    assert [h["sentence_index"] for h in r["items"]] == [2, 0, 1]
    r = search(
        owner, corpus, "{dep=nsubj}", layers=layers, context={"unit": "sentence"}
    )
    assert r["items"][1]["right"] == " of science."

    # anchored: CWB candidates (fake engine: occurrences of "language") filtered on the slot token
    r = search(owner, corpus, "language{dep=nsubj}", layers=layers)
    assert fake_engine.calls[-1]["cqp"].splitlines()[1:] == [
        "#attr 0 dep=nsubj",
        '#target 0 @[word="language" %c]',
    ]
    expected = sql_count(
        cid, f"lower(t.form) = 'language' AND {EFF_DEP} = 'nsubj'", pos["id"], dep["id"]
    )
    assert r["counts"]["hits"] == expected == 3
    r = search(owner, corpus, "language{dep=nsubj}")
    assert (
        r["counts"]["hits"]
        == sql_count(cid, "lower(t.form) = 'language' AND t.deprel = 'nsubj'")
        == 2
    )

    bad = owner.post(
        "/api/search",
        json={
            "scope": {"corpus_id": cid},
            "query": "{dep=nsubj}",
            "layers": {"pos": dep["id"]},
        },
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_LAYER"

    # statistics: deprel frequency over the dep layer, counted like the search
    job = owner.post(
        "/api/stats/frequency",
        json={
            "scope": {"corpus_id": cid},
            "unit": "deprel",
            "layers": {"dep": dep["id"]},
        },
    ).json()
    drain()
    job = owner.get(f"/api/jobs/{job['id']}").json()
    assert job["state"] == "succeeded", job
    stat = owner.get(f"/api/stats/{job['result']['stat_id']}").json()
    rows = {r["key"]: r for r in stat["rows"]}
    assert (
        rows["nsubj"]["values"]["freq"] == 3
        and rows["nsubj"]["search_query"] == "{dep=nsubj}"
    )
    assert rows["root"]["values"]["freq"] == 2
    assert stat["totals"]["tokens"] == TOKENS
    assert sum(r["values"]["freq"] for r in stat["rows"]) == TOKENS
    r = owner.post(
        "/api/stats/collocations",
        json={"scope": {"corpus_id": cid}, "node": "{dep=nsubj}"},
    )
    assert r.status_code == 422


def test_conllu_export(owner, project, corpus):
    conllu = pytest.importorskip("conllu")
    doc = corpus["document_id"]
    dep = make_layer(owner, project, corpus, "dep") | {"_doc": doc}
    act(owner, dep, 1, 2, "modify", label="nsubj", head=4)
    job = owner.post(
        f"/api/layers/{dep['id']}/export", json={"format": "conllu"}
    ).json()
    assert job["kind"] == "export"
    drain()
    job = owner.get(f"/api/jobs/{job['id']}").json()
    assert job["state"] == "succeeded", job
    assert job["result"]["rows"] == 3 and job["result"]["filename"].endswith(".conllu")
    r = owner.get(f"/api/jobs/{job['id']}/download")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    sents = conllu.parse(r.text)
    assert [s.metadata["text"] for s in sents] == TEXT.split("\n")
    docs = owner.get(f"/api/corpora/{corpus['id']}/documents").json()
    title = docs["items"][0]["title"]
    # document title (no external id) and the sentence number as the platform shows it
    assert sents[0].metadata["sent_id"] == f"{'_'.join(title.split())}-1"
    assert sents[1].metadata["sent_id"] == f"{'_'.join(title.split())}-2"
    for s, sent in enumerate(sents):
        rows = [(t["form"], t["upos"], t["deprel"], t["head"]) for t in sent]
        expected = [
            (form, p, d, h)
            for form, (p, d, h) in zip(TEXT.split("\n")[s].split(), SYSTEM[s])
        ]
        if s == 1:
            expected[1] = ("language", "NOUN", "nsubj", 4)  # the human value wins
        assert rows == expected


def test_project_rename_usage_and_delete(owner, project, corpus, member):
    """Q71: owners rename and delete a project; others may not; delete removes layers with project label sets."""
    pid = project["id"]
    upos = label_set(owner, "upos")
    mine = owner.post(
        f"/api/projects/{pid}/label-sets",
        json={"name": "p", "kind": "pos", "copy_from": upos["id"]},
    ).json()
    r = owner.post(
        f"/api/projects/{pid}/layers",
        json={"corpus_id": corpus["id"], "kind": "pos", "name": "p", "label_set_id": mine["id"]},
    )
    assert r.status_code == 200, r.text
    drain()
    owner.post(
        f"/api/projects/{pid}/kb/documents",
        json={"kind": "note", "title": "n", "body": "x"},
    )
    editor = member("editor")
    assert editor.patch(f"/api/projects/{pid}", json={"name": "改名"}).status_code == 403
    assert editor.delete(f"/api/projects/{pid}").status_code == 403
    r = owner.patch(f"/api/projects/{pid}", json={"name": " 新名称 "})
    assert r.status_code == 200 and r.json()["name"] == "新名称"
    assert owner.patch(f"/api/projects/{pid}", json={"name": ""}).status_code == 422
    usage = editor.get(f"/api/projects/{pid}/usage").json()
    assert usage == {
        "corpora": 1,
        "layers": 1,
        "notes": 1,
        "kb_documents": 0,
        "terms": 0,
        "members": 2,
    }
    assert owner.delete(f"/api/projects/{pid}").status_code == 204
    assert owner.get(f"/api/projects/{pid}").status_code == 404
    assert editor.get(f"/api/projects/{pid}").status_code == 404
    assert owner.get(f"/api/corpora/{corpus['id']}").status_code == 404
    assert owner.get("/api/projects").json()["total"] == 0


def test_sentence_system_tokens_without_layer(owner, make_user, corpus):
    """GET /corpora/{id}/documents/{doc}/sentences/{n}: system POS and dependencies with no layer (read-only)."""
    url = f"/api/corpora/{corpus['id']}/documents/{corpus['document_id']}/sentences"
    s = owner.get(f"{url}/0").json()
    assert s["text"] == "Language is a system." and s["sentence_index"] == 0
    assert [
        (t["index"], t["form"], t["pos"], t["deprel"], t["head"]) for t in s["tokens"]
    ] == [
        (1, "Language", "NOUN", "nsubj", 4),
        (2, "is", "AUX", "cop", 4),
        (3, "a", "DET", "det", 4),
        (4, "system.", "NOUN", "root", 0),
    ]
    assert owner.get(f"{url}/9").status_code == 404
    assert make_user("stranger@example.edu").get(f"{url}/0").status_code in (403, 404)
