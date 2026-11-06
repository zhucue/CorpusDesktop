"""P9 multi-group operations (contracts/p9.md): model usage and quota, admin views, audit log, project soft
delete / restore / purge, feedback, export expiry and automatic index rebuilds."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from tests.api.conftest import ORIGIN, PASSWORD, drain, upload

TEXT = "Language is a system.\nStudents learn a language.\n"


def bearer(client, project_id):
    from services.api.main import app

    token = client.post(
        "/api/auth/agent-token", json={"project_id": project_id}
    ).json()["token"]
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def anonymous():
    from services.api.main import app

    return TestClient(app, headers={"Origin": ORIGIN})


@pytest.fixture
def admin(make_user):
    return make_user("root@example.edu", admin=True)


@pytest.fixture
def corpus(owner, project):
    c = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "作文", "language": "en"},
    ).json()
    # two different texts: an identical second file would be skipped as a duplicate (P10)
    upload(owner, c["id"], {"a.txt": TEXT, "b.txt": TEXT + " Again."})
    drain()
    return owner.get(f"/api/corpora/{c['id']}").json()


def usage_row(user_id, project_id=None, source="agent", prompt=60, completion=40, **kw):
    from services.api.db import transaction
    from services.api.models import LlmUsage

    with transaction() as db:
        db.add(
            LlmUsage(
                user_id=user_id,
                project_id=project_id,
                source=source,
                model="fake-chat",
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=prompt + completion,
                **kw,
            )
        )


def audit_actions(**where):
    from services.api.db import transaction
    from services.api.models import AuditLog

    with transaction() as db:
        stmt = select(AuditLog).order_by(AuditLog.id)
        for k, v in where.items():
            stmt = stmt.where(getattr(AuditLog, k) == v)
        return [(a.action, a.target_name, a.actor_email) for a in db.scalars(stmt)]


def note(client, project_id, ready=True):
    doc = client.post(
        f"/api/projects/{project_id}/kb/documents",
        json={"kind": "note", "title": "笔记", "body": "language 研究"},
    ).json()
    if ready:  # as after kb_import, without running the embedder
        from services.api.db import transaction
        from services.api.models import KbDocument

        with transaction() as db:
            db.get(KbDocument, uuid.UUID(doc["id"])).chunk_count = 1
    return doc


def label_set_id(client, name):
    return next(
        s for s in client.get("/api/label-sets").json()["items"] if s["name"] == name
    )["id"]


# ---- usage and quota ----


def test_usage_and_quota(owner, project, corpus, make_user, admin, monkeypatch):
    other = make_user("other@example.edu")
    pid = project["id"]
    usage_row(owner.user_id, pid, "agent", session_id="s1")
    usage_row(owner.user_id, pid, "agent:estimated", prompt=10, completion=0)
    usage_row(owner.user_id, pid, "preannotate", prompt=200, completion=100)
    usage_row(other.user_id, None, "kb_summarize", prompt=5, completion=5)
    last_month = datetime.now(UTC) - timedelta(days=40)
    usage_row(
        owner.user_id, pid, "agent", prompt=1000, completion=0, created_at=last_month
    )

    r = owner.get("/api/me/llm-usage").json()
    assert r["month"] == datetime.now().astimezone().strftime("%Y-%m")
    assert r["total_tokens"] == 410 and r["limit"] is None
    assert r["by_source"] == [
        {"source": "preannotate", "total_tokens": 300},
        {"source": "agent", "total_tokens": 110},
    ]

    assert owner.get("/api/admin/llm-usage").status_code == 403
    assert (
        bearer(admin, admin.post("/api/projects", json={"name": "a"}).json()["id"])
        .get("/api/admin/llm-usage")
        .status_code
        == 403
    )
    by_user = admin.get("/api/admin/llm-usage").json()
    assert by_user["total"] == 2 and by_user["total_tokens"] == 420
    first = by_user["items"][0]
    assert first == {
        "key": owner.user_id,
        "name": "owner@example.edu",
        "total_tokens": 410,
        "prompt_tokens": 270,
        "completion_tokens": 140,
        "calls": 3,
    }
    by_project = admin.get("/api/admin/llm-usage", params={"group": "project"}).json()
    assert [(x["key"], x["name"], x["total_tokens"]) for x in by_project["items"]] == [
        (pid, project["name"], 410),
        (None, None, 10),
    ]
    old = admin.get(
        "/api/admin/llm-usage",
        params={"month": last_month.astimezone().strftime("%Y-%m")},
    ).json()
    assert old["total_tokens"] >= 1000
    assert (
        admin.get("/api/admin/llm-usage", params={"month": "2026-13"}).status_code
        == 422
    )

    # quota: owner is at 410 tokens this month
    monkeypatch.setenv("LLM_MONTHLY_TOKENS_PER_USER", "400")
    assert owner.get("/api/me/llm-usage").json()["limit"] == 400
    span = label_set_id(owner, "learner-errors")
    layer = {
        "corpus_id": corpus["id"],
        "kind": "span",
        "name": "偏误",
        "label_set_id": span,
    }
    r = owner.post(f"/api/projects/{pid}/layers", json={**layer, "preannotate": True})
    assert r.status_code == 429
    assert r.json()["error"] == {
        "code": "LLM_QUOTA_EXCEEDED",
        "message": "本月模型用量已达上限（400 token），请联系管理员",
    }
    assert (
        owner.get(f"/api/projects/{pid}/layers").json()["total"] == 0
    )  # nothing created
    created = owner.post(
        f"/api/projects/{pid}/layers", json={**layer, "preannotate": False}
    )
    assert created.status_code == 200
    r = owner.post(f"/api/layers/{created.json()['id']}/preannotate", json={})
    assert r.json()["error"]["code"] == "LLM_QUOTA_EXCEEDED"
    # POS pre-annotation needs no chat model
    pos = owner.post(
        f"/api/projects/{pid}/layers",
        json={
            "corpus_id": corpus["id"],
            "kind": "pos",
            "name": "词性",
            "label_set_id": label_set_id(owner, "upos"),
        },
    )
    assert pos.status_code == 200, pos.text
    doc = note(owner, pid)
    r = owner.post(f"/api/kb/documents/{doc['id']}/summarize")
    assert r.status_code == 429
    r = owner.post(
        f"/api/projects/{pid}/kb/terms/extract",
        json={"source": "literature", "document_ids": [doc["id"]], "method": "model"},
    )
    assert r.status_code == 429
    scope = {"corpus_id": corpus["id"]}
    r = owner.post(
        f"/api/projects/{pid}/kb/terms/extract",
        json={"source": "corpus", "scope": scope, "method": "model"},
    )
    assert r.status_code == 429
    r = owner.post(
        f"/api/projects/{pid}/kb/terms/extract",
        json={"source": "corpus", "scope": {"corpus_id": corpus["id"]}},
    )
    assert r.status_code == 200, r.text  # POS patterns: no model
    # other users are below the limit
    owner.put(f"/api/projects/{pid}/members/{other.user_id}", json={"role": "editor"})
    assert other.post(f"/api/kb/documents/{doc['id']}/summarize").status_code == 200

    # retrying a failed model job counts as starting it
    from services.api.db import transaction
    from services.api.models import Job

    with transaction() as db:
        db.execute(
            update(Job)
            .where(Job.kind == "kb_summarize")
            .values(state="failed", finished_at=func.now())
        )
        job_id = db.scalar(select(Job.id).where(Job.kind == "kb_summarize"))
    assert owner.post(f"/api/jobs/{job_id}/retry").status_code == 429
    monkeypatch.setenv("LLM_MONTHLY_TOKENS_PER_USER", "0")
    assert owner.post(f"/api/jobs/{job_id}/retry").status_code == 200


# ---- audit ----


def test_audit_entries(owner, project, corpus, member, admin, make_user):
    pid = project["id"]
    c = anonymous()
    assert (
        c.post(
            "/api/auth/login", json={"email": "owner@example.edu", "password": "wrong"}
        ).status_code
        == 401
    )
    created = admin.post(
        "/api/admin/users", json={"email": "temp@example.edu", "display_name": "临时"}
    ).json()["user"]
    tid = created["id"]
    admin.post(f"/api/admin/users/{tid}/reset-password")
    admin.post(f"/api/admin/users/{tid}/admin", json={"is_admin": True})
    admin.post(f"/api/admin/users/{tid}/admin", json={"is_admin": False})
    admin.post(f"/api/admin/users/{tid}/disable")
    admin.post(f"/api/admin/users/{tid}/enable")
    r = owner.post(
        "/api/auth/password",
        json={"old_password": PASSWORD, "new_password": "another long passphrase"},
    )
    assert r.status_code == 200, r.text

    editor = member("editor")
    owner.put(f"/api/projects/{pid}/members/{editor.user_id}", json={"role": "viewer"})
    owner.delete(f"/api/projects/{pid}/members/{editor.user_id}")
    sub = owner.post(
        f"/api/projects/{pid}/subcorpora",
        json={"name": "全部", "corpus_id": corpus["id"], "filter": {}},
    ).json()
    assert owner.delete(f"/api/subcorpora/{sub['id']}").status_code == 204
    layer = owner.post(
        f"/api/projects/{pid}/layers",
        json={
            "corpus_id": corpus["id"],
            "kind": "span",
            "name": "偏误层",
            "label_set_id": label_set_id(owner, "learner-errors"),
            "preannotate": False,
        },
    ).json()
    assert owner.delete(f"/api/layers/{layer['id']}").status_code == 204
    doc = note(owner, pid, ready=False)
    assert owner.delete(f"/api/kb/documents/{doc['id']}").status_code == 204
    docs = owner.get(f"/api/corpora/{corpus['id']}/documents").json()["items"]
    assert (
        owner.delete(
            f"/api/corpora/{corpus['id']}/documents/{docs[0]['id']}"
        ).status_code
        == 204
    )
    assert owner.delete(f"/api/corpora/{corpus['id']}").status_code == 204

    other = owner.post("/api/projects", json={"name": "别的项目"}).json()
    assert owner.delete(f"/api/projects/{other['id']}").status_code == 204

    actions = [a for a, *_ in audit_actions()]
    for action in (
        "login",
        "login_failed",
        "user_create",
        "password_reset",
        "admin_grant",
        "admin_revoke",
        "user_disable",
        "user_enable",
        "password_change",
        "member_add",
        "member_role",
        "member_remove",
        "subcorpus_delete",
        "layer_delete",
        "kb_document_delete",
        "document_delete",
        "corpus_delete",
        "project_delete",
    ):
        assert action in actions, action
    failed = audit_actions(action="login_failed")
    assert failed == [("login_failed", None, None)]
    names = {a: n for a, n, _ in audit_actions(actor_email="owner@example.edu")}
    assert names["corpus_delete"] == "作文" and names["layer_delete"] == "偏误层"
    assert names["document_delete"] == docs[0]["title"]

    # admin: filters and paging; Bearer and non-admins 403
    page = admin.get(
        "/api/admin/audit", params={"action": "member_add,member_remove"}
    ).json()
    assert {x["action"] for x in page["items"]} == {"member_add", "member_remove"}
    assert page["items"][0]["ip"] == "testclient"
    mine = admin.get("/api/admin/audit", params={"actor": "owner@"}).json()
    assert mine["total"] > 0 and all(
        x["actor_email"] == "owner@example.edu" for x in mine["items"]
    )
    today = datetime.now().astimezone().date().isoformat()
    assert admin.get("/api/admin/audit", params={"from": today}).json()["total"] == len(
        actions
    )
    assert (
        admin.get("/api/admin/audit", params={"to": "2000-01-01"}).json()["total"] == 0
    )
    assert owner.get("/api/admin/audit").status_code == 403

    # project owners see their project only; other roles 403, Bearer 403
    own = owner.get(f"/api/projects/{pid}/audit").json()
    assert own["total"] > 0 and all(x["project_id"] == pid for x in own["items"])
    assert "project_delete" not in {x["action"] for x in own["items"]}
    viewer = member("viewer")
    assert viewer.get(f"/api/projects/{pid}/audit").status_code == 403
    assert bearer(owner, pid).get(f"/api/projects/{pid}/audit").status_code == 403
    assert (
        make_user("x@example.edu").get(f"/api/projects/{pid}/audit").status_code == 404
    )


def test_audit_ip_from_forwarded_for():
    c = anonymous()
    c.post(
        "/api/auth/login",
        json={"email": "nobody@example.edu", "password": "x"},
        headers={"X-Forwarded-For": "203.0.113.9, 10.0.0.7"},
    )
    from services.api.db import transaction
    from services.api.models import AuditLog

    with transaction() as db:
        row = db.scalar(select(AuditLog).where(AuditLog.action == "login_failed"))
        assert row.ip == "10.0.0.7" and row.detail["email"] == "nobody@example.edu"


# ---- soft delete, restore, purge ----


def test_soft_delete_restore_and_purge(
    owner, project, corpus, member, admin, monkeypatch
):
    from services.api.db import data_dir, session, transaction
    from services.api.models import AuditLog, Corpus, Project
    from services.api.projects import expired_project_ids, purge_project
    from services.api.storage import corpus_dir

    pid = project["id"]
    editor = member("editor")
    agent = bearer(owner, pid)
    layer = owner.post(
        f"/api/projects/{pid}/layers",
        json={
            "corpus_id": corpus["id"],
            "kind": "span",
            "name": "偏误",
            "label_set_id": label_set_id(owner, "learner-errors"),
            "preannotate": False,
        },
    ).json()
    doc = note(owner, pid, ready=False)
    job = owner.get(f"/api/projects/{pid}/jobs").json()["items"][0]
    keep = owner.post("/api/projects", json={"name": "保留"}).json()

    assert editor.delete(f"/api/projects/{pid}").status_code == 403
    assert agent.delete(f"/api/projects/{pid}").status_code == 403
    assert owner.delete(f"/api/projects/{pid}").status_code == 204
    for client in (owner, editor, agent):
        assert client.get(f"/api/projects/{pid}").status_code == 404
        assert client.get(f"/api/corpora/{corpus['id']}").status_code == 404
        assert client.get(f"/api/layers/{layer['id']}").status_code == 404
        assert client.get(f"/api/kb/documents/{doc['id']}").status_code == 404
        assert client.get(f"/api/jobs/{job['id']}").status_code == 404
        r = client.post(
            "/api/search",
            json={"scope": {"corpus_id": corpus["id"]}, "query": "language"},
        )
        assert r.status_code == 404
    assert [p["id"] for p in owner.get("/api/projects").json()["items"]] == [keep["id"]]
    assert agent.get("/api/projects").json()["total"] == 0
    assert (
        owner.post("/api/auth/agent-token", json={"project_id": pid}).status_code == 404
    )
    assert corpus_dir(corpus["id"]).exists()  # files stay until the purge

    deleted = owner.get("/api/me/deleted-projects").json()
    assert [p["id"] for p in deleted["items"]] == [pid]
    assert deleted["items"][0]["purge_at"] and deleted["items"][0]["deleted_at"]
    assert editor.get("/api/me/deleted-projects").json()["total"] == 0
    assert agent.get("/api/me/deleted-projects").status_code == 403

    assert editor.post(f"/api/projects/{pid}/restore").status_code == 403
    assert agent.post(f"/api/projects/{pid}/restore").status_code == 403
    assert owner.post(f"/api/projects/{keep['id']}/restore").status_code == 409
    r = owner.post(f"/api/projects/{pid}/restore")
    assert r.status_code == 200 and r.json()["role"] == "owner"
    assert owner.get(f"/api/projects/{pid}").status_code == 200
    assert editor.get(f"/api/layers/{layer['id']}").status_code == 200
    r = owner.post(
        "/api/search", json={"scope": {"corpus_id": corpus["id"]}, "query": "language"}
    )
    assert r.status_code == 200 and r.json()["counts"]["hits"] > 0

    # admins restore projects they are not in; past PROJECT_PURGE_DAYS: 410
    assert owner.delete(f"/api/projects/{pid}").status_code == 204
    assert admin.post(f"/api/projects/{pid}/restore").status_code == 200
    assert owner.delete(f"/api/projects/{pid}").status_code == 204
    with transaction() as db:
        db.get(Project, uuid.UUID(pid)).deleted_at = datetime.now(UTC) - timedelta(
            days=8
        )
    assert owner.get("/api/me/deleted-projects").json()["total"] == 0
    r = owner.post(f"/api/projects/{pid}/restore")
    assert r.status_code == 410 and r.json()["error"]["code"] == "PURGED"
    monkeypatch.setenv("PROJECT_PURGE_DAYS", "10")
    assert owner.get("/api/me/deleted-projects").json()["total"] == 1
    monkeypatch.setenv("PROJECT_PURGE_DAYS", "7")

    exports = data_dir() / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / f"{job['id']}.csv").write_text("x")
    with session() as db:
        assert expired_project_ids(db) == [uuid.UUID(pid)]
        assert purge_project(db, uuid.UUID(keep["id"])) is False  # not deleted
        assert purge_project(db, uuid.UUID(pid)) is True
    with transaction() as db:
        assert db.get(Project, uuid.UUID(pid)) is None
        assert db.get(Corpus, uuid.UUID(corpus["id"])) is None
        purge = db.scalar(select(AuditLog).where(AuditLog.action == "project_purge"))
        assert purge.actor_id is None and purge.target_name == project["name"]
        assert str(purge.project_id) == pid
    assert not corpus_dir(corpus["id"]).exists()
    assert not (exports / f"{job['id']}.csv").exists()
    assert (
        owner.post(f"/api/projects/{pid}/restore").json()["error"]["code"] == "PURGED"
    )
    assert owner.post(f"/api/projects/{uuid.uuid4()}/restore").status_code == 404
    assert owner.get(f"/api/projects/{keep['id']}").status_code == 200


# ---- admin views ----


def test_admin_projects_owner_and_jobs(
    owner, project, corpus, member, admin, make_user, monkeypatch
):
    pid = project["id"]
    editor = member("editor")
    outsider = make_user("outsider@example.edu")
    agent = bearer(
        admin, admin.post("/api/projects", json={"name": "管理员自己的"}).json()["id"]
    )
    for path in (
        "/api/admin/projects",
        "/api/admin/jobs",
        "/api/admin/system",
        "/api/admin/feedback",
    ):
        assert owner.get(path).status_code == 403, path
        assert agent.get(path).status_code == 403, path
    assert (
        owner.post(
            f"/api/admin/projects/{pid}/owner", json={"user_id": owner.user_id}
        ).status_code
        == 403
    )

    page = admin.get("/api/admin/projects").json()
    assert page["total"] == 2
    row = next(x for x in page["items"] if x["id"] == pid)
    assert row["owner"]["email"] == "owner@example.edu"
    assert (row["members"], row["corpora"], row["layers"], row["kb_documents"]) == (
        2,
        1,
        0,
        0,
    )
    assert row["disk_bytes"] > 0 and row["deleted_at"] is None
    assert admin.get("/api/admin/projects", params={"q": "owner@"}).json()["total"] == 1
    assert admin.get("/api/admin/projects", params={"q": "论文"}).json()["total"] == 1
    assert admin.get("/api/admin/projects", params={"deleted": 1}).json()["total"] == 0
    assert admin.get("/api/admin/projects", params={"deleted": 0}).json()["total"] == 2

    # owner change: outsider becomes owner, the old owner an editor
    r = admin.post(
        f"/api/admin/projects/{pid}/owner", json={"user_id": outsider.user_id}
    )
    assert r.status_code == 200, r.text
    assert (
        r.json()["owner"]["email"] == "outsider@example.edu"
        and r.json()["members"] == 3
    )
    roles = {
        m["email"]: m["role"]
        for m in outsider.get(f"/api/projects/{pid}/members").json()["items"]
    }
    assert roles == {
        "owner@example.edu": "editor",
        "editor@example.edu": "editor",
        "outsider@example.edu": "owner",
    }
    r = admin.post(f"/api/admin/projects/{pid}/owner", json={"user_id": editor.user_id})
    assert r.json()["owner"]["email"] == "editor@example.edu"
    assert {
        m["role"] for m in owner.get(f"/api/projects/{pid}/members").json()["items"]
    } == {
        "owner",
        "editor",
    }
    assert (
        admin.post(
            f"/api/admin/projects/{uuid.uuid4()}/owner",
            json={"user_id": editor.user_id},
        ).status_code
        == 404
    )
    assert len(audit_actions(action="project_owner")) == 2
    gone = make_user("gone@example.edu")
    admin.post(f"/api/admin/users/{gone.user_id}/disable")
    r = admin.post(f"/api/admin/projects/{pid}/owner", json={"user_id": gone.user_id})
    assert r.status_code == 409 and r.json()["error"]["code"] == "USER_DISABLED"

    editor.delete(f"/api/projects/{pid}")
    assert admin.get("/api/admin/projects", params={"deleted": 0}).json()["total"] == 1
    assert admin.get("/api/admin/projects").json()["total"] == 2
    assert (
        admin.get("/api/admin/projects", params={"deleted": 1}).json()["items"][0]["id"]
        == pid
    )
    # admins can also reassign a deleted project before restoring it
    admin.post(f"/api/projects/{pid}/restore")

    # jobs across projects; an admin cancels any of them (audited)
    job = upload(owner, corpus["id"], {"c.txt": TEXT}).json()
    jobs = admin.get("/api/admin/jobs", params={"state": "queued"}).json()
    assert [j["id"] for j in jobs["items"]] == [job["id"]]
    assert jobs["items"][0]["project_name"] == project["name"]
    assert admin.get("/api/admin/jobs", params={"kind": "export"}).json()["total"] == 0
    assert admin.get("/api/admin/jobs").json()["total"] >= 2
    assert (
        admin.get(f"/api/jobs/{job['id']}").status_code == 404
    )  # not a member: job pages stay private
    r = admin.post(f"/api/jobs/{job['id']}/cancel")
    assert r.status_code == 200 and r.json()["state"] == "cancelled"
    assert admin.post(f"/api/jobs/{job['id']}/cancel").status_code == 409
    assert audit_actions(action="job_cancel_admin")[0][2] == "root@example.edu"
    job2 = upload(owner, corpus["id"], {"d.txt": TEXT}).json()
    assert agent.post(f"/api/jobs/{job2['id']}/cancel").status_code in (403, 404)
    # outsider is an editor now: a regular cancel, not audited
    assert outsider.post(f"/api/jobs/{job2['id']}/cancel").status_code == 200
    assert len(audit_actions(action="job_cancel_admin")) == 1


def test_admin_system(admin, tmp_path, monkeypatch):
    from services.api.db import data_dir

    health = data_dir() / "worker-health"
    health.mkdir(parents=True, exist_ok=True)
    (health / "worker-1").write_text("")
    stale = health / "worker-light-1"
    stale.write_text('{"kinds": ["export", "stats"]}')
    old = datetime.now().timestamp() - 300
    os.utime(stale, (old, old))
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    r = admin.get("/api/admin/system").json()
    assert r["version"] and "model" in r and "embed" in r
    workers = {w["id"]: w for w in r["workers"]}
    assert (
        workers["worker-1"]["healthy"] is True and workers["worker-1"]["kinds"] is None
    )
    assert workers["worker-light-1"]["healthy"] is False
    assert workers["worker-light-1"]["kinds"] == ["export", "stats"]
    assert r["disk"]["total"] > 0 and r["disk"]["free"] > 0
    assert r["data_bytes"] >= 0 and r["search_cache_bytes"] >= 0
    assert r["last_backup_at"] is None

    backup = tmp_path / "backups" / "20261106-030000"
    backup.mkdir(parents=True)
    (backup / "manifest.txt").write_text("project=corpus\n")
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    at = admin.get("/api/admin/system").json()["last_backup_at"]
    assert at and datetime.fromisoformat(at) > datetime.now(UTC) - timedelta(minutes=5)
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "missing"))
    assert admin.get("/api/admin/system").json()["last_backup_at"] is None


# ---- feedback ----


def test_feedback(owner, project, admin, make_user):
    agent = bearer(owner, project["id"])
    assert agent.post("/api/feedback", json={"text": "x"}).status_code == 403
    assert anonymous().post("/api/feedback", json={"text": "x"}).status_code == 401
    assert owner.post("/api/feedback", json={"text": "   "}).status_code == 422
    assert owner.post("/api/feedback", json={"text": "长" * 2001}).status_code == 422
    r = owner.post(
        "/api/feedback",
        json={
            "text": " 检索页翻页后高亮丢失 ",
            "page": "/search",
            "project_id": project["id"],
        },
    )
    assert r.status_code == 200, r.text
    fb = r.json()
    assert fb["text"] == "检索页翻页后高亮丢失" and fb["status"] == "open"
    assert fb["project_id"] == project["id"] and fb["app_version"]
    stranger = make_user("s@example.edu")
    r = stranger.post(
        "/api/feedback", json={"text": "别人的项目", "project_id": project["id"]}
    )
    assert r.status_code == 200 and r.json()["project_id"] is None

    assert owner.get("/api/admin/feedback").status_code == 403
    items = admin.get("/api/admin/feedback").json()
    assert items["total"] == 2 and items["items"][0]["user"]["email"] == "s@example.edu"
    assert items["items"][1]["project_name"] == project["name"]
    assert (
        owner.patch(
            f"/api/admin/feedback/{fb['id']}", json={"status": "done"}
        ).status_code
        == 403
    )
    r = admin.patch(
        f"/api/admin/feedback/{fb['id']}",
        json={"status": "done", "admin_note": "已修复"},
    )
    assert r.status_code == 200
    assert (
        r.json()["status"] == "done"
        and r.json()["handled_at"]
        and r.json()["admin_note"] == "已修复"
    )
    assert (
        admin.get("/api/admin/feedback", params={"status": "open"}).json()["total"] == 1
    )
    assert (
        admin.get("/api/admin/feedback", params={"status": "done"}).json()["total"] == 1
    )
    r = admin.patch(f"/api/admin/feedback/{fb['id']}", json={"status": "open"})
    assert r.json()["handled_at"] is None and r.json()["admin_note"] == "已修复"
    assert (
        admin.patch("/api/admin/feedback/999999", json={"status": "done"}).status_code
        == 404
    )


# ---- export expiry ----


def test_export_expired(owner, project, monkeypatch):
    from services.api.db import data_dir, transaction
    from services.api.models import Job

    def export_job(days_ago):
        with transaction() as db:
            job = Job(
                kind="export",
                params={"format": "csv", "source": "evidence"},
                owner_id=uuid.UUID(owner.user_id),
                project_id=uuid.UUID(project["id"]),
                state="succeeded",
                result={"filename": "e.csv"},
                finished_at=datetime.now(UTC) - timedelta(days=days_ago),
            )
            db.add(job)
            db.flush()
            return str(job.id)

    old, recent = export_job(31), export_job(1)
    r = owner.get(f"/api/jobs/{old}/download")
    assert r.status_code == 410
    assert r.json()["error"] == {
        "code": "EXPORT_EXPIRED",
        "message": "导出文件已过期，请重新导出",
    }
    assert owner.get(f"/api/jobs/{recent}/download").status_code == 404
    monkeypatch.setenv("EXPORT_RETENTION_DAYS", "60")
    assert owner.get(f"/api/jobs/{old}/download").status_code == 404
    path = data_dir() / "exports" / f"{recent}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("a,b\n")
    assert owner.get(f"/api/jobs/{recent}/download").status_code == 200


# ---- automatic index rebuild ----


def test_index_rebuild_after_document_changes(owner, project, corpus, fake_engine):
    from services.api.db import transaction
    from services.api.models import Job

    def index_jobs(state=None):
        with transaction() as db:
            stmt = select(func.count()).where(Job.kind == "index")
            if state:
                stmt = stmt.where(Job.state == state)
            return db.scalar(stmt)

    cid = corpus["id"]
    assert corpus["index_pending"] is False
    before = index_jobs()
    docs = owner.get(f"/api/corpora/{cid}/documents").json()["items"]
    a, b = docs
    r = owner.patch(f"/api/corpora/{cid}/documents/{a['id']}", json={"title": "新标题"})
    assert (
        r.status_code == 200 and index_jobs() == before
    )  # titles are not in the index
    r = owner.patch(
        f"/api/corpora/{cid}/documents/{a['id']}", json={"metadata": {"year": 2020}}
    )
    assert index_jobs("queued") == 1
    owner.patch(
        f"/api/corpora/{cid}/documents/{a['id']}", json={"metadata": {"year": 2020}}
    )
    owner.patch(
        f"/api/corpora/{cid}/documents/{b['id']}", json={"metadata": {"year": 2021}}
    )
    assert owner.delete(f"/api/corpora/{cid}/documents/{a['id']}").status_code == 204
    assert index_jobs("queued") == 1  # one queued build is enough
    c = owner.get(f"/api/corpora/{cid}").json()
    assert c["index_pending"] is True and c["status"] == "stale"
    listed = owner.get("/api/corpora", params={"project_id": project["id"]}).json()[
        "items"
    ]
    assert next(x for x in listed if x["id"] == cid)["index_pending"] is True
    drain()
    c = owner.get(f"/api/corpora/{cid}").json()
    assert c["index_pending"] is False and c["status"] == "ready"
    assert c["stats"]["documents"] == 1
    assert [d for d, _ in fake_engine.indexes[f"C{uuid.UUID(cid).hex.upper()}"]] == [
        b["id"]
    ]


# ---- upload language ----


def test_upload_language_check(owner, project):
    def corpus_of(language):
        return owner.post(
            f"/api/projects/{project['id']}/corpora",
            json={"name": language, "language": language},
        ).json()

    en, fr = (
        corpus_of("en"),
        corpus_of("ko"),
    )  # creating a corpus of any language is fine (P10: ko is still unsupported)
    r = upload(owner, en["id"], {"a.txt": TEXT}, language="ko")
    assert r.status_code == 422
    assert r.json()["error"] == {
        "code": "LANGUAGE_UNSUPPORTED",
        "message": "暂不支持该语言：ko（支持 zh、en、ja、fr、de、es、ru）",
    }
    assert upload(owner, fr["id"], {"a.txt": TEXT}).status_code == 422
    assert upload(owner, fr["id"], {"a.conllu": "# x\n"}).status_code == 200
    assert upload(owner, fr["id"], {"a.txt": TEXT}, language="auto").status_code == 200
    assert (
        upload(owner, en["id"], {"b.txt": TEXT}, language="zh-Hans").status_code == 200
    )
    assert upload(owner, en["id"], {"c.txt": TEXT}).status_code == 200


def test_delete_cancels_jobs_and_restore_keeps_data(
    owner, project, corpus, monkeypatch
):
    """Deleting stops the project's queued / running jobs (LLM pre-annotation included); after a restore
    search, layers and the knowledge base work again and stopped jobs can be retried."""
    from engine.kb import embed
    from tests.api.test_kb import fake_vector

    monkeypatch.setattr(
        embed, "embed", lambda texts, download=True: [fake_vector(t) for t in texts]
    )
    monkeypatch.setattr(embed, "load", lambda download=True: None)
    monkeypatch.setattr(embed, "model_name", lambda: "fake-model")
    pid = project["id"]
    kb = owner.post(
        f"/api/projects/{pid}/kb/documents",
        json={"kind": "note", "title": "笔记", "body": "corpus 语料研究"},
    ).json()
    drain()
    layer = owner.post(
        f"/api/projects/{pid}/layers",
        json={
            "corpus_id": corpus["id"],
            "kind": "span",
            "name": "偏误",
            "label_set_id": label_set_id(owner, "learner-errors"),
            "preannotate": True,
        },
    ).json()
    pre = layer["job_id"]
    imp = upload(owner, corpus["id"], {"c.txt": TEXT}).json()["id"]

    assert owner.delete(f"/api/projects/{pid}").status_code == 204
    from services.api.db import transaction
    from services.api.models import AnnotationLayer, Job

    with transaction() as db:
        assert {db.get(Job, uuid.UUID(j)).state for j in (pre, imp)} == {"cancelled"}
        stopped = db.get(AnnotationLayer, uuid.UUID(layer["id"]))
        assert (stopped.status, stopped.error) == ("failed", "预标已取消")
    drain()  # the stopped jobs are not picked up

    assert owner.post(f"/api/projects/{pid}/restore").status_code == 200
    restored = audit_actions(action="project_restore")
    assert restored == [("project_restore", project["name"], "owner@example.edu")]
    r = owner.post(f"/api/projects/{pid}/kb/search", json={"q": "corpus"})
    assert r.status_code == 200
    assert [i["chunk"]["document_id"] for i in r.json()["items"]] == [kb["id"]]
    r = owner.post(
        "/api/search", json={"scope": {"corpus_id": corpus["id"]}, "query": "language"}
    )
    assert r.status_code == 200 and r.json()["counts"]["hits"] > 0
    assert owner.get(f"/api/layers/{layer['id']}").status_code == 200
    r = owner.post(f"/api/jobs/{pre}/retry")
    assert r.status_code == 200 and r.json()["state"] == "queued"
