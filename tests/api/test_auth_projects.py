"""Actual PostgreSQL S1 auth/RLS integration; no SQLite or mock authorization."""

import os
import secrets
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from services.api import auth, projects
from services.api.db import engine, transaction, validate_runtime_role
from services.api.errors import install_error_handlers
from services.api.models import LoginSession, Project, ProjectMember, User


@unittest.skipUnless(
    os.getenv("TEST_OWNER_DATABASE_URL") and os.getenv("TEST_ADMIN_DATABASE_URL"),
    "Dedicated Compose PostgreSQL integration environment required",
)
class AuthProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner_engine = create_engine(
            os.environ["TEST_OWNER_DATABASE_URL"], hide_parameters=True
        )
        cls.admin_engine = create_engine(
            os.environ["TEST_ADMIN_DATABASE_URL"], hide_parameters=True
        )
        cls.password = secrets.token_urlsafe(24)
        cls.users = {}
        with Session(cls.owner_engine) as session, session.begin():
            for role in ("owner", "editor", "viewer", "admin", "disabled"):
                user = User(
                    id=uuid4(),
                    email=f"s1-{uuid4().hex}@example.test",
                    password_hash=auth.HASHER.hash(cls.password),
                    is_active=role != "disabled",
                    is_platform_admin=role == "admin",
                )
                session.add(user)
                cls.users[role] = {"id": user.id, "email": user.email}
        cls.app = FastAPI()
        install_error_handlers(cls.app)
        cls.app.include_router(auth.router)
        cls.app.include_router(projects.router)

    @classmethod
    def tearDownClass(cls):
        ids = [row["id"] for row in cls.users.values()]
        with Session(cls.admin_engine) as session, session.begin():
            session.execute(delete(Project).where(Project.owner_id.in_(ids)))
            session.execute(delete(User).where(User.id.in_(ids)))
        cls.owner_engine.dispose()
        cls.admin_engine.dispose()

    def setUp(self):
        auth._attempts.clear()
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.close()

    def login(self, role="owner"):
        client = TestClient(self.app, base_url=os.environ["PUBLIC_ORIGIN"])
        self.clients.append(client)
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": os.environ["PUBLIC_ORIGIN"]},
            json={"email": self.users[role]["email"], "password": self.password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        client.headers.update(
            {
                "Origin": os.environ["PUBLIC_ORIGIN"],
                "X-CSRF-Token": response.json()["csrf_token"],
            }
        )
        return client, response

    def project(self, client):
        result = client.post(
            "/api/v1/projects", json={"name": "S1 integration " + uuid4().hex}
        )
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()["id"]

    def add_member(self, owner, project_id, role):
        result = owner.put(
            f"/api/v1/projects/{project_id}/members/{self.users[role]['id']}",
            json={"role": role},
        )
        self.assertEqual(result.status_code, 200, result.text)

    def test_hash_only_session_cookie_and_logout_replay(self):
        client, response = self.login()
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertNotIn("secure", cookie)
        raw = client.cookies[auth.COOKIE]
        self.assertNotIn(raw, response.text)
        self.assertNotIn(self.password, response.text)
        with transaction() as session:
            stored = session.get(LoginSession, auth.token_hash(raw))
            self.assertEqual(
                stored.csrf_hash, auth.token_hash(response.json()["csrf_token"])
            )
            self.assertNotEqual(stored.token_hash, raw)
            self.assertTrue(
                session.get(User, self.users["owner"]["id"]).password_hash.startswith(
                    "$argon2id$"
                )
            )
        self.assertEqual(
            client.get("/api/v1/auth/session").json()["csrf_token"],
            response.json()["csrf_token"],
        )
        self.assertEqual(client.post("/api/v1/auth/logout").status_code, 204)
        client.cookies.set(auth.COOKIE, raw)
        self.assertEqual(client.get("/api/v1/auth/session").status_code, 401)

    def test_https_secure_cookie_and_explicit_local_http_only(self):
        with patch.dict(
            os.environ,
            {
                "PUBLIC_ORIGIN": "https://research.example",
                "ALLOW_INSECURE_HTTP": "false",
            },
        ):
            _, response = self.login()
            self.assertIn("Secure", response.headers["set-cookie"])
        with (
            patch.dict(
                os.environ,
                {
                    "PUBLIC_ORIGIN": "http://research.example",
                    "ALLOW_INSECURE_HTTP": "true",
                },
            ),
            self.assertRaises(RuntimeError),
        ):
            auth.site_config()

    def test_csrf_origin_and_login_content_type(self):
        client, _ = self.login()
        for headers in (
            {"X-CSRF-Token": "wrong"},
            {"Origin": "https://attacker.example"},
        ):
            result = client.post(
                "/api/v1/projects", json={"name": "denied"}, headers=headers
            )
            self.assertEqual(result.status_code, 403)
            self.assertEqual(
                client.post("/api/v1/auth/logout", headers=headers).status_code, 403
            )
        other = TestClient(self.app, base_url=os.environ["PUBLIC_ORIGIN"])
        self.clients.append(other)
        result = other.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://attacker.example"},
            json={"email": self.users["owner"]["email"], "password": self.password},
        )
        self.assertEqual(result.status_code, 403)
        result = other.post(
            "/api/v1/auth/login",
            headers={
                "Origin": os.environ["PUBLIC_ORIGIN"],
                "Content-Type": "text/plain",
            },
            content="{}",
        )
        self.assertIn(result.status_code, (415, 422))
        invalid = other.post(
            "/api/v1/auth/login",
            json={"email": "bad", "password": self.password, "extra": self.password},
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn(self.password, invalid.text)

    def test_project_role_boundaries_and_platform_admin_isolation(self):
        owner, _ = self.login()
        project_id = self.project(owner)
        self.add_member(owner, project_id, "editor")
        self.add_member(owner, project_id, "viewer")
        for role in ("editor", "viewer", "admin"):
            client, _ = self.login(role)
            result = client.get(f"/api/v1/projects/{project_id}")
            if role == "admin":
                self.assertEqual(result.status_code, 404)
                self.assertEqual(client.get("/api/v1/projects").json()["items"], [])
            else:
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["role"], role)
                self.assertEqual(
                    result.json()["permissions"]["upload"], role == "editor"
                )
                self.assertEqual(
                    client.get(f"/api/v1/projects/{project_id}/members").status_code,
                    403,
                )
        result = owner.put(
            f"/api/v1/projects/{project_id}/members/{self.users['owner']['id']}",
            json={"role": "viewer"},
        )
        self.assertEqual(result.status_code, 409)
        viewer, _ = self.login("viewer")
        self.assertEqual(
            owner.delete(
                f"/api/v1/projects/{project_id}/members/{self.users['viewer']['id']}"
            ).status_code,
            204,
        )
        self.assertEqual(viewer.get(f"/api/v1/projects/{project_id}").status_code, 404)

    def test_real_rls_editor_write_viewer_denial_and_cross_project(self):
        owner, _ = self.login()
        project_id = self.project(owner)
        self.add_member(owner, project_id, "editor")
        self.add_member(owner, project_id, "viewer")
        for role, writable in (("editor", True), ("viewer", False), ("admin", False)):
            with transaction(self.users[role]["id"]) as session:
                found = session.scalar(select(Project).where(Project.id == project_id))
                self.assertEqual(found is not None, role != "admin")
                result = session.execute(
                    update(Project)
                    .where(Project.id == project_id)
                    .values(name="RLS checked")
                )
                self.assertEqual(result.rowcount, int(writable))
        with (
            self.assertRaises(DBAPIError),
            transaction(self.users["viewer"]["id"]) as session,
        ):
            session.add(
                Project(name="forged owner", owner_id=self.users["owner"]["id"])
            )
            session.flush()
        with transaction(self.users["editor"]["id"]) as session:
            changed = session.execute(
                update(ProjectMember)
                .where(ProjectMember.project_id == project_id)
                .values(role="viewer")
            )
            self.assertEqual(changed.rowcount, 0)

    def test_pool_identity_cleared_after_commit_and_rollback(self):
        owner, _ = self.login()
        project_id = self.project(owner)
        with transaction(self.users["owner"]["id"]) as session:
            self.assertIsNotNone(session.get(Project, project_id))
            backend_pid = session.scalar(text("SELECT pg_backend_pid()"))
        with (
            self.assertRaisesRegex(RuntimeError, "rollback"),
            transaction(self.users["owner"]["id"]) as session,
        ):
            self.assertEqual(
                session.scalar(text("SELECT pg_backend_pid()")), backend_pid
            )
            self.assertEqual(
                session.scalar(text("SELECT app.actor_id()")), self.users["owner"]["id"]
            )
            raise RuntimeError("rollback")
        with transaction() as session:
            self.assertEqual(
                session.scalar(text("SELECT pg_backend_pid()")), backend_pid
            )
            self.assertIsNone(session.scalar(text("SELECT app.actor_id()")))
            self.assertEqual(session.scalars(select(Project)).all(), [])
        with engine().connect() as connection:
            self.assertIn(
                connection.scalar(text("SELECT current_setting('app.actor_id',true)")),
                (None, ""),
            )

    def test_runtime_refuses_owner_and_superuser(self):
        for privileged in (self.owner_engine, self.admin_engine):
            with (
                Session(privileged) as session,
                self.assertRaisesRegex(RuntimeError, "non-owner"),
            ):
                validate_runtime_role(session)
        with transaction() as session:
            self.assertEqual(session.scalar(text("SELECT current_user")), "corpus_app")

    def test_disabled_expired_and_missing_accounts(self):
        client, _ = self.login()
        raw = client.cookies[auth.COOKIE]
        with Session(self.admin_engine) as session, session.begin():
            session.execute(
                update(LoginSession)
                .where(LoginSession.token_hash == auth.token_hash(raw))
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        self.assertEqual(client.get("/api/v1/auth/session").status_code, 401)
        editor, _ = self.login("editor")
        with Session(self.owner_engine) as session, session.begin():
            session.execute(
                update(User)
                .where(User.id == self.users["editor"]["id"])
                .values(is_active=False)
            )
        try:
            self.assertEqual(editor.get("/api/v1/auth/session").status_code, 401)
            with transaction(self.users["editor"]["id"]) as session:
                self.assertIsNone(session.scalar(text("SELECT app.actor_id()")))
        finally:
            with Session(self.owner_engine) as session, session.begin():
                session.execute(
                    update(User)
                    .where(User.id == self.users["editor"]["id"])
                    .values(is_active=True)
                )
        for email in (self.users["disabled"]["email"], "not-found@example.test"):
            result = client.post(
                "/api/v1/auth/login", json={"email": email, "password": self.password}
            )
            self.assertEqual(result.status_code, 401)
            self.assertEqual(result.json()["code"], "AUTH_INVALID")

    def test_bounded_login_throttling_and_registration_closed(self):
        client = TestClient(self.app, base_url=os.environ["PUBLIC_ORIGIN"])
        self.clients.append(client)
        statuses = [
            client.post(
                "/api/v1/auth/login",
                headers={"Origin": os.environ["PUBLIC_ORIGIN"]},
                json={"email": "missing@example.test", "password": "invalid"},
            ).status_code
            for _ in range(11)
        ]
        self.assertEqual(statuses, [401] * 10 + [429])
        self.assertEqual(client.post("/api/v1/auth/register", json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
