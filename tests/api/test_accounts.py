"""Account lifecycle, password change, health and system info (contracts/p7.md §五、§六)."""

from fastapi.testclient import TestClient

from tests.api.conftest import ORIGIN, PASSWORD

NEW_PASSWORD = "a brand new passphrase"


def client():
    from services.api.main import app

    return TestClient(app, headers={"Origin": ORIGIN})


def login(email, password, c=None):
    c = c or client()
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    return c, r


def bearer_of(c, project_id):
    token = c.post("/api/auth/agent-token", json={"project_id": project_id}).json()[
        "token"
    ]
    b = client()
    b.headers["Authorization"] = f"Bearer {token}"
    return b


def test_create_login_forced_change(make_user):
    admin = make_user("root@example.edu", admin=True)
    r = admin.post(
        "/api/admin/users",
        json={"email": "New@Example.edu ", "display_name": "新同学"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    temp = body["temporary_password"]
    assert len(temp) == 16
    assert body["user"]["email"] == "new@example.edu"
    assert body["user"]["projects"] == 0 and body["user"]["disabled_at"] is None
    assert (
        admin.post(
            "/api/admin/users", json={"email": "new@example.edu", "display_name": "x"}
        ).status_code
        == 409
    )

    c, r = login("new@example.edu", temp)
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    assert c.get("/api/auth/me").json()["must_change_password"] is True
    r = c.get("/api/projects")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    r = c.post("/api/projects", json={"name": "x"})
    assert r.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    r = c.post(
        "/api/auth/password",
        json={"old_password": "wrong password!", "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "WRONG_PASSWORD"
    r = c.post(
        "/api/auth/password", json={"old_password": temp, "new_password": "short"}
    )
    assert r.status_code == 422
    r = c.post("/api/auth/password", json={"old_password": temp, "new_password": temp})
    assert r.status_code == 422
    r = c.post(
        "/api/auth/password", json={"old_password": temp, "new_password": NEW_PASSWORD}
    )
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] is False
    assert c.get("/api/projects").status_code == 200

    listing = admin.get("/api/admin/users", params={"q": "新同"}).json()
    assert listing["total"] == 1
    assert listing["items"][0]["last_login_at"] is not None
    assert admin.get("/api/admin/users").json()["total"] == 2


def test_disable_revokes_sessions_and_tokens(make_user, owner, project):
    admin = make_user("root@example.edu", admin=True)
    b = bearer_of(owner, project["id"])
    assert b.get(f"/api/projects/{project['id']}").status_code == 200

    r = admin.post(f"/api/admin/users/{owner.user_id}/disable")
    assert r.status_code == 200 and r.json()["disabled_at"] is not None
    assert owner.get("/api/auth/me").status_code == 401
    assert b.get(f"/api/projects/{project['id']}").status_code == 401
    _, r = login("owner@example.edu", PASSWORD)
    assert r.status_code == 403
    assert r.json()["error"] == {
        "code": "ACCOUNT_DISABLED",
        "message": "账号已停用，请联系管理员",
    }

    assert admin.post(f"/api/admin/users/{owner.user_id}/enable").status_code == 200
    c, r = login("owner@example.edu", PASSWORD)
    assert r.status_code == 200
    assert c.get("/api/projects").json()["total"] == 1


def test_disabled_user_rejected_even_with_live_session(owner):
    """A session that survived (e.g. account disabled directly in the database) is refused too."""
    from datetime import UTC, datetime

    from services.api.db import transaction
    from services.api.models import User

    with transaction() as db:
        db.get(User, owner.user_id).disabled_at = datetime.now(UTC)
    r = owner.get("/api/projects")
    assert r.status_code == 401 and r.json()["error"]["code"] == "ACCOUNT_DISABLED"


def test_admins_disabling_each_other_at_once(make_user, monkeypatch):
    """Concurrent disable / demote of each other: no 500 (deadlock) and one active admin remains.
    A pause after the last-admin check holds its row locks long enough for both requests to overlap."""
    import threading
    import time

    from sqlalchemy import func, select

    from services.api import admin
    from services.api.db import transaction
    from services.api.models import User

    check = admin._keep_one_admin

    def slow_check(db, target):
        check(db, target)
        time.sleep(0.3)

    monkeypatch.setattr(admin, "_keep_one_admin", slow_check)

    for n in range(6):
        a = make_user(f"a{n}@example.edu", admin=True)
        b = make_user(f"b{n}@example.edu", admin=True)
        if n % 2:
            calls = [
                (a, f"/api/admin/users/{b.user_id}/admin", {"is_admin": False}),
                (b, f"/api/admin/users/{a.user_id}/admin", {"is_admin": False}),
            ]
        else:
            calls = [
                (a, f"/api/admin/users/{b.user_id}/disable", None),
                (b, f"/api/admin/users/{a.user_id}/disable", None),
            ]
        gate = threading.Barrier(2)
        codes = []

        def run(c, path, body, gate=gate, codes=codes):
            gate.wait()
            try:  # TestClient re-raises server errors (a deadlock) instead of answering 500
                codes.append(c.post(path, json=body).status_code)
            except Exception as e:  # noqa: BLE001
                codes.append(repr(e)[:200])

        threads = [threading.Thread(target=run, args=call) for call in calls]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(codes) == 2 and all(
            code in (200, 401, 403, 409) for code in codes
        ), codes
        assert 200 in codes, codes
        with transaction() as db:
            active = db.scalar(
                select(func.count()).where(
                    User.is_admin,
                    User.disabled_at.is_(None),
                    User.email.in_([f"a{n}@example.edu", f"b{n}@example.edu"]),
                )
            )
            assert active == 1
            # leave no active admin from this round, so the next pair starts alone
            for u in db.scalars(select(User).where(User.is_admin)):
                u.is_admin = False


def test_last_admin_and_self(make_user):
    admin = make_user("root@example.edu", admin=True)
    other = make_user("second@example.edu", admin=True)
    r = admin.post(f"/api/admin/users/{admin.user_id}/disable")
    assert r.status_code == 409 and r.json()["error"]["code"] == "CANNOT_DISABLE_SELF"

    assert admin.post(f"/api/admin/users/{other.user_id}/disable").status_code == 200
    # admin is now the only active admin
    r = admin.post(f"/api/admin/users/{admin.user_id}/admin", json={"is_admin": False})
    assert r.status_code == 409 and r.json()["error"]["code"] == "LAST_ADMIN"
    assert admin.post(f"/api/admin/users/{other.user_id}/enable").status_code == 200
    c, _ = login("second@example.edu", PASSWORD)
    r = c.post(f"/api/admin/users/{admin.user_id}/disable")
    assert r.status_code == 200
    # second is the last active admin: admin cannot disable it (admin is disabled anyway)
    r = c.post(
        f"/api/admin/users/{c.get('/api/auth/me').json()['id']}/admin",
        json={"is_admin": False},
    )
    assert r.status_code == 409

    plain = make_user("plain@example.edu")
    r = c.post(f"/api/admin/users/{plain.user_id}/admin", json={"is_admin": True})
    assert r.status_code == 200 and r.json()["is_admin"] is True
    r = c.post(f"/api/admin/users/{plain.user_id}/admin", json={"is_admin": False})
    assert r.status_code == 200 and r.json()["is_admin"] is False


def test_reset_password(make_user, owner, project):
    admin = make_user("root@example.edu", admin=True)
    b = bearer_of(owner, project["id"])
    r = admin.post(f"/api/admin/users/{owner.user_id}/reset-password")
    assert r.status_code == 200
    temp = r.json()["temporary_password"]
    assert owner.get("/api/auth/me").status_code == 401
    assert b.get(f"/api/projects/{project['id']}").status_code == 401
    _, r = login("owner@example.edu", PASSWORD)
    assert r.status_code == 401
    c, r = login("owner@example.edu", temp)
    assert r.json()["must_change_password"] is True
    assert (
        c.post("/api/auth/agent-token", json={"project_id": project["id"]}).json()[
            "error"
        ]["code"]
        == "PASSWORD_CHANGE_REQUIRED"
    )


def test_password_change_keeps_current_session_only(owner, project):
    other_session, r = login("owner@example.edu", PASSWORD)
    assert r.status_code == 200
    b = bearer_of(owner, project["id"])
    r = b.post(
        "/api/auth/password",
        json={"old_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 403
    r = owner.post(
        "/api/auth/password",
        json={"old_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 200, r.text
    assert owner.get("/api/projects").status_code == 200
    assert other_session.get("/api/auth/me").status_code == 401
    assert b.get(f"/api/projects/{project['id']}").status_code == 401
    _, r = login("owner@example.edu", NEW_PASSWORD)
    assert r.status_code == 200


def test_admin_endpoints_need_admin_session(make_user, owner, project):
    admin = make_user("root@example.edu", admin=True)
    calls = [
        ("GET", "/api/admin/users", None),
        ("POST", "/api/admin/users", {"email": "x@example.edu", "display_name": "x"}),
        ("POST", f"/api/admin/users/{owner.user_id}/reset-password", None),
        ("POST", f"/api/admin/users/{owner.user_id}/disable", None),
        ("POST", f"/api/admin/users/{owner.user_id}/enable", None),
        ("POST", f"/api/admin/users/{owner.user_id}/admin", {"is_admin": True}),
    ]
    admin_project = admin.post("/api/projects", json={"name": "管理员项目"}).json()
    admin_bearer = bearer_of(admin, admin_project["id"])
    for method, path, body in calls:
        for c in (owner, admin_bearer):
            r = c.request(method, path, json=body)
            assert r.status_code == 403, (method, path, r.status_code)


def test_health_and_system_info(owner, monkeypatch):
    from engine.kb import embed

    c = client()
    r = c.get("/api/health")
    assert r.status_code == 200 and r.json() == {"ok": True, "db": True}
    assert c.get("/api/system/info").status_code == 401

    monkeypatch.setenv("APP_VERSION", "1.2.0")
    monkeypatch.setenv("MODEL_BASE_URL", "https://user:key@api.example.com:8443/v1")
    monkeypatch.setenv("MODEL_ID", "qwen-plus")
    monkeypatch.setenv("EMBED_PROVIDER", "local")
    monkeypatch.setattr(embed, "load", lambda download=True: None)
    info = owner.get("/api/system/info").json()
    assert info["version"] == "1.2.0"
    assert info["model"] == {
        "configured": True,
        "host": "api.example.com",
        "model_id": "qwen-plus",
    }
    assert info["embed"]["mode"] == "local" and info["embed"]["host"] is None
    assert info["embed"]["ready"] is True

    monkeypatch.delenv("MODEL_BASE_URL")
    monkeypatch.setenv("EMBED_PROVIDER", "openai")
    monkeypatch.setenv("EMBED_BASE_URL", "http://embed.internal:9000/v1")
    monkeypatch.setenv("EMBED_MODEL", "bge-m3")
    info = owner.get("/api/system/info").json()
    assert info["model"]["configured"] is False and info["model"]["host"] is None
    assert info["embed"] == {
        "mode": "remote",
        "host": "embed.internal",
        "model": "bge-m3",
        "ready": True,
    }


def test_health_reports_database_failure(monkeypatch):
    from sqlalchemy import create_engine

    from services.api import system

    down = create_engine("postgresql+psycopg://corpus:x@127.0.0.1:1/corpus")
    monkeypatch.setattr(system, "engine", lambda: down)
    r = client().get("/api/health")
    assert r.status_code == 503 and r.json() == {"ok": False, "db": False}


def test_create_account_reset(owner, project, capsys, monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "create_account.py"
    spec = importlib.util.spec_from_file_location("create_account", path)
    create_account = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(create_account)
    monkeypatch.setattr(
        sys, "argv", ["create_account.py", "--email", "owner@example.edu", "--reset"]
    )
    create_account.main()
    out = capsys.readouterr().out
    temp = out.split("临时密码：")[1].strip()
    assert owner.get("/api/auth/me").status_code == 401
    _, r = login("owner@example.edu", temp)
    assert r.status_code == 200 and r.json()["must_change_password"] is True


def test_worker_health_file(monkeypatch, tmp_path):
    import time

    from services.worker import main as worker

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    worker.touch_health()
    path = tmp_path / "worker-health" / worker.WORKER_ID
    assert time.time() - path.stat().st_mtime < 90
