"""Real fixed-object TXT revisions, project indexes and file-level query counts."""

import hashlib
import io
import os
import shutil
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from services.api import (
    agent_checkpoints,
    agent_control,
    agent_internal,
    agent_routes,
    agent_tools,
    jobs,
    materials,
    projects,
    research,
    storage,
    uploads,
)
from services.api.db import bound_transaction, transaction
from services.api.errors import ApiError
from services.api.job_models import Job, Upload
from services.api.material_models import MaterialRevision
from tests.integration import test_research_queries as shared
from tests.integration.test_research_queries import query, worker_role
from tests.integration.test_source_sync_pipeline import ENABLED
from workers import dispatcher, validation
from workers import materials as importer
from workers import research as query_worker


@unittest.skipUnless(ENABLED and shutil.which("cwb-encode"), "Real PG/S3/CWB required")
class PrivateMaterialTests(unittest.TestCase):
    setUpClass = classmethod(shared.ResearchTests.setUpClass.__func__)
    tearDownClass = classmethod(shared.ResearchTests.tearDownClass.__func__)
    policy = classmethod(shared.ResearchTests.policy.__func__)
    setUp = shared.ResearchTests.setUp
    start = shared.ResearchTests.start
    full = shared.ResearchTests.full
    page = shared.ResearchTests.page

    def uploaded(self, raw=b"Hello.\r\nHello!", *, actor=None, project=None):
        actor = actor or self.owner
        project = project or self.project
        value = uploads.create_upload(
            project,
            uploads.CreateUpload(
                filename="private.txt",
                size=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                media_type="text/plain",
            ),
            actor,
            uuid4().hex,
        )
        ident = UUID(value["upload_id"])
        with transaction(actor.id) as db:
            upload = db.get(Upload, ident)
            version, etag = storage.put_private(
                upload.object_key, io.BytesIO(raw), len(raw), "text/plain"
            )
            upload.version_id, upload.etag, upload.state = version, etag, "UPLOADED"
        action = uploads.complete_upload(ident, jobs.EmptyBody(), actor, uuid4().hex)
        with worker_role():
            self.assertEqual(
                validation.validate_upload(action["job_id"], 1)["status"], "published"
            )
        return ident

    def imported(self, upload=None, language="eng"):
        upload = upload or self.uploaded()
        value = materials.start_import(
            self.project,
            materials.ImportInput(upload_id=upload, language=language),
            self.owner,
            uuid4().hex,
        )
        with worker_role():
            self.assertEqual(
                importer.execute(value["job_id"], 1)["status"], "published"
            )
        return materials.get_import(self.project, UUID(value["job_id"]), self.viewer)

    def prepared(self, revisions, *, shared=False):
        value = research.create_snapshot(
            self.project,
            research.SnapshotInput(
                mount_ids=[self.mount] if shared else [],
                material_revision_ids=[UUID(r) for r in revisions],
            ),
            self.owner,
            uuid4().hex,
        )
        with worker_role():
            self.assertEqual(
                query_worker.execute(value["job_id"], 1)["status"], "complete"
            )
        ident = UUID(value["snapshot"]["id"])
        return research.get_snapshot(self.project, ident, self.viewer)

    def test_real_private_and_mixed_counts_unicode_and_complete_document_offsets(self):
        raw = b"\xef\xbb\xbf" + "Hello.\r\nHello 😀 é.\nHello!".encode()
        first = self.imported(self.uploaded(raw))
        second = self.imported()
        private = self.prepared([first["result"]["id"], second["result"]["id"]])
        self.assertEqual(private["counts"]["documents"], 2)
        self.assertEqual(
            private["counts"]["document_units"],
            {"source_records": 0, "private_files": 2},
        )
        value = self.start(UUID(private["id"]), size=2)
        completed = self.full(value)
        self.assertEqual(
            (
                completed["total_hits"],
                completed["matched_segments"],
                completed["matched_documents"],
            ),
            (5, 5, 2),
        )
        self.assertEqual(
            completed["matched_document_units"],
            {"source_records": 0, "private_files": 2},
        )
        hits = []
        cursor = None
        while True:
            page = self.page(value, cursor)
            hits.extend(page["hits"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        text_by_doc = {
            first["material_id"]: raw.decode("utf-8-sig"),
            second["material_id"]: "Hello.\r\nHello!",
        }
        for hit in hits:
            self.assertEqual(
                text_by_doc[hit["document_id"]][hit["start_cp"] : hit["end_cp"]],
                "Hello",
            )
            self.assertIsNone(hit["source_sentence_id"])
            self.assertIsNone(hit["source_url"])
            detail = research.context(
                self.project,
                UUID(value["result_set_id"]),
                hit["hit_ref"]["ordinal"],
                self.viewer,
            )
            self.assertEqual(
                detail["text"][
                    detail["start_cp"] - detail["context_start_cp"] : detail["end_cp"]
                    - detail["context_start_cp"]
                ],
                "Hello",
            )
        self.assertTrue(any(h["context_start_cp"] > 0 for h in hits))
        mixed = self.prepared(
            [first["result"]["id"], second["result"]["id"]], shared=True
        )
        value = self.start(UUID(mixed["id"]), ast=query(unit="token"))
        completed = self.full(value)
        self.assertEqual(
            (
                completed["total_hits"],
                completed["matched_segments"],
                completed["matched_documents"],
            ),
            (125, 65, 62),
        )
        self.assertEqual(
            completed["matched_document_units"],
            {"source_records": 60, "private_files": 2},
        )
        self.policy("deny")
        with self.assertRaises(ApiError):
            self.page(value)
        self.policy("allow")

    def test_language_correction_is_new_revision_and_old_snapshot_stays_fixed(self):
        upload = self.uploaded()
        first = self.imported(upload)
        snapshot = self.prepared([first["result"]["id"]])
        again = materials.start_import(
            self.project,
            materials.ImportInput(upload_id=upload, language="eng"),
            self.owner,
            uuid4().hex,
        )
        self.assertEqual(again["job_id"], first["job_id"])
        corrected = self.imported(upload, "cmn")
        self.assertEqual(corrected["material_id"], first["material_id"])
        self.assertNotEqual(corrected["result"]["id"], first["result"]["id"])
        material = materials.get_material(
            self.project, UUID(first["material_id"]), self.viewer
        )
        self.assertEqual(len(material["revisions"]), 2)
        self.assertEqual(
            research.get_snapshot(self.project, UUID(snapshot["id"]), self.viewer)[
                "members"
            ][0]["material_revision_id"],
            first["result"]["id"],
        )
        with self.assertRaises(ApiError) as error:
            self.prepared([first["result"]["id"], corrected["result"]["id"]])
        self.assertEqual(error.exception.code, "MATERIAL_REVISION_CONFLICT")

    def test_project_rls_cross_project_revision_and_pi_metadata(self):
        upload = self.uploaded()
        with self.assertRaises(ApiError):
            materials.start_import(
                self.project,
                materials.ImportInput(upload_id=upload, language="eng"),
                self.viewer,
                uuid4().hex,
            )
        imported = self.imported(upload)
        revision = UUID(imported["result"]["id"])
        for actor in (self.admin, self.outsider):
            with transaction(actor.id) as db:
                self.assertEqual(
                    db.scalar(
                        text(
                            "SELECT count(*) FROM app.material_revisions WHERE id=:id"
                        ),
                        {"id": revision},
                    ),
                    0,
                )
        with self.assertRaises(DBAPIError), transaction(self.viewer.id) as db:
            db.execute(
                text(
                    "INSERT INTO app.material_revisions SELECT * FROM app.material_revisions WHERE id=:id"
                ),
                {"id": revision},
            )
        other = projects.create_project(
            projects.ProjectInput(name="Other"), self.owner
        ).id
        with self.assertRaises(ApiError):
            research.create_snapshot(
                other,
                research.SnapshotInput(material_revision_ids=[revision]),
                self.owner,
                uuid4().hex,
            )
        scope = {
            "scope_kind": "project",
            "project_id": str(self.project),
            "snapshot_ids": [],
            "material_revision_ids": [],
            "alignment_overlay_revision": None,
        }
        with transaction(self.viewer.id) as db, bound_transaction(self.viewer.id, db):
            value = agent_tools.dispatch(
                db,
                self.viewer,
                scope,
                "materials.get",
                {"material_id": imported["material_id"]},
                uuid4(),
            )
        self.assertNotIn("name", value)
        self.assertNotIn("quality", value)
        self.assertNotIn("counts", value)

    def test_wrong_worker_kind_and_cancel_retry_queued_do_not_change_validated_upload(
        self,
    ):
        upload = self.uploaded()
        value = materials.start_import(
            self.project,
            materials.ImportInput(upload_id=upload, language="eng"),
            self.owner,
            uuid4().hex,
        )
        with worker_role():
            self.assertEqual(
                validation.validate_upload(value["job_id"], 1)["status"],
                "duplicate_or_ineligible",
            )
        with (
            worker_role(),
            patch(
                "pipelines.materials.txt.parse_txt",
                side_effect=OSError("controlled transient"),
            ),
        ):
            self.assertEqual(importer.execute(value["job_id"], 1)["status"], "failed")
        jobs.retry(UUID(value["job_id"]), jobs.EmptyBody(), self.owner, uuid4().hex)
        with worker_role(), patch.object(dispatcher.app, "send_task") as send:
            dispatcher.send(UUID(value["job_id"]), 2)
            self.assertEqual(send.call_args.args[0], "workers.import_txt")
            self.assertEqual(send.call_args.kwargs["queue"], "corpus.index")
        # A later queued attempt also releases its reservation when delivery fails.
        with worker_role(), transaction() as db:
            row = db.get(Job, UUID(value["job_id"]))
            jobs.finish_failure(
                db, row, "DELIVERY_FAILED", "Controlled delivery failure", True
            )
            self.assertEqual(row.reserved_bytes, 0)
        jobs.retry(UUID(value["job_id"]), jobs.EmptyBody(), self.owner, uuid4().hex)
        jobs.cancel(UUID(value["job_id"]), jobs.EmptyBody(), self.owner, uuid4().hex)
        with transaction(self.owner.id) as db:
            self.assertEqual(db.get(Job, UUID(value["job_id"])).reserved_bytes, 0)
            self.assertEqual(db.get(Upload, upload).state, "VALIDATED")

    def test_commit_ack_loss_preserves_registered_versions(self):
        upload = self.uploaded()
        value = materials.start_import(
            self.project,
            materials.ImportInput(upload_id=upload, language="eng"),
            self.owner,
            uuid4().hex,
        )
        original = importer.publish

        def lost(*args):
            self.assertTrue(original(*args))
            raise OSError("controlled commit acknowledgement loss")

        with worker_role(), patch.object(importer, "publish", side_effect=lost):
            importer.execute(value["job_id"], 1)
        current = materials.get_import(self.project, UUID(value["job_id"]), self.viewer)
        self.assertEqual(current["state"], "SUCCEEDED")
        with transaction(self.owner.id) as db:
            row = db.get(MaterialRevision, UUID(current["result"]["id"]))
            objects = row.objects
        for item in objects:
            stream = storage.read_private(
                item["object_key"], item["version_id"], item["etag"]
            )
            try:
                self.assertEqual(
                    hashlib.sha256(stream.read()).hexdigest(), item["sha256"]
                )
            finally:
                stream.close()

    def test_unknown_put_holds_reservation_and_disables_retry(self):
        upload = self.uploaded()
        value = materials.start_import(
            self.project,
            materials.ImportInput(upload_id=upload, language="eng"),
            self.owner,
            uuid4().hex,
        )
        original = storage.put_private

        def lost(*args):
            original(*args)
            raise TimeoutError("controlled upload acknowledgement loss")

        with worker_role(), patch.object(storage, "put_private", side_effect=lost):
            importer.execute(value["job_id"], 1)
        current = materials.get_import(self.project, UUID(value["job_id"]), self.viewer)
        self.assertEqual(current["error"]["code"], "IMPORT_CLEANUP_REQUIRED")
        self.assertFalse(current["allowed_actions"]["retry"])
        with transaction(self.owner.id) as db:
            self.assertGreater(db.get(Job, UUID(value["job_id"])).reserved_bytes, 0)

    def test_withdrawal_after_storage_never_publishes_revision_or_changes_raw(self):
        upload = self.uploaded()
        value = materials.start_import(
            self.project,
            materials.ImportInput(upload_id=upload, language="eng"),
            self.owner,
            uuid4().hex,
        )
        original = importer.publish
        api_url = os.environ["DATABASE_URL"]

        def cancel(*args):
            with patch.dict(os.environ, {"DATABASE_URL": api_url}):
                jobs.cancel(
                    UUID(value["job_id"]), jobs.EmptyBody(), self.owner, uuid4().hex
                )
            return original(*args)

        with worker_role(), patch.object(importer, "publish", side_effect=cancel):
            importer.execute(value["job_id"], 1)
        with transaction(self.owner.id) as db:
            self.assertIsNone(
                db.scalar(
                    select(MaterialRevision).where(
                        MaterialRevision.import_id == UUID(value["job_id"])
                    )
                )
            )
            self.assertEqual(db.get(Upload, upload).state, "VALIDATED")
            self.assertEqual(db.get(Job, UUID(value["job_id"])).reserved_bytes, 0)

    def test_worker_global_quota_sees_two_mutually_private_projects(self):
        other = projects.create_project(
            projects.ProjectInput(name="Other owner"), self.outsider
        ).id
        first = self.uploaded()
        second = self.uploaded(actor=self.outsider, project=other)
        amount = 256 * 1024**2
        with worker_role(), transaction() as db:
            baseline = sum(
                sum(x["bytes"] for x in row.objects)
                for row in db.scalars(select(MaterialRevision))
            ) + sum(
                row.reserved_bytes
                for row in db.scalars(
                    select(Job).where(Job.kind == "TXT_IMPORT", Job.state != "QUEUED")
                )
            )
        with patch.dict(
            os.environ,
            {
                "MATERIAL_STORAGE_MAX_BYTES": str(baseline + amount),
                "MATERIAL_IMPORT_MAX_BYTES": str(amount),
            },
        ):
            a = materials.start_import(
                self.project,
                materials.ImportInput(upload_id=first, language="eng"),
                self.owner,
                uuid4().hex,
            )
            b = materials.start_import(
                other,
                materials.ImportInput(upload_id=second, language="eng"),
                self.outsider,
                uuid4().hex,
            )
            # API RLS cannot see the other owner's queued task; worker must make the final decision.
            with worker_role():
                first_lease = importer.claim(UUID(a["job_id"]), 1)
                self.assertIsNotNone(first_lease)
                self.assertIsNone(importer.claim(UUID(b["job_id"]), 1))
                with transaction() as db:
                    row = db.get(Job, UUID(a["job_id"]))
                    jobs.finish_failure(
                        db, row, "TEST_FINISHED", "Claim only, no object created."
                    )
                    row.reserved_bytes = 0
        self.assertEqual(
            materials.get_import(other, UUID(b["job_id"]), self.outsider)["error"][
                "code"
            ],
            "MATERIAL_QUOTA_EXCEEDED",
        )

    @patch.dict(os.environ, {"AGENT_RUNTIME_MODE": "fixture"})
    def test_pi_import_pending_and_exact_revision_observation_gate(self):
        upload = self.uploaded()
        owner = agent_control.create_session(
            self.owner.id,
            {
                "scope_kind": "project",
                "project_id": str(self.project),
                "snapshot_ids": [],
                "material_revision_ids": [],
                "alignment_overlay_revision": None,
                "result_refs": [],
            },
        )
        started = agent_control.create_run(
            self.owner.id,
            UUID(owner["session_id"]),
            uuid4(),
            "Fixture request",
            owner["scope_digest"],
        )
        run_id = UUID(started["run_id"])
        token = agent_control.claim(run_id, uuid4())["execution_token"]

        def invoke(tool, arguments):
            with agent_control.execution(run_id, token) as (
                db,
                session,
                run,
                actor,
                tools,
            ):
                return agent_control.invoke(
                    db,
                    session,
                    run,
                    actor,
                    tools,
                    agent_internal.InvocationInput(
                        request_key=uuid4(),
                        tool_call_id=uuid4().hex,
                        tool_name=tool,
                        arguments=arguments,
                    ),
                )

        accepted = invoke(
            "imports.start", {"upload_id": str(upload), "language": "eng"}
        )
        self.assertEqual(accepted["result"]["status"], "accepted")
        with (
            self.assertRaises(ApiError) as pending,
            agent_control.execution(run_id, token) as (db, _, run, _, _),
        ):
            agent_checkpoints.necessary_results(db, run)
        self.assertEqual(pending.exception.code, "JOBS_PENDING")
        with worker_role():
            self.assertEqual(
                importer.execute(accepted["result"]["job_id"], 1)["status"], "published"
            )
        with (
            self.assertRaises(ApiError) as unobserved,
            agent_control.execution(run_id, token) as (db, _, run, _, _),
        ):
            agent_checkpoints.necessary_results(db, run)
        self.assertEqual(unobserved.exception.code, "JOB_RESULT_NOT_OBSERVED")
        observed = invoke("imports.get", {"import_id": accepted["result"]["job_id"]})
        self.assertIsNotNone(observed["data"]["material_revision_id"])
        self.assertNotIn("filename", observed["data"])
        with agent_control.execution(run_id, token) as (db, _, run, _, _):
            agent_checkpoints.necessary_results(db, run)

    @patch.dict(os.environ, {"AGENT_RUNTIME_MODE": "fixture"})
    def test_agent_cancel_only_its_new_import_not_reused_job(self):
        def call(upload):
            session = agent_control.create_session(
                self.owner.id,
                {
                    "scope_kind": "project",
                    "project_id": str(self.project),
                    "snapshot_ids": [],
                    "material_revision_ids": [],
                    "alignment_overlay_revision": None,
                    "result_refs": [],
                },
            )
            started = agent_control.create_run(
                self.owner.id,
                UUID(session["session_id"]),
                uuid4(),
                "Fixture request",
                session["scope_digest"],
            )
            run_id = UUID(started["run_id"])
            token = agent_control.claim(run_id, uuid4())["execution_token"]
            with agent_control.execution(run_id, token) as (
                db,
                owner,
                run,
                actor,
                tools,
            ):
                response = agent_control.invoke(
                    db,
                    owner,
                    run,
                    actor,
                    tools,
                    agent_internal.InvocationInput(
                        request_key=uuid4(),
                        tool_call_id=uuid4().hex,
                        tool_name="imports.start",
                        arguments={"upload_id": str(upload), "language": "eng"},
                    ),
                )
            self.assertEqual(response["result"]["status"], "accepted")
            return run_id, UUID(response["result"]["job_id"])

        upload = self.uploaded()
        run_id, job_id = call(upload)
        self.assertEqual(
            agent_routes.cancel(run_id, jobs.EmptyBody(), self.owner)["state"],
            "CANCELLED",
        )
        with transaction(self.owner.id) as db:
            self.assertEqual(db.get(Job, job_id).state, "CANCELLED")
            self.assertEqual(db.get(Job, job_id).reserved_bytes, 0)
            self.assertEqual(db.get(Upload, upload).state, "VALIDATED")
        other_upload = self.uploaded()
        existing = materials.start_import(
            self.project,
            materials.ImportInput(upload_id=other_upload, language="eng"),
            self.owner,
            uuid4().hex,
        )
        run_id, reused = call(other_upload)
        self.assertEqual(str(reused), existing["job_id"])
        agent_routes.cancel(run_id, jobs.EmptyBody(), self.owner)
        with transaction(self.owner.id) as db:
            self.assertEqual(db.get(Job, reused).state, "QUEUED")
            self.assertGreater(db.get(Job, reused).reserved_bytes, 0)
            self.assertEqual(db.get(Upload, other_upload).state, "VALIDATED")
        jobs.cancel(reused, jobs.EmptyBody(), self.owner, uuid4().hex)
