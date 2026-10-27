"""Real PG/RLS/private S3 publication with actual tiny parser/CWB artifacts."""

import copy
import io
import os
import secrets
import shutil
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from scripts import release_fixture
from services.api import agent_checkpoints, agent_control, catalog, projects, storage
from services.api import source_mounts as mounts
from services.api import source_releases as releases
from services.api.agent_internal import InvocationInput
from services.api.auth import Actor
from services.api.catalog_models import CatalogSource
from services.api.db import transaction
from services.api.errors import ApiError
from services.api.index_models import SourceIndex
from services.api.jobs import EmptyBody
from tests.integration.test_source_sync_pipeline import ENABLED


@unittest.skipUnless(ENABLED and shutil.which("cwb-encode"), "Real PG/S3/CWB required")
class SourceReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = {"source_id": "fixture-release-" + uuid4().hex, "accounts": {}}
        for name in ("admin", "owner", "editor", "viewer", "outsider"):
            cls.body["accounts"][name] = {
                "id": str(uuid4()),
                "email": f"release-{uuid4().hex}@example.test",
                "password": secrets.token_urlsafe(24),
            }
        cls.engine = release_fixture.engine()
        try:
            cls.fixture = release_fixture.setup(cls.body)
            for name, value in cls.body["accounts"].items():
                setattr(
                    cls,
                    name,
                    Actor(UUID(value["id"]), value["email"], name == "admin", ""),
                )
            cls.project = projects.create_project(
                projects.ProjectInput(name="Release fixture project"), cls.owner
            ).id
            cls.second_project = projects.create_project(
                projects.ProjectInput(name="Release fixture second"), cls.owner
            ).id
            for name in ("editor", "viewer"):
                projects.set_member(
                    cls.project,
                    getattr(cls, name).id,
                    projects.MemberInput(role=name),
                    cls.owner,
                )
        except BaseException:
            release_fixture.cleanup(cls.body)
            raise

    @classmethod
    def tearDownClass(cls):
        release_fixture.cleanup(cls.body)
        cls.engine.dispose()

    def setUp(self):
        self.source = self.fixture["source_id"]
        self.first, self.second = self.fixture["versions"]
        with self.engine.begin() as db:
            args = {
                "source": self.source,
                "ids": [UUID(x["id"]) for x in self.body["accounts"].values()],
            }
            for statement in (
                "DELETE FROM app.mount_actions WHERE actor_id=ANY(:ids)",
                "DELETE FROM app.project_source_mounts WHERE created_by=ANY(:ids)",
                "DELETE FROM app.source_release_heads WHERE source_id=:source",
                "DELETE FROM app.catalog_releases WHERE source_id=:source",
                "DELETE FROM app.source_policy_heads WHERE source_id=:source",
                "DELETE FROM app.source_policies WHERE source_id=:source",
                "DELETE FROM app.source_release_actions WHERE actor_id=ANY(:ids)",
            ):
                db.execute(text(statement), args)

    def policy(self, decision="allow", version=None, key=None):
        version = version or self.first
        ident = UUID(version["acquisition_id"])
        previous = releases.get_policy(self.source, ident, self.admin)
        return releases.update_policy(
            self.source,
            ident,
            releases.PolicyInput(
                expected_revision=previous["revision"],
                decision=decision,
                review_note="Explicit synthetic fixture only; no approval of real D12",
                evidence_urls=["https://example.test/authored-fixture"],
            ),
            self.admin,
            key or uuid4().hex,
        )

    def publish(self, version=None, key=None):
        version = version or self.first
        current = releases.get_policy(
            self.source, UUID(version["acquisition_id"]), self.admin
        )
        return releases.publish(
            self.source,
            releases.PublishInput(
                index_id=UUID(version["index_id"]),
                expected_policy_revision=current["revision"],
            ),
            self.admin,
            key or uuid4().hex,
        )

    def mounted(self, release=None, project=None, key=None):
        if release is None:
            self.policy()
            release = self.publish()["release"]
        return mounts.create(
            project or self.project,
            mounts.MountInput(source_snapshot_id=UUID(release["source_snapshot_id"])),
            self.owner,
            key or uuid4().hex,
        )

    def test_real_publish_concurrent_idempotency_and_project_rls(self):
        self.assertEqual(
            releases.get_policy(
                self.source, UUID(self.first["acquisition_id"]), self.admin
            )["decision"],
            "unknown",
        )
        with self.assertRaises(ApiError) as caught:
            releases.publish(
                self.source,
                releases.PublishInput(
                    index_id=UUID(self.first["index_id"]), expected_policy_revision=1
                ),
                self.admin,
                uuid4().hex,
            )
        self.assertEqual(caught.exception.code, "SOURCE_POLICY_DENIED")
        with self.assertRaises(ApiError):
            releases.get_policy(
                self.source, UUID(self.first["acquisition_id"]), self.owner
            )
        self.policy()
        key = uuid4().hex
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.publish(key=key), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertTrue(self.publish()["existing"])
        result = self.mounted(results[0]["release"])
        mid = UUID(result["mount"]["id"])
        actual = mounts.manifest(self.project, mid, self.viewer)
        self.assertEqual(actual["manifest"]["counts"]["sentences"], 4)
        self.assertNotIn("object_key", str(actual))
        self.assertEqual(
            len(catalog.source_versions(self.source, self.viewer, None, 50).items), 1
        )
        for actor in (self.admin, self.outsider):
            with self.subTest(actor=actor.id), self.assertRaises(ApiError):
                mounts.manifest(self.project, mid, actor)
            with transaction(actor.id) as db:
                self.assertEqual(
                    db.scalar(
                        text(
                            "SELECT count(*) FROM app.project_source_mounts WHERE id=:id"
                        ),
                        {"id": mid},
                    ),
                    0,
                )
        with transaction(self.outsider.id) as db:
            self.assertIsNone(db.get(SourceIndex, UUID(self.first["index_id"])))
        with transaction(self.viewer.id) as db:
            self.assertIsNotNone(db.get(SourceIndex, UUID(self.first["index_id"])))
            self.assertEqual(
                db.execute(
                    text(
                        "UPDATE app.project_source_mounts SET removed_at=now() WHERE id=:id"
                    ),
                    {"id": mid},
                ).rowcount,
                0,
            )
        with self.assertRaises(DBAPIError), transaction(self.viewer.id) as db:
            db.execute(
                text(
                    "INSERT INTO app.project_source_mounts(id,project_id,source_snapshot_id,created_by,created_at) VALUES(:id,:project,:snapshot,:actor,now())"
                ),
                {
                    "id": uuid4(),
                    "project": self.project,
                    "snapshot": UUID(result["mount"]["release"]["source_snapshot_id"]),
                    "actor": self.viewer.id,
                },
            )
        with self.assertRaises(ApiError):
            mounts.remove(self.project, mid, EmptyBody(), self.viewer, uuid4().hex)

    def test_policy_withdrawal_blocks_reads_reuse_and_old_success_replay(self):
        policy_key, mount_key, publish_key = (uuid4().hex for _ in range(3))
        approved = self.policy(key=policy_key)
        release = self.publish(key=publish_key)["release"]
        result = self.mounted(release, key=mount_key)
        mid = UUID(result["mount"]["id"])
        self.policy("deny")
        for call in (
            lambda: mounts.manifest(self.project, mid, self.viewer),
            lambda: self.mounted(release, key=mount_key),
            lambda: self.mounted(release),
            lambda: self.publish(key=publish_key),
            lambda: releases.update_policy(
                self.source,
                UUID(self.first["acquisition_id"]),
                releases.PolicyInput(
                    expected_revision=0,
                    decision="allow",
                    review_note=approved["policy"]["review_note"],
                    evidence_urls=approved["policy"]["evidence_urls"],
                ),
                self.admin,
                policy_key,
            ),
        ):
            with self.assertRaises(ApiError):
                call()
        with transaction(self.viewer.id) as db:
            self.assertIsNone(db.get(SourceIndex, UUID(self.first["index_id"])))
        self.assertFalse(
            mounts.get_mount(self.project, mid, self.viewer)["allowed_actions"][
                "read_manifest"
            ]
        )
        self.policy("allow")
        replay = self.mounted(release, key=mount_key)
        self.assertEqual(replay["mount"]["release"]["current_policy_revision"], 3)
        mounts.remove(self.project, mid, EmptyBody(), self.editor, uuid4().hex)
        with self.assertRaises(ApiError):
            self.mounted(release, key=mount_key)

    def test_source_identity_edit_and_restore_requires_new_explicit_approval(self):
        result = self.mounted()
        mid = UUID(result["mount"]["id"])
        with transaction(self.admin.id) as db:
            source = db.get(CatalogSource, self.source)
            original, revision = dict(source.metadata_json), source.revision
        catalog.update_catalog(
            self.source,
            catalog.CatalogUpdate(
                **{**original, "name": original["name"] + " changed"},
                expected_revision=revision,
            ),
            self.admin,
            uuid4().hex,
        )
        with self.assertRaises(ApiError):
            mounts.manifest(self.project, mid, self.viewer)
        catalog.update_catalog(
            self.source,
            catalog.CatalogUpdate(**original, expected_revision=revision + 1),
            self.admin,
            uuid4().hex,
        )
        with self.assertRaises(ApiError):
            mounts.manifest(self.project, mid, self.viewer)
        self.policy()
        self.assertEqual(
            mounts.manifest(self.project, mid, self.viewer)["manifest_sha256"],
            self.first["manifest_sha256"],
        )

    def test_new_release_never_upgrades_old_mount_and_remove_is_historical(self):
        first = self.mounted()
        second_project = self.mounted(first["mount"]["release"], self.second_project)
        self.policy(version=self.second)
        second = self.publish(self.second)["release"]
        self.assertNotEqual(
            second["source_snapshot_id"],
            first["mount"]["release"]["source_snapshot_id"],
        )
        before = mounts.get_mount(self.project, UUID(first["mount"]["id"]), self.viewer)
        self.assertEqual(before["release"]["index_id"], self.first["index_id"])
        self.assertEqual(
            mounts.get_mount(
                self.second_project, UUID(second_project["mount"]["id"]), self.owner
            )["release"]["index_id"],
            self.first["index_id"],
        )
        mounts.remove(
            self.project,
            UUID(first["mount"]["id"]),
            EmptyBody(),
            self.owner,
            uuid4().hex,
        )
        newer = self.mounted(first["mount"]["release"])
        self.assertNotEqual(newer["mount"]["id"], first["mount"]["id"])
        listing = mounts.list_mounts(self.project, self.viewer, None, 50)
        self.assertEqual(listing["total"], 2)
        self.assertEqual({x["state"] for x in listing["items"]}, {"ACTIVE", "REMOVED"})

    def test_missing_object_and_manifest_mismatch_leave_no_publication(self):
        self.policy()
        with transaction(self.admin.id) as db:
            original = copy.deepcopy(
                db.get(SourceIndex, UUID(self.first["index_id"])).objects
            )
        corrupt_key = f"release-fixture/{self.source}/corrupt-manifest"
        version, etag = storage.put_private(
            corrupt_key, io.BytesIO(b"{}"), 2, "application/json"
        )
        for mode in ("missing", "corrupt"):
            changed = copy.deepcopy(original)
            item = next(x for x in changed if x["name"] == "manifest.json")
            if mode == "missing":
                item["version_id"] = str(uuid4())
            else:
                item.update(
                    object_key=corrupt_key, version_id=version, etag=etag, bytes=2
                )
            try:
                with self.engine.begin() as db:
                    db.execute(
                        text(
                            "UPDATE app.source_indexes SET objects=CAST(:objects AS jsonb) WHERE id=:id"
                        ),
                        {
                            "id": UUID(self.first["index_id"]),
                            "objects": __import__("json").dumps(changed),
                        },
                    )
                with self.assertRaises(ApiError) as caught:
                    self.publish()
                self.assertEqual(caught.exception.code, "RELEASE_OBJECT_UNAVAILABLE")
                with self.engine.connect() as db:
                    for table in ("catalog_releases", "source_release_heads"):
                        self.assertEqual(
                            db.scalar(
                                text(
                                    f"SELECT count(*) FROM app.{table} WHERE source_id=:id"
                                ),
                                {"id": self.source},
                            ),
                            0,
                        )
            finally:
                with self.engine.begin() as db:
                    db.execute(
                        text(
                            "UPDATE app.source_indexes SET objects=CAST(:objects AS jsonb) WHERE id=:id"
                        ),
                        {
                            "id": UUID(self.first["index_id"]),
                            "objects": __import__("json").dumps(original),
                        },
                    )

    @patch.dict(os.environ, {"AGENT_RUNTIME_MODE": "fixture"})
    def test_pi_manifest_replay_and_context_recheck_current_policy(self):
        mounted = self.mounted()
        scope = {
            "scope_kind": "project",
            "project_id": str(self.project),
            "snapshot_ids": [],
            "material_revision_ids": [],
            "alignment_overlay_revision": None,
        }
        session = agent_control.create_session(self.viewer.id, scope)
        run = agent_control.create_run(
            self.viewer.id,
            UUID(session["session_id"]),
            uuid4(),
            "Fixture request",
            session["scope_digest"],
        )
        rid = UUID(run["run_id"])
        grant = agent_control.claim(rid, uuid4())
        body = InvocationInput(
            request_key=uuid4(),
            tool_call_id=uuid4().hex,
            tool_name="mounts.manifest",
            arguments={"mount_id": mounted["mount"]["id"]},
        )

        def invoke():
            with agent_control.execution(rid, grant["execution_token"]) as args:
                return agent_control.invoke(*args, body)

        first = invoke()
        self.assertEqual(first["result"]["status"], "succeeded")
        self.assertEqual(invoke(), first)
        self.policy("deny")
        with self.assertRaises(ApiError):
            invoke()
        with (
            self.assertRaises(ApiError) as caught,
            agent_control.execution(rid, grant["execution_token"]) as (
                db,
                owner,
                current,
                _,
                tools,
            ),
        ):
            agent_checkpoints.check_context(db, owner, current, tools)
        self.assertEqual(caught.exception.code, "CHECKPOINT_AUTH_CHANGED")


if __name__ == "__main__":
    unittest.main()
