"""Opt-in real PostgreSQL catalog RLS, idempotency and concurrent edits."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError

from contracts.catalog import CatalogCreate, CatalogUpdate
from services.api import catalog
from services.api.auth import Actor, current_actor
from services.api.catalog_models import CatalogSource
from services.api.db import engine, transaction
from services.api.errors import ApiError, install_error_handlers

ENABLED = all(
    os.getenv(k)
    for k in ("DATABASE_URL", "TEST_OWNER_DATABASE_URL", "TEST_ADMIN_DATABASE_URL")
)


@unittest.skipUnless(ENABLED, "Explicit real PostgreSQL role URLs required")
class CatalogPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner = create_engine(os.environ["TEST_OWNER_DATABASE_URL"])
        cls.admin_db = create_engine(os.environ["TEST_ADMIN_DATABASE_URL"])

    @classmethod
    def tearDownClass(cls):
        engine().dispose()
        cls.owner.dispose()
        cls.admin_db.dispose()

    def setUp(self):
        self.prefix = "test_" + uuid4().hex
        self.users = [
            Actor(uuid4(), f"catalog-{uuid4().hex}@example.test", i < 2, "")
            for i in range(3)
        ]
        self.admin, self.admin2, self.reader = self.users
        with self.owner.begin() as conn:
            for user in self.users:
                conn.execute(
                    text(
                        "INSERT INTO app.users(id,email,password_hash,is_platform_admin) VALUES(:id,:email,'unused',:admin)"
                    ),
                    {
                        "id": user.id,
                        "email": user.email,
                        "admin": user.is_platform_admin,
                    },
                )
        self.app = FastAPI()
        install_error_handlers(self.app)
        self.app.include_router(catalog.router)
        self.actor = self.admin
        self.app.dependency_overrides[current_actor] = lambda: self.actor
        self.client = TestClient(self.app)
        self.metadata = {
            "name": "Catalog integration",
            "publisher": "Test publisher",
            "entry_kind": "dataset",
            "categories": ["test"],
            "languages": ["zh"],
            "official_url": "https://example.test/dataset",
            "materials": "Fixture metadata",
            "access_route": "Catalog only",
            "boundary": "Not a release",
        }

    def tearDown(self):
        self.client.close()
        with self.admin_db.begin() as conn:
            for user in self.users:
                conn.execute(
                    text("DELETE FROM app.catalog_actions WHERE actor_id=:id"),
                    {"id": user.id},
                )
            conn.execute(
                text("DELETE FROM app.catalog_sources WHERE source_id LIKE :prefix"),
                {"prefix": self.prefix + "%"},
            )
            for user in self.users:
                conn.execute(
                    text("DELETE FROM app.users WHERE id=:id"), {"id": user.id}
                )

    def create(self, suffix="", key=None):
        response = self.client.post(
            "/api/v1/admin/catalog",
            headers={"Idempotency-Key": key or uuid4().hex},
            json={"source_id": self.prefix + suffix, **self.metadata},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_seed_discovery_and_empty_production_versions(self):
        self.actor = self.reader
        response = self.client.get("/api/v1/sources", params={"q": "D12"})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["name"], "Tatoeba")
        self.assertEqual(
            result["items"][0]["integration_status"], "experimental_evidence"
        )
        self.assertFalse(result["items"][0]["capabilities"]["fulltext_analysis"])
        self.assertEqual(
            self.client.get("/api/v1/sources/D12/versions").json(),
            {"items": [], "total": 0, "next_cursor": None},
        )
        self.assertEqual(
            self.client.get("/api/v1/sources", params={"capability": "export"}).json()[
                "total"
            ],
            0,
        )
        self.assertEqual(
            self.client.get("/api/v1/sources", params={"q": "%"}).json()["total"], 0
        )
        self.app.dependency_overrides.clear()
        self.assertEqual(self.client.get("/api/v1/sources").status_code, 401)

    def test_filter_pagination_and_fresh_client_persistence(self):
        for suffix in ("a", "b", "c"):
            self.create(suffix)
        args = {"q": self.prefix, "category": "test", "language": "zh", "page_size": 2}
        first = self.client.get("/api/v1/sources", params=args).json()
        self.assertEqual(first["total"], 3)
        self.assertEqual(len(first["items"]), 2)
        with TestClient(self.app) as fresh:
            second = fresh.get(
                "/api/v1/sources", params={**args, "cursor": first["next_cursor"]}
            ).json()
        self.assertEqual(
            [r["source_id"] for r in first["items"] + second["items"]],
            [self.prefix + c for c in "abc"],
        )
        self.assertIsNone(second["next_cursor"])
        self.assertEqual(
            self.client.get(
                "/api/v1/sources",
                params={**args, "language": "en", "cursor": first["next_cursor"]},
            ).status_code,
            422,
        )

    def test_reader_denied_api_and_direct_rls_release_write_denied(self):
        source = self.create()
        self.actor = self.reader
        self.assertEqual(
            self.client.post(
                "/api/v1/admin/catalog",
                headers={"Idempotency-Key": "reader"},
                json={"source_id": self.prefix + "no", **self.metadata},
            ).status_code,
            403,
        )
        with transaction(self.reader.id) as session:
            changed = session.execute(
                text(
                    "UPDATE app.catalog_sources SET revision=revision+1 WHERE source_id=:id"
                ),
                {"id": source["source_id"]},
            )
            self.assertEqual(changed.rowcount, 0)
        with self.assertRaises(DBAPIError), transaction(self.admin.id) as session:
            session.execute(
                text(
                    "INSERT INTO app.catalog_releases(release_id,source_id,version,published_at,manifest_sha256) VALUES(:rid,:id,'fake',now(),:sha)"
                ),
                {"rid": uuid4(), "id": source["source_id"], "sha": "0" * 64},
            )
        with transaction() as session:
            self.assertEqual(list(session.scalars(select(CatalogSource))), [])

    def test_concurrent_idempotent_create_and_conflict(self):
        body = CatalogCreate(source_id=self.prefix, **self.metadata)

        def create(_):
            return catalog.create_catalog(body, self.admin, "same-create").model_dump(
                mode="json"
            )

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(create, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(
            self.client.post(
                "/api/v1/admin/catalog",
                headers={"Idempotency-Key": "same-create"},
                json={**body.model_dump(), "name": "different"},
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/admin/catalog",
                headers={"Idempotency-Key": "other-create"},
                json=body.model_dump(),
            ).status_code,
            409,
        )

    def test_two_admin_revision_race_and_replayed_update(self):
        self.create()

        def update(actor):
            try:
                return catalog.update_catalog(
                    self.prefix,
                    CatalogUpdate(**self.metadata, expected_revision=1),
                    actor,
                    "race",
                ).revision
            except ApiError as exc:
                return exc.code

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(update, [self.admin, self.admin2]))
        self.assertCountEqual(results, [2, "REVISION_CONFLICT"])
        winner = self.admin if results[0] == 2 else self.admin2
        replay = catalog.update_catalog(
            self.prefix,
            CatalogUpdate(**self.metadata, expected_revision=1),
            winner,
            "race",
        )
        self.assertEqual(replay.revision, 2)

    def test_demoted_admin_snapshot_cannot_mutate_or_replay(self):
        self.create(key="old")
        with self.admin_db.begin() as conn:
            conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": "actor:" + str(self.admin.id)},
            )
            conn.execute(
                text("UPDATE app.users SET is_platform_admin=false WHERE id=:id"),
                {"id": self.admin.id},
            )
        response = self.client.post(
            "/api/v1/admin/catalog",
            headers={"Idempotency-Key": "old"},
            json={"source_id": self.prefix, **self.metadata},
        )
        self.assertEqual(response.status_code, 403)
        with transaction(self.admin.id) as session:
            self.assertEqual(
                session.scalar(text("SELECT count(*) FROM app.catalog_actions")), 0
            )

    def test_identity_edit_clears_old_experiment_evidence(self):
        self.create()
        with self.admin_db.begin() as conn:
            conn.execute(
                text(
                    "UPDATE app.catalog_sources SET integration_status='experimental_evidence',evidence_refs='[\"old-evidence\"]' WHERE source_id=:id"
                ),
                {"id": self.prefix},
            )
        description = {
            **self.metadata,
            "boundary": "Updated boundary",
            "expected_revision": 1,
        }
        first = self.client.patch(
            f"/api/v1/admin/catalog/{self.prefix}",
            headers={"Idempotency-Key": "description"},
            json=description,
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["evidence_refs"], ["old-evidence"])
        second = self.client.patch(
            f"/api/v1/admin/catalog/{self.prefix}",
            headers={"Idempotency-Key": "identity"},
            json={**description, "name": "Different source", "expected_revision": 2},
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["evidence_refs"], [])
        self.assertEqual(second.json()["integration_status"], "catalog_only")
