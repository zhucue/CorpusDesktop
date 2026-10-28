"""P6-3 权限与撤销回归：对运行中的 Compose 栈执行（contracts/p6.md P6-3）。

STACK_URL=http://127.0.0.1:8088 uv run pytest tests/integration/test_permissions_matrix.py -s -p no:cacheprovider

账号经 `docker compose … exec -T api python scripts/create_account.py --batch` 创建，随机密码只走标准输入；
STACK_COMPOSE 可改 compose 命令（默认 `docker compose -f deploy/compose.yaml`），STACK_ORIGIN 默认等于 STACK_URL。
测试只创建并改动自己的账号、项目与内置语料（结束时删除内置语料与项目）；矩阵表打印到标准输出。
"""

import json
import os
import secrets
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

STACK_URL = os.environ.get("STACK_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not STACK_URL, reason="STACK_URL 未设置")
ORIGIN = os.environ.get("STACK_ORIGIN", STACK_URL)
COMPOSE = os.environ.get(
    "STACK_COMPOSE", "docker compose -f deploy/compose.yaml"
).split()
ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures"
TAG = secrets.token_hex(3)

ROLES = ["owner", "editor", "annotator", "viewer", "outsider", "admin", "bearer"]
SHORT = {
    "owner": "O",
    "editor": "E",
    "annotator": "A",
    "viewer": "V",
    "outsider": "N",
    "admin": "P",
    "bearer": "B",
}
OK = "ok"


def exp(o, e, a, v, n, p, b):
    return dict(zip(ROLES, [o, e, a, v, n, p, b]))


READ = exp(OK, OK, OK, OK, 404, 404, OK)
WRITE = exp(OK, OK, 403, 403, 404, 404, OK)
WRITE_H = {**WRITE, "bearer": 403}  # owner / editor, cookie session only
ANNOT = exp(OK, OK, OK, 403, 404, 404, OK)
ANNOT_H = {**ANNOT, "bearer": 403}
EDIT = ANNOT  # knowledge base: owner / editor / annotator
EDIT_C = ANNOT_H
DELETE_C = {**WRITE, "bearer": 403}  # kb delete: owner / editor or creator, cookie only
MANAGE_H = exp(OK, 403, 403, 403, 404, 404, 403)
ANYONE = exp(OK, OK, OK, OK, OK, OK, OK)
COOKIE = {**ANYONE, "bearer": 403}
ADMIN = exp(403, 403, 403, 403, 403, OK, 403)
ADMIN_FLAG = {**ADMIN, "admin": 422}  # admin without builtin=1
CREATOR = exp(OK, 403, 403, 403, 404, 404, OK)  # single-mode layer: creator only
CREATOR_H = {**CREATOR, "bearer": 403}
JOB_OWN = exp(OK, OK, 403, OK, 404, 404, OK)  # viewer's job: creator, owner, editor
AGENT_LIST = exp(OK, OK, OK, OK, 404, 404, 401)
AGENT_OWN = exp(OK, 404, 404, 404, 404, 404, 401)


# ---- clients ----


class Client:
    def __init__(self, name, token=None):
        self.name = name
        headers = {"Origin": ORIGIN}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.Client(base_url=STACK_URL, headers=headers, timeout=120)

    def req(self, method, path, **kw):
        return self.http.request(method, path, **kw)

    def get(self, path, **kw):
        return self.req("GET", path, **kw)

    def post(self, path, **kw):
        return self.req("POST", path, **kw)

    def patch(self, path, **kw):
        return self.req("PATCH", path, **kw)

    def put(self, path, **kw):
        return self.req("PUT", path, **kw)

    def delete(self, path, **kw):
        return self.req("DELETE", path, **kw)

    def ok(self, method, path, **kw):
        r = self.req(method, path, **kw)
        assert r.status_code < 300, (
            f"{self.name} {method} {path} → {r.status_code} {r.text[:500]}"
        )
        return (
            r.json()
            if r.content and "json" in r.headers.get("content-type", "")
            else None
        )


def create_accounts(names, admin=()):
    """Accounts with random passwords; passwords only ever travel over stdin."""
    specs = {
        n: {
            "email": f"p6-{TAG}-{n}@example.edu",
            "password": secrets.token_urlsafe(18),
            "admin": n in admin,
        }
        for n in names
    }
    out = subprocess.run(
        [
            *COMPOSE,
            "exec",
            "-T",
            "api",
            "python",
            "scripts/create_account.py",
            "--batch",
        ],
        input="".join(json.dumps(s) + "\n" for s in specs.values()),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        check=False,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    ids = {
        row["email"]: row["id"]
        for row in map(json.loads, filter(None, out.stdout.splitlines()))
    }
    accounts = {}
    for n, s in specs.items():
        c = Client(n)
        c.ok(
            "POST",
            "/api/auth/login",
            json={"email": s["email"], "password": s["password"]},
        )
        c.id, c.email = ids[s["email"]], s["email"]
        accounts[n] = c
    return accounts


def wait_job(client, job_id, timeout=600):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.ok("GET", f"/api/jobs/{job_id}")
        if job["state"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(1)
    raise AssertionError(f"任务 {job_id} 超时")


def wait_corpus(client, corpus_id, timeout=600):
    deadline = time.time() + timeout
    while time.time() < deadline:
        c = client.ok("GET", f"/api/corpora/{corpus_id}")
        if c["status"] in ("ready", "failed"):
            assert c["status"] == "ready", c
            return c
        time.sleep(1)
    raise AssertionError(f"语料库 {corpus_id} 超时")


def make_corpus(owner, project_id, name, files, language="en"):
    c = owner.ok(
        "POST",
        f"/api/projects/{project_id}/corpora",
        json={"name": name, "language": language},
    )
    if files:
        upload(owner, c["id"], files, language)
    return c


def upload(client, corpus_id, files, language="en"):
    return client.post(
        f"/api/corpora/{corpus_id}/documents",
        files=[("files", (n, data, "application/octet-stream")) for n, data in files],
        data={"language": language},
    )


def tmx():
    return [("pairs.tmx", (FIX / "sample.tmx").read_bytes())]


def txt(n):
    return [
        (f"t{i}.txt", f"Language study {i}. Students learn a language.\n".encode())
        for i in range(n)
    ]


# ---- world ----


@dataclass
class World:
    u: dict
    bearer: Client
    bearer_q: Client
    ids: dict = field(default_factory=dict)


@pytest.fixture(scope="module")
def world():
    u = create_accounts(
        [
            "owner",
            "editor",
            "annotator",
            "viewer",
            "outsider",
            "admin",
            "spare",
            "leaver",
        ],
        admin=("admin",),
    )
    o = u["owner"]
    ids = {}
    p = o.ok("POST", "/api/projects", json={"name": f"P6 权限 {TAG}"})["id"]
    q = o.ok("POST", "/api/projects", json={"name": f"P6 另一项目 {TAG}"})["id"]
    ids.update(project=p, other_project=q)
    for name, role in (
        ("editor", "editor"),
        ("annotator", "annotator"),
        ("viewer", "viewer"),
        ("leaver", "editor"),
    ):
        o.ok("PUT", f"/api/projects/{p}/members/{u[name].id}", json={"role": role})

    corpus = make_corpus(o, p, "平行样本", tmx())
    victim = make_corpus(o, p, "删除用", txt(8))
    doomed = make_corpus(o, p, "待删除语料", tmx())
    for c in (corpus, victim, doomed):
        wait_corpus(o, c["id"])
    ids.update(corpus=corpus["id"], victim=victim["id"], doomed=doomed["id"])
    docs = o.ok("GET", f"/api/corpora/{corpus['id']}/documents")["items"]
    en = next(d for d in docs if d["language"].startswith("en"))
    zh = next(d for d in docs if d["language"].startswith("zh"))
    ids.update(doc_en=en["id"], doc_zh=zh["id"])
    ids["victim_docs"] = [
        d["id"] for d in o.ok("GET", f"/api/corpora/{victim['id']}/documents")["items"]
    ]

    ids["builtin"] = u["admin"].ok(
        "POST", "/api/corpora", json={"name": f"P6 内置 {TAG}", "language": "en"}
    )["id"]

    sets = o.ok("GET", "/api/label-sets", params={"project_id": p, "page_size": 200})[
        "items"
    ]
    by_kind = lambda kind, name=None: next(
        s["id"]
        for s in sets
        if s["kind"] == kind and (name is None or s["name"] == name)
    )
    ids.update(ls_span=by_kind("span", "learner-errors"), ls_pos=by_kind("pos", "upos"))
    try:
        ids["ls_rel"] = by_kind("relation")
    except StopIteration:
        ids["ls_rel"] = o.ok(
            "POST",
            f"/api/projects/{p}/label-sets",
            json={
                "name": "rel",
                "kind": "relation",
                "labels": [{"id": "cause", "name": "cause"}],
            },
        )["id"]

    def layer(**body):
        return o.ok("POST", f"/api/projects/{p}/layers", json=body)

    pos = layer(
        corpus_id=corpus["id"], kind="pos", name="词性", label_set_id=ids["ls_pos"]
    )
    if pos.get("job_id"):
        wait_job(o, pos["job_id"])
    ids["layer_pos"] = pos["id"]
    ids["layer_span"] = layer(
        corpus_id=corpus["id"],
        kind="span",
        name="偏误",
        label_set_id=ids["ls_span"],
        preannotate=False,
    )["id"]
    ids["layer_rel"] = layer(
        kind="relation",
        name="关系",
        base_layer_id=ids["layer_span"],
        label_set_id=ids["ls_rel"],
        preannotate=False,
    )["id"]
    ids["layer_align"] = layer(
        corpus_id=corpus["id"],
        tgt_corpus_id=corpus["id"],
        kind="alignment",
        name="对齐",
        level="sentence",
        preannotate=False,
    )["id"]
    ids["layer_align_word"] = layer(
        corpus_id=corpus["id"],
        tgt_corpus_id=corpus["id"],
        kind="alignment",
        name="词对齐",
        level="word",
        preannotate=False,
    )["id"]
    ids["layer_multi"] = layer(
        corpus_id=corpus["id"],
        kind="span",
        name="多人",
        label_set_id=ids["ls_span"],
        mode="multi",
        annotators=[o.id, u["annotator"].id],
        preannotate=False,
    )["id"]
    span_rows = o.ok(
        "GET",
        f"/api/layers/{ids['layer_span']}/spans",
        params={"document_id": en["id"]},
    )["items"]
    ids["sentences"] = [
        (r["document_id"], r["sentence_index"], r["start_cp"], r["end_cp"])
        for r in span_rows
    ]
    ids["nz"] = len(
        o.ok(
            "GET",
            f"/api/layers/{ids['layer_span']}/spans",
            params={"document_id": zh["id"]},
        )["items"]
    )
    ids["span_label"] = "时态"
    ids["align_rows"] = o.ok("GET", f"/api/layers/{ids['layer_align']}/alignments")[
        "items"
    ]

    scope = {"corpus_id": corpus["id"]}
    ids["subcorpus"] = o.ok(
        "POST",
        f"/api/projects/{p}/subcorpora",
        json={"name": "全部", "corpus_id": corpus["id"], "filter": {}},
    )["id"]
    ids["query"] = o.ok(
        "POST",
        f"/api/projects/{p}/queries",
        json={"name": "q", "query": "language", "scope": scope},
    )["id"]
    ids["stat"] = run_stat(o, scope)
    ids["evidence"] = o.ok(
        "POST",
        f"/api/projects/{p}/evidence",
        json={"kind": "text", "text": "Language shapes thought.", "source": "样本"},
    )["id"]
    export = o.ok(
        "POST",
        "/api/search/export",
        json={"scope": scope, "query": "language", "format": "csv"},
    )
    assert wait_job(o, export["id"])["state"] == "succeeded"
    ids["export_job"] = export["id"]
    viewer_export = u["viewer"].ok(
        "POST",
        "/api/search/export",
        json={"scope": scope, "query": "language", "format": "csv"},
    )
    assert wait_job(u["viewer"], viewer_export["id"])["state"] == "succeeded"
    ids["viewer_job"] = viewer_export["id"]
    ids["note"] = o.ok(
        "POST",
        f"/api/projects/{p}/kb/documents",
        json={"kind": "note", "title": "笔记", "body": "language 研究"},
    )["id"]
    ids["term"] = o.ok(
        "POST", f"/api/projects/{p}/kb/terms", json={"term": f"language-{TAG}"}
    )["id"]
    ids["session"] = o.ok(
        "POST", "/agent/sessions", json={"project_id": p, "title": "s"}
    )["id"]

    token = o.ok("POST", "/api/auth/agent-token", json={"project_id": p})["token"]
    token_q = o.ok("POST", "/api/auth/agent-token", json={"project_id": q})["token"]
    w = World(
        u=u,
        bearer=Client("bearer", token),
        bearer_q=Client("bearer_q", token_q),
        ids=ids,
    )
    yield w
    # built-in corpora are visible to every user: remove all the test made (also left over from earlier runs)
    admin = u["admin"]
    for c in admin.ok("GET", "/api/corpora", params={"page_size": 200})["items"]:
        if c["project_id"] is None and c["name"].startswith(("tmp-bi-", "P6 内置 ")):
            admin.delete(f"/api/corpora/{c['id']}")


def run_stat(client, scope):
    job = client.ok(
        "POST", "/api/stats/frequency", json={"scope": scope, "unit": "word", "top": 20}
    )
    job = wait_job(client, job["id"])
    assert job["state"] == "succeeded", job
    return job["result"]["stat_id"]


# ---- cases ----


@dataclass
class Case:
    group: str
    name: str
    expect: dict
    call: Callable  # (client, ctx, role) -> Response
    setup: Callable | None = (
        None  # (world, role) -> ctx, run as owner before each role's call
    )


def build_cases(w: World):
    i = w.ids
    o = w.u["owner"]
    p = i["project"]
    scope = {"corpus_id": i["corpus"]}
    doc_en, doc_zh = i["doc_en"], i["doc_zh"]
    sents = i["sentences"]
    ns = len(sents)
    victim_docs = iter(i["victim_docs"])
    idx = {r: n for n, r in enumerate(ROLES)}
    serial = iter(range(10**6))

    def fresh_corpus(_w, role):
        return o.ok(
            "POST",
            f"/api/projects/{p}/corpora",
            json={"name": f"tmp-{role}", "language": "en"},
        )

    def fresh_builtin(_w, role):
        return w.u["admin"].ok(
            "POST",
            "/api/corpora",
            json={"name": f"tmp-bi-{TAG}-{role}", "language": "en"},
        )

    def fresh_span(layer="layer_span"):
        counter = iter(range(1000))

        def make(_w, role):
            while True:  # 1-character spans walking through the sentences; skip ranges that exist
                n = next(counter)
                d, _s, a, b = sents[n % len(sents)]
                start = a + (n // len(sents)) % (b - a)
                r = o.post(
                    f"/api/layers/{i[layer]}/spans",
                    json={
                        "document_id": d,
                        "start_cp": start,
                        "end_cp": start + 1,
                        "label": i["span_label"],
                    },
                )
                if r.status_code != 409:
                    assert r.status_code == 200, r.text
                    return r.json()

        return make

    span_maker = fresh_span()

    def fresh_relation(_w, role):
        a, b = span_maker(_w, role), span_maker(_w, role)
        rel = o.ok(
            "POST",
            f"/api/layers/{i['layer_rel']}/relations",
            json={"from_span_id": a["id"], "to_span_id": b["id"], "label": rel_label()},
        )
        return {"a": a, "b": b, "rel": rel}

    def two_spans(_w, role):
        return {"a": span_maker(_w, role), "b": span_maker(_w, role)}

    rel_labels = []

    def rel_label():
        if not rel_labels:
            ls = o.ok(
                "GET", "/api/label-sets", params={"project_id": p, "page_size": 200}
            )["items"]
            labels = next(s for s in ls if s["id"] == i["ls_rel"])["labels"]
            rel_labels.append(labels[0]["id"])
        return rel_labels[0]

    def fresh_alignment(_w, role):
        n = idx[role]
        r = o.post(
            f"/api/layers/{i['layer_align']}/alignments",
            json={
                "src_document_id": doc_en,
                "src_sentence_index": n % ns,
                "tgt_document_id": doc_zh,
                "tgt_sentence_index": (n + 1) % i["nz"],
            },
        )
        if r.status_code == 409:  # pair exists: use any row of the layer
            rows = o.ok("GET", f"/api/layers/{i['layer_align']}/alignments")["items"]
            return next(a for row in rows for a in row.get("alignments", []))
        assert r.status_code == 200, r.text
        return r.json()

    def fresh(kind):
        def make(_w, role):
            if kind == "query":
                return o.ok(
                    "POST",
                    f"/api/projects/{p}/queries",
                    json={"name": role, "query": "language", "scope": scope},
                )
            if kind == "subcorpus":
                return o.ok(
                    "POST",
                    f"/api/projects/{p}/subcorpora",
                    json={"name": role, "corpus_id": i["corpus"], "filter": {}},
                )
            if kind == "evidence":
                return o.ok(
                    "POST",
                    f"/api/projects/{p}/evidence",
                    json={"kind": "text", "text": "x", "source": role},
                )
            if kind == "label_set":
                return o.ok(
                    "POST",
                    f"/api/projects/{p}/label-sets",
                    json={
                        "name": f"tmp-{role}",
                        "kind": "span",
                        "labels": [{"id": "x", "name": "x"}],
                    },
                )
            if kind == "layer":
                return o.ok(
                    "POST",
                    f"/api/projects/{p}/layers",
                    json={
                        "corpus_id": i["corpus"],
                        "kind": "span",
                        "name": f"tmp-{role}",
                        "label_set_id": i["ls_span"],
                        "preannotate": False,
                    },
                )
            if kind == "note":
                return o.ok(
                    "POST",
                    f"/api/projects/{p}/kb/documents",
                    json={"kind": "note", "title": f"tmp-{role}", "body": "x"},
                )
            if kind == "term":
                return o.ok(
                    "POST",
                    f"/api/projects/{p}/kb/terms",
                    json={"term": f"tmp-{TAG}-{role}-{next(serial)}"},
                )
            if kind == "stat":
                return {"id": run_stat(o, scope)}
            if kind == "session":
                return o.ok(
                    "POST", "/agent/sessions", json={"project_id": p, "title": role}
                )
            if kind == "member":
                o.ok(
                    "PUT",
                    f"/api/projects/{p}/members/{w.u['spare'].id}",
                    json={"role": "viewer"},
                )
                return {}
            if kind == "victim_doc":
                return {"id": next(victim_docs)}
            raise KeyError(kind)

        return make

    md = (FIX / "kb-sample.md").read_bytes()
    span_body = lambda role: {
        "document_id": sents[0][0],
        "start_cp": sents[0][2] + idx[role],
        "end_cp": sents[0][2] + idx[role] + 3,
        "label": i["span_label"],
    }
    s1 = sents[1] if len(sents) > 1 else sents[0]

    C = Case
    return [
        # projects and members
        C(
            "项目",
            "POST /projects",
            COOKIE,
            lambda c, x, r: c.post("/api/projects", json={"name": f"tmp-{TAG}-{r}"}),
        ),
        C(
            "项目",
            "GET /projects/{id}",
            READ,
            lambda c, x, r: c.get(f"/api/projects/{p}"),
        ),
        C(
            "项目",
            "GET /projects/{id}/members",
            READ,
            lambda c, x, r: c.get(f"/api/projects/{p}/members"),
        ),
        C(
            "项目",
            "PUT /members/{uid}",
            MANAGE_H,
            lambda c, x, r: c.put(
                f"/api/projects/{p}/members/{w.u['spare'].id}", json={"role": "viewer"}
            ),
        ),
        C(
            "项目",
            "DELETE /members/{uid}",
            MANAGE_H,
            lambda c, x, r: c.delete(f"/api/projects/{p}/members/{w.u['spare'].id}"),
            fresh("member"),
        ),
        C(
            "项目",
            "GET /users?email=",
            ANYONE,
            lambda c, x, r: c.get("/api/users", params={"email": o.email}),
        ),
        C(
            "项目",
            "POST /auth/agent-token",
            {**READ, "bearer": 403},
            lambda c, x, r: c.post("/api/auth/agent-token", json={"project_id": p}),
        ),
        # corpora and documents
        C(
            "语料",
            "GET /corpora?project_id",
            READ,
            lambda c, x, r: c.get("/api/corpora", params={"project_id": p}),
        ),
        C(
            "语料",
            "GET /corpora/{id}",
            READ,
            lambda c, x, r: c.get(f"/api/corpora/{i['corpus']}"),
        ),
        C(
            "语料",
            "GET /corpora/{id}/documents",
            READ,
            lambda c, x, r: c.get(f"/api/corpora/{i['corpus']}/documents"),
        ),
        C(
            "语料",
            "GET metadata-fields",
            READ,
            lambda c, x, r: c.get(f"/api/corpora/{i['corpus']}/metadata-fields"),
        ),
        C(
            "语料",
            "POST /projects/{id}/corpora",
            WRITE,
            lambda c, x, r: c.post(
                f"/api/projects/{p}/corpora",
                json={"name": f"tmp-{r}", "language": "en"},
            ),
        ),
        C(
            "语料",
            "POST /corpora/{id}/documents",
            WRITE_H,
            lambda c, x, r: upload(c, x["id"], txt(1)),
            fresh_corpus,
        ),
        C(
            "语料",
            "PATCH documents/{doc}",
            WRITE,
            lambda c, x, r: c.patch(
                f"/api/corpora/{i['victim']}/documents/{i['victim_docs'][-1]}",
                json={"title": f"t-{r}"},
            ),
        ),
        C(
            "语料",
            "DELETE documents/{doc}",
            WRITE_H,
            lambda c, x, r: c.delete(f"/api/corpora/{i['victim']}/documents/{x['id']}"),
            fresh("victim_doc"),
        ),
        C(
            "语料",
            "POST reindex",
            WRITE_H,
            lambda c, x, r: c.post(f"/api/corpora/{x['id']}/reindex"),
            fresh_corpus,
        ),
        C(
            "语料",
            "DELETE /corpora/{id}",
            WRITE_H,
            lambda c, x, r: c.delete(f"/api/corpora/{x['id']}"),
            fresh_corpus,
        ),
        # built-in corpora
        C(
            "内置",
            "POST /corpora",
            ADMIN,
            lambda c, x, r: c.post(
                "/api/corpora", json={"name": f"tmp-bi-{TAG}-{r}", "language": "en"}
            ),
        ),
        C(
            "内置",
            "GET /corpora/{builtin}",
            ANYONE,
            lambda c, x, r: c.get(f"/api/corpora/{i['builtin']}"),
        ),
        C(
            "内置",
            "POST builtin documents",
            ADMIN,
            lambda c, x, r: upload(c, x["id"], txt(1)),
            fresh_builtin,
        ),
        C(
            "内置",
            "DELETE /corpora/{builtin}",
            ADMIN,
            lambda c, x, r: c.delete(f"/api/corpora/{x['id']}"),
            fresh_builtin,
        ),
        # subcorpora
        C(
            "子库",
            "GET subcorpora",
            READ,
            lambda c, x, r: c.get(f"/api/projects/{p}/subcorpora"),
        ),
        C(
            "子库",
            "POST subcorpora",
            WRITE,
            lambda c, x, r: c.post(
                f"/api/projects/{p}/subcorpora",
                json={"name": f"s-{r}", "corpus_id": i["corpus"], "filter": {}},
            ),
        ),
        C(
            "子库",
            "GET /subcorpora/{id}",
            READ,
            lambda c, x, r: c.get(f"/api/subcorpora/{i['subcorpus']}"),
        ),
        C(
            "子库",
            "DELETE /subcorpora/{id}",
            WRITE_H,
            lambda c, x, r: c.delete(f"/api/subcorpora/{x['id']}"),
            fresh("subcorpus"),
        ),
        # search and saved queries
        C(
            "检索",
            "POST /search/parse",
            ANYONE,
            lambda c, x, r: c.post("/api/search/parse", json={"query": "language"}),
        ),
        C(
            "检索",
            "POST /search",
            READ,
            lambda c, x, r: c.post(
                "/api/search", json={"scope": scope, "query": "language"}
            ),
        ),
        C(
            "检索",
            "POST /search (subcorpus)",
            READ,
            lambda c, x, r: c.post(
                "/api/search",
                json={"scope": {"subcorpus_id": i["subcorpus"]}, "query": "language"},
            ),
        ),
        C(
            "检索",
            "GET /search/context",
            READ,
            lambda c, x, r: c.get(
                "/api/search/context",
                params={"document_id": doc_en, "sentence_index": 0},
            ),
        ),
        C(
            "检索",
            "POST /search/export",
            READ,
            lambda c, x, r: c.post(
                "/api/search/export",
                json={"scope": scope, "query": "language", "format": "csv"},
            ),
        ),
        C(
            "检索",
            "GET queries",
            READ,
            lambda c, x, r: c.get(f"/api/projects/{p}/queries"),
        ),
        C(
            "检索",
            "POST queries",
            WRITE,
            lambda c, x, r: c.post(
                f"/api/projects/{p}/queries",
                json={"name": r, "query": "language", "scope": scope},
            ),
        ),
        C(
            "检索",
            "DELETE /queries/{id}",
            WRITE_H,
            lambda c, x, r: c.delete(f"/api/queries/{x['id']}"),
            fresh("query"),
        ),
        # statistics
        C(
            "统计",
            "POST /stats/frequency",
            READ,
            lambda c, x, r: c.post(
                "/api/stats/frequency", json={"scope": scope, "unit": "word", "top": 5}
            ),
        ),
        C(
            "统计",
            "POST /stats/collocations",
            READ,
            lambda c, x, r: c.post(
                "/api/stats/collocations",
                json={"scope": scope, "node": "language", "min_freq": 1},
            ),
        ),
        C(
            "统计",
            "GET /stats/{id}",
            READ,
            lambda c, x, r: c.get(f"/api/stats/{i['stat']}"),
        ),
        C(
            "统计",
            "GET /projects/{id}/stats",
            READ,
            lambda c, x, r: c.get(f"/api/projects/{p}/stats"),
        ),
        C(
            "统计",
            "POST /stats/{id}/export",
            READ,
            lambda c, x, r: c.post(
                f"/api/stats/{i['stat']}/export", json={"format": "csv"}
            ),
        ),
        C(
            "统计",
            "DELETE /stats/{id}",
            WRITE_H,
            lambda c, x, r: c.delete(f"/api/stats/{x['id']}"),
            fresh("stat"),
        ),
        C(
            "统计",
            "POST /stats/alignment",
            READ,
            lambda c, x, r: c.post(
                "/api/stats/alignment", json={"layer_id": i["layer_align"]}
            ),
        ),
        # evidence
        C(
            "证据",
            "GET evidence",
            READ,
            lambda c, x, r: c.get(f"/api/projects/{p}/evidence"),
        ),
        C(
            "证据",
            "POST evidence",
            ANNOT,
            lambda c, x, r: c.post(
                f"/api/projects/{p}/evidence",
                json={"kind": "text", "text": "t", "source": r},
            ),
        ),
        C(
            "证据",
            "DELETE /evidence/{id}",
            WRITE_H,
            lambda c, x, r: c.delete(f"/api/evidence/{x['id']}"),
            fresh("evidence"),
        ),
        C(
            "证据",
            "POST evidence/export",
            READ,
            lambda c, x, r: c.post(
                f"/api/projects/{p}/evidence/export", json={"format": "csv"}
            ),
        ),
        # jobs
        C(
            "任务",
            "GET /projects/{id}/jobs",
            READ,
            lambda c, x, r: c.get(f"/api/projects/{p}/jobs"),
        ),
        C(
            "任务",
            "GET /jobs/{id}",
            READ,
            lambda c, x, r: c.get(f"/api/jobs/{i['export_job']}"),
        ),
        C(
            "任务",
            "GET /jobs/{id}/download",
            READ,
            lambda c, x, r: c.get(f"/api/jobs/{i['export_job']}/download"),
        ),
        C(
            "任务",
            "POST /jobs/{id}/cancel",
            WRITE,
            lambda c, x, r: c.post(f"/api/jobs/{i['export_job']}/cancel"),
        ),
        C(
            "任务",
            "POST /jobs/{id}/retry",
            WRITE,
            lambda c, x, r: c.post(f"/api/jobs/{i['export_job']}/retry"),
        ),
        C(
            "任务",
            "POST cancel (viewer's job)",
            JOB_OWN,
            lambda c, x, r: c.post(f"/api/jobs/{i['viewer_job']}/cancel"),
        ),
        C(
            "任务",
            "POST retry (viewer's job)",
            JOB_OWN,
            lambda c, x, r: c.post(f"/api/jobs/{i['viewer_job']}/retry"),
        ),
        C(
            "任务",
            "GET /jobs?builtin=1",
            ADMIN,
            lambda c, x, r: c.get("/api/jobs", params={"builtin": 1}),
        ),
        C(
            "任务",
            "GET /jobs (no builtin)",
            ADMIN_FLAG,
            lambda c, x, r: c.get("/api/jobs"),
        ),
        # label sets
        C(
            "标签集",
            "GET /label-sets",
            READ,
            lambda c, x, r: c.get("/api/label-sets", params={"project_id": p}),
        ),
        C(
            "标签集",
            "POST label-sets",
            WRITE_H,
            lambda c, x, r: c.post(
                f"/api/projects/{p}/label-sets",
                json={
                    "name": f"ls-{r}",
                    "kind": "span",
                    "labels": [{"id": "x", "name": "x"}],
                },
            ),
        ),
        C(
            "标签集",
            "PATCH /label-sets/{id}",
            WRITE_H,
            lambda c, x, r: c.patch(
                f"/api/label-sets/{x['id']}", json={"name": f"ls2-{r}"}
            ),
            fresh("label_set"),
        ),
        C(
            "标签集",
            "DELETE /label-sets/{id}",
            WRITE_H,
            lambda c, x, r: c.delete(f"/api/label-sets/{x['id']}"),
            fresh("label_set"),
        ),
        # layers and token annotation
        C(
            "标注层",
            "GET layers",
            READ,
            lambda c, x, r: c.get(f"/api/projects/{p}/layers"),
        ),
        C(
            "标注层",
            "POST layers",
            WRITE,
            lambda c, x, r: c.post(
                f"/api/projects/{p}/layers",
                json={
                    "corpus_id": i["corpus"],
                    "kind": "span",
                    "name": f"l-{r}",
                    "label_set_id": i["ls_span"],
                    "preannotate": False,
                },
            ),
        ),
        C(
            "标注层",
            "GET /layers/{id}",
            READ,
            lambda c, x, r: c.get(f"/api/layers/{i['layer_pos']}"),
        ),
        C(
            "标注层",
            "DELETE /layers/{id}",
            WRITE_H,
            lambda c, x, r: c.delete(f"/api/layers/{x['id']}"),
            fresh("layer"),
        ),
        C(
            "标注层",
            "POST preannotate",
            WRITE,
            lambda c, x, r: c.post(
                f"/api/layers/{i['layer_pos']}/preannotate", json={}
            ),
        ),
        C(
            "标注层",
            "GET documents",
            READ,
            lambda c, x, r: c.get(f"/api/layers/{i['layer_pos']}/documents"),
        ),
        C(
            "标注层",
            "GET sentences",
            READ,
            lambda c, x, r: c.get(f"/api/layers/{i['layer_pos']}/sentences"),
        ),
        C(
            "标注层",
            "GET sentence",
            READ,
            lambda c, x, r: c.get(f"/api/layers/{i['layer_pos']}/sentences/{doc_en}/0"),
        ),
        C(
            "标注层",
            "POST annotations",
            CREATOR_H,
            lambda c, x, r: c.post(
                f"/api/layers/{i['layer_pos']}/annotations",
                json={
                    "document_id": doc_en,
                    "sentence_index": 0,
                    "token_index": 1,
                    "action": "confirm",
                },
            ),
        ),
        C(
            "标注层",
            "POST sentence confirm",
            CREATOR_H,
            lambda c, x, r: c.post(
                f"/api/layers/{i['layer_pos']}/sentences/{doc_en}/0/confirm", json={}
            ),
        ),
        C(
            "标注层",
            "POST sentence reset",
            CREATOR_H,
            lambda c, x, r: c.post(
                f"/api/layers/{i['layer_pos']}/sentences/{doc_en}/0/reset", json={}
            ),
        ),
        C(
            "标注层",
            "GET diff",
            READ,
            lambda c, x, r: c.get(f"/api/layers/{i['layer_pos']}/diff"),
        ),
        C(
            "标注层",
            "GET stats",
            READ,
            lambda c, x, r: c.get(f"/api/layers/{i['layer_pos']}/stats"),
        ),
        C(
            "标注层",
            "POST export",
            READ,
            lambda c, x, r: c.post(
                f"/api/layers/{i['layer_pos']}/export", json={"format": "conllu"}
            ),
        ),
        C(
            "标注层",
            "POST suggest",
            CREATOR,
            lambda c, x, r: c.post(
                f"/api/layers/{i['layer_pos']}/suggest",
                json={
                    "document_id": doc_en,
                    "sentence_index": 1,
                    "token_index": 1,
                    "label": "NOUN",
                },
            ),
        ),
        # spans and relations
        C(
            "片段",
            "GET spans",
            READ,
            lambda c, x, r: c.get(f"/api/layers/{i['layer_span']}/spans"),
        ),
        C(
            "片段",
            "POST spans",
            CREATOR_H,
            lambda c, x, r: c.post(
                f"/api/layers/{i['layer_span']}/spans", json=span_body(r)
            ),
        ),
        C(
            "片段",
            "PATCH spans/{id}",
            CREATOR_H,
            lambda c, x, r: c.patch(
                f"/api/layers/{i['layer_span']}/spans/{x['id']}",
                json={"action": "confirm"},
            ),
            span_maker,
        ),
        C(
            "片段",
            "DELETE spans/{id}",
            CREATOR_H,
            lambda c, x, r: c.delete(f"/api/layers/{i['layer_span']}/spans/{x['id']}"),
            span_maker,
        ),
        C(
            "片段",
            "POST relations",
            CREATOR_H,
            lambda c, x, r: c.post(
                f"/api/layers/{i['layer_rel']}/relations",
                json={
                    "from_span_id": x["a"]["id"],
                    "to_span_id": x["b"]["id"],
                    "label": rel_label(),
                },
            ),
            two_spans,
        ),
        C(
            "片段",
            "PATCH relations/{id}",
            CREATOR_H,
            lambda c, x, r: c.patch(
                f"/api/layers/{i['layer_rel']}/relations/{x['rel']['id']}",
                json={"action": "confirm"},
            ),
            fresh_relation,
        ),
        C(
            "片段",
            "DELETE relations/{id}",
            CREATOR_H,
            lambda c, x, r: c.delete(
                f"/api/layers/{i['layer_rel']}/relations/{x['rel']['id']}"
            ),
            fresh_relation,
        ),
        C(
            "片段",
            "POST spans/suggest",
            CREATOR,
            lambda c, x, r: c.post(
                f"/api/layers/{i['layer_span']}/spans/suggest",
                json={
                    "document_id": s1[0],
                    "sentence_index": s1[1],
                    "spans": [
                        {
                            "start_cp": s1[2],
                            "end_cp": s1[2] + 2 + idx[r],
                            "label": i["span_label"],
                        }
                    ],
                },
            ),
        ),
        # alignments
        C(
            "对齐",
            "GET alignments",
            READ,
            lambda c, x, r: c.get(f"/api/layers/{i['layer_align']}/alignments"),
        ),
        C(
            "对齐",
            "POST alignments",
            CREATOR_H,
            lambda c, x, r: c.post(
                f"/api/layers/{i['layer_align']}/alignments",
                json={
                    "src_document_id": doc_en,
                    "src_sentence_index": idx[r] % ns,
                    "tgt_document_id": doc_zh,
                    "tgt_sentence_index": (idx[r] + 2) % i["nz"],
                },
            ),
        ),
        C(
            "对齐",
            "PATCH alignments/{id}",
            CREATOR_H,
            lambda c, x, r: c.patch(
                f"/api/layers/{i['layer_align']}/alignments/{x['id']}",
                json={"action": "confirm"},
            ),
            fresh_alignment,
        ),
        C(
            "对齐",
            "POST alignments/suggest",
            CREATOR,
            lambda c, x, r: c.post(
                f"/api/layers/{i['layer_align_word']}/alignments/suggest",
                json={
                    "src_document_id": doc_en,
                    "src_sentence_index": 0,
                    "tgt_document_id": doc_zh,
                    "tgt_sentence_index": 0,
                    "links": [{"src": [1], "tgt": [1]}],
                },
            ),
        ),
        # agreement and adjudication
        C(
            "仲裁",
            "GET agreement",
            READ,
            lambda c, x, r: c.get(f"/api/layers/{i['layer_multi']}/agreement"),
        ),
        C(
            "仲裁",
            "GET disagreements",
            WRITE,
            lambda c, x, r: c.get(f"/api/layers/{i['layer_multi']}/disagreements"),
        ),
        C(
            "仲裁",
            "POST adjudicate",
            WRITE_H,
            lambda c, x, r: c.post(
                f"/api/layers/{i['layer_multi']}/adjudicate",
                json={
                    "target_kind": "span",
                    "target_key": f"{doc_en}:{sents[0][2]}-{sents[0][2] + 3}",
                    "final": {"label": None},
                },
            ),
        ),
        # knowledge base documents and notes
        C(
            "知识库",
            "GET kb/documents",
            READ,
            lambda c, x, r: c.get(f"/api/projects/{p}/kb/documents"),
        ),
        C(
            "知识库",
            "POST note",
            EDIT,
            lambda c, x, r: c.post(
                f"/api/projects/{p}/kb/documents",
                json={"kind": "note", "title": r, "body": "x"},
            ),
        ),
        C(
            "知识库",
            "POST guideline",
            EDIT_C,
            lambda c, x, r: c.post(
                f"/api/projects/{p}/kb/documents",
                json={"kind": "guideline", "title": r, "body": "x"},
            ),
        ),
        C(
            "知识库",
            "POST upload",
            EDIT_C,
            lambda c, x, r: c.post(
                f"/api/projects/{p}/kb/documents",
                files=[("files", (f"{r}.md", md, "text/markdown"))],
            ),
        ),
        C(
            "知识库",
            "GET /kb/documents/{id}",
            READ,
            lambda c, x, r: c.get(f"/api/kb/documents/{i['note']}"),
        ),
        C(
            "知识库",
            "PATCH note",
            EDIT,
            lambda c, x, r: c.patch(
                f"/api/kb/documents/{i['note']}", json={"title": r}
            ),
        ),
        C(
            "知识库",
            "DELETE /kb/documents/{id}",
            DELETE_C,
            lambda c, x, r: c.delete(f"/api/kb/documents/{x['id']}"),
            fresh("note"),
        ),
        C(
            "知识库",
            "POST reimport",
            EDIT_C,
            lambda c, x, r: c.post(f"/api/kb/documents/{x['id']}/reimport"),
            fresh("note"),
        ),
        C(
            "知识库",
            "GET chunks",
            READ,
            lambda c, x, r: c.get(f"/api/kb/documents/{i['note']}/chunks"),
        ),
        C(
            "知识库",
            "POST summarize",
            EDIT,
            lambda c, x, r: c.post(f"/api/kb/documents/{i['note']}/summarize"),
        ),
        C(
            "知识库",
            "POST refs",
            EDIT,
            lambda c, x, r: c.post(
                f"/api/kb/documents/{i['note']}/refs",
                json={"kind": "evidence", "ref": {"evidence_id": i["evidence"]}},
            ),
        ),
        C(
            "知识库",
            "POST note export",
            READ,
            lambda c, x, r: c.post(
                f"/api/kb/documents/{i['note']}/export", json={"format": "md"}
            ),
        ),
        C(
            "知识库",
            "POST kb/search",
            READ,
            lambda c, x, r: c.post(
                f"/api/projects/{p}/kb/search",
                json={"q": "language", "mode": "keyword"},
            ),
        ),
        # terms
        C(
            "术语",
            "GET terms",
            READ,
            lambda c, x, r: c.get(f"/api/projects/{p}/kb/terms"),
        ),
        C(
            "术语",
            "POST terms (draft)",
            EDIT,
            lambda c, x, r: c.post(
                f"/api/projects/{p}/kb/terms", json={"term": f"t-{TAG}-{r}"}
            ),
        ),
        C(
            "术语",
            "GET /kb/terms/{id}",
            READ,
            lambda c, x, r: c.get(f"/api/kb/terms/{i['term']}"),
        ),
        C(
            "术语",
            "PATCH /kb/terms/{id}",
            EDIT_C,
            lambda c, x, r: c.patch(
                f"/api/kb/terms/{i['term']}", json={"definition": r}
            ),
        ),
        C(
            "术语",
            "DELETE /kb/terms/{id}",
            DELETE_C,
            lambda c, x, r: c.delete(f"/api/kb/terms/{x['id']}"),
            fresh("term"),
        ),
        C(
            "术语",
            "POST examples",
            EDIT_C,
            lambda c, x, r: c.post(
                f"/api/kb/terms/{x['id']}/examples",
                json={"text": "language", "source": r},
            ),
            fresh("term"),
        ),
        C(
            "术语",
            "POST terms/extract",
            EDIT,
            lambda c, x, r: c.post(
                f"/api/projects/{p}/kb/terms/extract",
                json={"source": "corpus", "scope": scope},
            ),
        ),
        C(
            "术语",
            "POST terms/export",
            READ,
            lambda c, x, r: c.post(
                f"/api/projects/{p}/kb/terms/export", json={"format": "csv"}
            ),
        ),
        # agent sessions (cookie only; owner-private)
        C(
            "会话",
            "GET /agent/sessions",
            AGENT_LIST,
            lambda c, x, r: c.get("/agent/sessions", params={"project_id": p}),
        ),
        C(
            "会话",
            "POST /agent/sessions",
            AGENT_LIST,
            lambda c, x, r: c.post(
                "/agent/sessions", json={"project_id": p, "title": r}
            ),
        ),
        C(
            "会话",
            "GET /agent/sessions/{id}",
            AGENT_OWN,
            lambda c, x, r: c.get(f"/agent/sessions/{i['session']}"),
        ),
        C(
            "会话",
            "PATCH /agent/sessions/{id}",
            AGENT_OWN,
            lambda c, x, r: c.patch(
                f"/agent/sessions/{i['session']}", json={"title": r}
            ),
        ),
        C(
            "会话",
            "DELETE /agent/sessions/{id}",
            AGENT_OWN,
            lambda c, x, r: c.delete(f"/agent/sessions/{x['id']}"),
            fresh("session"),
        ),
    ]


def matches(expected, status):
    if expected == OK:
        return (
            status < 400 or status == 409
        )  # 409: business conflict, not a permission denial
    return status == expected


def show(expected):
    return "✓" if expected == OK else str(expected)


def test_permission_matrix(world):
    w = world
    clients = {r: w.u[r] for r in ROLES if r != "bearer"} | {"bearer": w.bearer}
    rows, failures, five = [], [], []
    for case in build_cases(w):
        cells = []
        for role in ROLES:
            ctx = case.setup(w, role) if case.setup else None
            r = case.call(clients[role], ctx, role)
            want = case.expect[role]
            good = matches(want, r.status_code)
            cells.append(f"{r.status_code}{'' if good else '!'}")
            if r.status_code >= 500:
                five.append((case.name, role, r.status_code, r.text[:200]))
            if not good:
                failures.append(
                    (
                        case.group,
                        case.name,
                        role,
                        show(want),
                        r.status_code,
                        r.text[:200],
                    )
                )
        rows.append((case.group, case.name, cells))

    head = f"{'组':<6}{'接口':<34}" + "".join(f"{SHORT[r]:>6}" for r in ROLES)
    print("\n权限矩阵（实际状态码；! 表示与预期不符；409 视为允许后的业务冲突）")
    print(head)
    for group, name, cells in rows:
        print(f"{group:<6}{name:<34}" + "".join(f"{c:>6}" for c in cells))
    total = len(rows) * len(ROLES)
    print(
        f"\n用例 {len(rows)} 个接口 × {len(ROLES)} 角色 = {total} 次；不符 {len(failures)}；5xx {len(five)}"
    )
    for f in failures:
        print("不符：", f)
    assert not five, five
    assert not failures, failures


def test_bearer_other_project(world):
    """A token of project Q cannot touch project P (403), but works inside Q."""
    w, i = world, world.ids
    b = w.bearer_q
    assert b.get(f"/api/projects/{i['other_project']}").status_code == 200
    for method, path, body in [
        ("GET", f"/api/projects/{i['project']}", None),
        ("GET", f"/api/corpora/{i['corpus']}", None),
        (
            "POST",
            "/api/search",
            {"scope": {"corpus_id": i["corpus"]}, "query": "language"},
        ),
        ("GET", f"/api/layers/{i['layer_span']}", None),
        ("GET", f"/api/kb/documents/{i['note']}", None),
        ("GET", f"/api/jobs/{i['export_job']}", None),
        (
            "POST",
            f"/api/projects/{i['project']}/evidence",
            {"kind": "text", "text": "x", "source": "y"},
        ),
    ]:
        r = b.req(method, path, json=body)
        assert r.status_code == 403, (path, r.status_code, r.text)
    projects = b.ok("GET", "/api/projects")["items"]
    assert [x["id"] for x in projects] == [i["other_project"]]
    # admin's own token still cannot create a built-in corpus
    admin = w.u["admin"]
    ap = admin.ok("POST", "/api/projects", json={"name": f"tmp-admin-{TAG}"})["id"]
    at = Client(
        "admin-bearer",
        admin.ok("POST", "/api/auth/agent-token", json={"project_id": ap})["token"],
    )
    assert (
        at.post("/api/corpora", json={"name": "x", "language": "en"}).status_code == 403
    )


def test_revocation(world):
    """Removing a member: cookie, agent token, own jobs and agent sessions stop working on the next request."""
    w, i = world, world.ids
    o, leaver, p = w.u["owner"], w.u["leaver"], i["project"]
    token = Client(
        "leaver-bearer",
        leaver.ok("POST", "/api/auth/agent-token", json={"project_id": p})["token"],
    )
    session = leaver.ok(
        "POST", "/agent/sessions", json={"project_id": p, "title": "leaver"}
    )["id"]
    export = leaver.ok(
        "POST",
        "/api/search/export",
        json={
            "scope": {"corpus_id": i["corpus"]},
            "query": "language",
            "format": "csv",
        },
    )
    assert wait_job(leaver, export["id"])["state"] == "succeeded"
    probes = [
        ("cookie GET project", leaver, "GET", f"/api/projects/{p}", None),
        (
            "cookie search",
            leaver,
            "POST",
            "/api/search",
            {"scope": {"corpus_id": i["corpus"]}, "query": "language"},
        ),
        (
            "cookie create corpus",
            leaver,
            "POST",
            f"/api/projects/{p}/corpora",
            {"name": "x", "language": "en"},
        ),
        ("cookie own job", leaver, "GET", f"/api/jobs/{export['id']}", None),
        (
            "cookie own job download",
            leaver,
            "GET",
            f"/api/jobs/{export['id']}/download",
            None,
        ),
        ("cookie agent session", leaver, "GET", f"/agent/sessions/{session}", None),
        (
            "cookie agent session list",
            leaver,
            "GET",
            f"/agent/sessions?project_id={p}",
            None,
        ),
        (
            "cookie agent-token",
            leaver,
            "POST",
            "/api/auth/agent-token",
            {"project_id": p},
        ),
        ("bearer GET project", token, "GET", f"/api/projects/{p}", None),
        (
            "bearer search",
            token,
            "POST",
            "/api/search",
            {"scope": {"corpus_id": i["corpus"]}, "query": "language"},
        ),
        (
            "bearer kb note",
            token,
            "POST",
            f"/api/projects/{p}/kb/documents",
            {"kind": "note", "title": "x", "body": ""},
        ),
        ("bearer own job", token, "GET", f"/api/jobs/{export['id']}", None),
    ]
    before = {
        name: c.req(m, path, json=body).status_code for name, c, m, path, body in probes
    }
    assert all(s < 400 for n, s in before.items() if n != "cookie create corpus"), (
        before
    )

    # downgrade editor → viewer applies on the next request
    o.ok("PUT", f"/api/projects/{p}/members/{leaver.id}", json={"role": "viewer"})
    assert (
        leaver.post(
            f"/api/projects/{p}/corpora", json={"name": "y", "language": "en"}
        ).status_code
        == 403
    )
    assert (
        token.post(
            f"/api/projects/{p}/subcorpora",
            json={"name": "y", "corpus_id": i["corpus"], "filter": {}},
        ).status_code
        == 403
    )

    o.ok("DELETE", f"/api/projects/{p}/members/{leaver.id}")
    after = {
        name: c.req(m, path, json=body).status_code for name, c, m, path, body in probes
    }
    print("\n撤销前后（成员移除后下一次请求）")
    for name, *_ in probes:
        print(f"  {name:<28}{before[name]:>5} → {after[name]}")
    assert all(s in (401, 403, 404) for s in after.values()), after


def test_corpus_deletion(world):
    """Deleting a corpus: references answer clean 404 / 409 or keep their own copy, never 5xx."""
    w, i = world, world.ids
    o, p, d = w.u["owner"], i["project"], i["doomed"]
    scope = {"corpus_id": d}
    docs = o.ok("GET", f"/api/corpora/{d}/documents")["items"]
    doc = docs[0]["id"]
    sub = o.ok(
        "POST",
        f"/api/projects/{p}/subcorpora",
        json={"name": "doomed", "corpus_id": d, "filter": {}},
    )["id"]
    query = o.ok(
        "POST",
        f"/api/projects/{p}/queries",
        json={"name": "doomed", "query": "language", "scope": scope},
    )["id"]
    stat = run_stat(o, scope)
    layer = o.ok(
        "POST",
        f"/api/projects/{p}/layers",
        json={
            "corpus_id": d,
            "kind": "span",
            "name": "doomed",
            "label_set_id": i["ls_span"],
            "preannotate": False,
        },
    )["id"]
    hit = o.ok("POST", "/api/search", json={"scope": scope, "query": "language"})[
        "items"
    ][0]
    ev = o.ok(
        "POST",
        f"/api/projects/{p}/evidence",
        json={
            "kind": "hit",
            "text": hit["match"],
            "source": "doomed",
            "ref": {
                "search_query": "language",
                "scope": scope,
                "hit_id": hit["hit_id"],
                "document_id": hit["document_id"],
                "start_cp": hit["start_cp"],
                "end_cp": hit["end_cp"],
            },
        },
    )["id"]
    note = o.ok(
        "POST",
        f"/api/projects/{p}/kb/documents",
        json={"kind": "note", "title": "doomed", "body": ""},
    )["id"]
    o.ok(
        "POST",
        f"/api/kb/documents/{note}/refs",
        json={"kind": "evidence", "ref": {"evidence_id": ev}},
    )
    o.ok(
        "POST",
        f"/api/kb/documents/{note}/refs",
        json={"kind": "stat", "ref": {"stat_id": stat}},
    )
    term = o.ok(
        "POST",
        f"/api/projects/{p}/kb/terms",
        json={
            "term": f"doomed-{TAG}",
            "examples": [
                {
                    "text": hit["match"],
                    "source": "doomed",
                    "document_id": hit["document_id"],
                }
            ],
        },
    )["id"]
    session = o.ok("POST", "/agent/sessions", json={"project_id": p, "scope": scope})[
        "id"
    ]

    o.ok("DELETE", f"/api/corpora/{d}")
    probes = [
        (
            "search corpus",
            "POST",
            "/api/search",
            {"scope": scope, "query": "language"},
            (404,),
        ),
        (
            "search subcorpus",
            "POST",
            "/api/search",
            {"scope": {"subcorpus_id": sub}, "query": "language"},
            (404,),
        ),
        (
            "context",
            "GET",
            f"/api/search/context?document_id={doc}&sentence_index=0",
            None,
            (404,),
        ),
        ("GET corpus", "GET", f"/api/corpora/{d}", None, (404,)),
        ("GET subcorpus", "GET", f"/api/subcorpora/{sub}", None, (404,)),
        ("saved queries list", "GET", f"/api/projects/{p}/queries", None, (200,)),
        ("delete saved query", "DELETE", f"/api/queries/{query}", None, (204, 404)),
        ("stats frequency", "POST", "/api/stats/frequency", {"scope": scope}, (404,)),
        ("GET stat", "GET", f"/api/stats/{stat}", None, (200, 404)),
        (
            "export stat",
            "POST",
            f"/api/stats/{stat}/export",
            {"format": "csv"},
            (200, 404, 409),
        ),
        ("GET layer", "GET", f"/api/layers/{layer}", None, (404,)),
        ("layer spans", "GET", f"/api/layers/{layer}/spans", None, (404,)),
        ("project layers", "GET", f"/api/projects/{p}/layers", None, (200,)),
        ("evidence list", "GET", f"/api/projects/{p}/evidence", None, (200,)),
        (
            "evidence export",
            "POST",
            f"/api/projects/{p}/evidence/export",
            {"format": "csv"},
            (200,),
        ),
        ("GET note", "GET", f"/api/kb/documents/{note}", None, (200,)),
        (
            "note export",
            "POST",
            f"/api/kb/documents/{note}/export",
            {"format": "md"},
            (200,),
        ),
        (
            "note ref evidence",
            "POST",
            f"/api/kb/documents/{note}/refs",
            {"kind": "evidence", "ref": {"evidence_id": ev}},
            (200,),
        ),
        ("GET term", "GET", f"/api/kb/terms/{term}", None, (200,)),
        (
            "terms extract",
            "POST",
            f"/api/projects/{p}/kb/terms/extract",
            {"source": "corpus", "scope": scope},
            (404,),
        ),
        ("agent session", "GET", f"/agent/sessions/{session}", None, (200,)),
    ]
    results, bad = [], []
    jobs = []
    for name, m, path, body, allowed in probes:
        r = o.req(m, path, json=body)
        results.append((name, r.status_code))
        if r.status_code not in allowed:
            bad.append((name, r.status_code, r.text[:200]))
        if r.status_code == 200 and "export" in name:
            jobs.append((name, r.json()["id"]))
    for name, job_id in jobs:
        job = wait_job(o, job_id)
        results.append((f"{name} job", job["state"]))
        if job["state"] != "succeeded":
            bad.append((f"{name} job", job["state"], job.get("error")))
    print("\n删除语料后")
    for name, s in results:
        print(f"  {name:<24}{s}")
    assert not bad, bad


def test_project_cascade(world):
    """No DELETE /projects endpoint exists; check the schema cascades and that deleting the row leaves no orphans."""
    w = world
    o = w.u["owner"]
    pid = o.ok("POST", "/api/projects", json={"name": f"P6 级联 {TAG}"})["id"]
    c = make_corpus(o, pid, "级联", txt(1))
    wait_corpus(o, c["id"])
    o.ok(
        "POST",
        f"/api/projects/{pid}/evidence",
        json={"kind": "text", "text": "x", "source": "y"},
    )
    o.ok(
        "POST",
        f"/api/projects/{pid}/kb/documents",
        json={"kind": "note", "title": "n", "body": "x"},
    )
    o.ok("POST", f"/api/projects/{pid}/kb/terms", json={"term": f"cascade-{TAG}"})
    o.ok("POST", "/agent/sessions", json={"project_id": pid})
    sql = f"""
    SELECT tc.table_name, kcu.column_name, rc.delete_rule
    FROM information_schema.referential_constraints rc
    JOIN information_schema.table_constraints tc ON tc.constraint_name = rc.constraint_name
    JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = rc.constraint_name
    JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = rc.unique_constraint_name
    WHERE ccu.table_name = 'projects' ORDER BY 1;
    DELETE FROM projects WHERE id = '{pid}';
    SELECT 'corpora', count(*) FROM corpora WHERE project_id = '{pid}'
    UNION ALL SELECT 'jobs', count(*) FROM jobs WHERE project_id = '{pid}'
    UNION ALL SELECT 'evidence', count(*) FROM evidence WHERE project_id = '{pid}'
    UNION ALL SELECT 'kb_documents', count(*) FROM kb_documents WHERE project_id = '{pid}'
    UNION ALL SELECT 'kb_terms', count(*) FROM kb_terms WHERE project_id = '{pid}'
    UNION ALL SELECT 'agent_sessions', count(*) FROM agent_sessions WHERE project_id = '{pid}'
    UNION ALL SELECT 'documents', count(*) FROM documents WHERE corpus_id = '{c["id"]}';
    """
    out = subprocess.run(
        [
            *COMPOSE,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "corpus",
            "-d",
            "corpus",
            "-At",
            "-F",
            "|",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input=sql,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    lines = [x for x in out.stdout.splitlines() if "|" in x]
    rules = [x.split("|") for x in lines if len(x.split("|")) == 3]
    counts = {
        x.split("|")[0]: int(x.split("|")[1]) for x in lines if len(x.split("|")) == 2
    }
    print("\n引用 projects 的外键")
    for table, col, rule in rules:
        print(f"  {table}.{col}: {rule}")
    print("删除项目后残留行", counts)
    not_cascade = [r for r in rules if r[2] not in ("CASCADE", "SET NULL")]
    assert not not_cascade, not_cascade
    assert all(v == 0 for v in counts.values()), counts
    assert o.get(f"/api/projects/{pid}").status_code == 404
    assert o.get(f"/api/corpora/{c['id']}").status_code == 404
