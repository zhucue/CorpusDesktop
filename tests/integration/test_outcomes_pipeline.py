"""Real PG/S3 immutable evidence, notes and complete authorized exports."""
import asyncio
import csv
import hashlib
import io
import json
import os
import shutil
import unittest
import zipfile
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import text

from contracts.outcomes import (
    EvidenceInput,
    ExportInput,
    NoteAccept,
    NoteInput,
    NoteUpdate,
)
from services.api import jobs, outcomes, projects, source_releases, storage
from services.api.db import transaction
from services.api.errors import ApiError
from services.api.job_models import Job
from services.api.outcome_models import ExportRecord
from tests.integration import test_private_materials as private
from tests.integration import test_research_queries as shared
from tests.integration.test_research_queries import query, worker_role
from tests.integration.test_source_sync_pipeline import ENABLED


@unittest.skipUnless(ENABLED and shutil.which('cwb-encode'), 'Real PG/S3/CWB required')
class OutcomeTests(unittest.TestCase):
    setUpClass = classmethod(shared.ResearchTests.setUpClass.__func__)
    tearDownClass = classmethod(shared.ResearchTests.tearDownClass.__func__)
    policy = classmethod(shared.ResearchTests.policy.__func__)
    setUp = shared.ResearchTests.setUp
    start = shared.ResearchTests.start
    full = shared.ResearchTests.full
    page = shared.ResearchTests.page
    snapshot = shared.ResearchTests.snapshot
    uploaded = private.PrivateMaterialTests.uploaded
    imported = private.PrivateMaterialTests.imported
    prepared = private.PrivateMaterialTests.prepared

    def export_policy(self, decision):
        current = source_releases.get_policy(self.source, self.acquisition, self.admin)
        return source_releases.update_policy(
            self.source, self.acquisition,
            source_releases.PolicyInput(expected_revision=current['revision'], decision='allow',
                                        export_decision=decision, review_note='Authored fixture export only',
                                        evidence_urls=['https://example.test/authored-fixture']),
            self.admin, uuid4().hex)

    def completed(self, snapshot=None, value='Hello', unit='character'):
        action = self.start(snapshot or self.snapshot(), ast=query(value, unit))
        self.full(action)
        return action

    def evidence(self, run, ordinal=0, actor=None):
        return outcomes.create_evidence(self.project,
            EvidenceInput(result_set_id=UUID(run['result_set_id']), ordinal=ordinal),
            actor or self.owner, uuid4().hex)['evidence']

    def create_export(self, runs=None, *, note=None, format='json', actor=None, key=None):
        from services.api import exports
        target = {'kind':'note_revision','note_id':note['id'],'revision':note['revision']} if note else {
            'kind':'query_runs','query_run_ids':[r['query_run_id'] for r in runs]}
        return exports.create_export(self.project, ExportInput(target=target, format=format),
                                     actor or self.viewer, key or uuid4().hex)

    def generate(self, action):
        from services.api import exports
        from workers import exports as worker
        with worker_role():
            result = worker.execute(action['job_id'], 1)
        self.assertEqual(result['status'], 'published', result)
        return exports.get_export(self.project, UUID(action['export_id']), self.viewer)

    def download(self, action, actor=None):
        from services.api import exports
        response = exports.download_export(self.project, UUID(action['export_id']), actor or self.viewer)
        async def collect():
            return b''.join([part async for part in response.body_iterator])
        return asyncio.run(collect())

    def test_evidence_fixed_first_and_tail_full_coordinates_and_permissions(self):
        run = self.completed()
        first, last = self.evidence(run), self.evidence(run, 119)
        repeated = self.evidence(run, 119)
        self.assertEqual(last['id'], repeated['id'])
        self.assertEqual(last['hit_ref']['ordinal'], 119)
        self.assertEqual(last['method']['counts']['total_hits'], 120)
        for evidence in (first,last):
            detail = outcomes.get_evidence(self.project, UUID(evidence['id']), self.viewer)
            context = detail['context']
            self.assertEqual(context['text'][context['start_cp']-context['context_start_cp']:
                                             context['end_cp']-context['context_start_cp']], 'Hello')
        with self.assertRaises(ApiError):
            self.evidence(run, actor=self.viewer)
        with self.assertRaises(ApiError):
            outcomes.get_evidence(self.project, UUID(first['id']), self.outsider)
        other = projects.create_project(projects.ProjectInput(name='Other outcome project'), self.owner).id
        with self.assertRaises(ApiError):
            outcomes.get_evidence(other, UUID(first['id']), self.owner)
        self.policy('deny')
        with self.assertRaises(ApiError):
            outcomes.get_evidence(self.project, UUID(first['id']), self.viewer)

    def test_note_revision_conflict_manual_acceptance_and_inherited_dependencies(self):
        run = self.completed()
        evidence = self.evidence(run)
        first = outcomes.create_note(self.project,
            NoteInput(title='第一版',body='Hello 原始解释',evidence_ids=[UUID(evidence['id'])]),
            self.owner,uuid4().hex)['note']
        with self.assertRaises(ApiError) as missing:
            outcomes.accept_note(self.project, UUID(first['id']), NoteAccept(expected_revision=1), self.owner, uuid4().hex)
        self.assertEqual(missing.exception.code, 'HUMAN_AUTHORIZATION_REQUIRED')
        session_hash = hashlib.sha256(uuid4().bytes).hexdigest()
        with self.engine.begin() as db:
            db.execute(text('INSERT INTO app.login_sessions(token_hash,user_id,csrf_hash,expires_at) VALUES(:hash,:actor,:hash,:expires)'),
                       {'hash':session_hash,'actor':self.owner.id,'expires':jobs.now()+timedelta(hours=1)})
        manual = replace(self.owner, session_hash=session_hash)
        accepted = outcomes.accept_note(self.project,UUID(first['id']),NoteAccept(expected_revision=1),manual,uuid4().hex)['note']
        self.assertEqual(accepted['status'],'accepted')
        second = outcomes.update_note(self.project,UUID(first['id']),
            NoteUpdate(expected_revision=1,title='第二版',body='去掉显示引用仍保留授权依赖'),self.owner,uuid4().hex)['note']
        self.assertEqual(second['status'],'draft')
        self.assertEqual(second['authorization_evidence_ids'],[evidence['id']])
        old = outcomes.get_note(self.project,UUID(first['id']),self.viewer,1)
        self.assertEqual(old['body'],'Hello 原始解释')
        self.assertEqual(old['status'],'accepted')
        self.export_policy('allow')
        exported=self.create_export(note=first)
        self.generate(exported)
        note_row=json.loads(self.download(exported))['rows'][0]
        self.assertEqual(note_row['status'],'accepted')
        reference=note_row['evidence_refs'][0]
        self.assertEqual(reference['id'],evidence['id'])
        self.assertEqual(reference['context'],evidence['context'])
        self.assertEqual(reference['method'],evidence['method'])
        self.assertEqual(reference['attribution']['owner'],'Fixture')
        self.assertEqual(reference['attribution']['license'],'CC-BY-2.0-FR')
        self.assertEqual(reference['attribution']['source_id'],self.source)
        with self.assertRaises(ApiError) as conflict:
            outcomes.update_note(self.project,UUID(first['id']),
                NoteUpdate(expected_revision=1,title='冲突',body='不能覆写'),self.owner,uuid4().hex)
        self.assertEqual(conflict.exception.code,'NOTE_REVISION_CONFLICT')
        with self.assertRaises(ApiError):
            outcomes.create_note(self.project,NoteInput(title='viewer',body='no'),self.viewer,uuid4().hex)
        self.policy('deny')
        with self.assertRaises(ApiError):
            outcomes.get_note(self.project,UUID(first['id']),self.viewer,None)

    def test_complete_mixed_and_private_runs_csv_json_full_rows_and_attribution(self):
        first = self.imported(self.uploaded(b'\xef\xbb\xbf'+ 'Hello.\r\nHello 😀 é.\nHello!'.encode()))
        second = self.imported()
        revisions=[first['result']['id'],second['result']['id']]
        mixed = self.completed(UUID(self.prepared(revisions,shared=True)['id']))
        pure = self.completed(UUID(self.prepared(revisions)['id']))
        zero = self.completed(UUID(pure['run']['snapshot_id']),value='absent-phrase')
        self.export_policy('allow')
        outputs={}
        for format in ('json','csv'):
            action=self.create_export([mixed,zero,pure],format=format)
            completed=self.generate(action)
            raw=self.download(action)
            self.assertEqual(completed['result']['sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(completed['result']['row_count'],130)
            outputs[format]=raw
        data=json.loads(outputs['json'])
        self.assertEqual([q['counts']['total_hits'] for q in data['methods']['queries']],[125,0,5])
        rows=data['rows']
        self.assertEqual(len(rows),130)
        self.assertEqual(rows[125]['row_number'],1)
        source=[r for r in rows if r['origin_kind']=='source']
        private_rows=[r for r in rows if r['origin_kind']=='private']
        self.assertEqual(len(source),120)
        self.assertTrue(all(r['owner'] and r['license'] and r['source_url'] for r in source))
        self.assertTrue(all(r['source_url'] is None and r['owner'] is None for r in private_rows))
        self.assertTrue(any(r['context_start_cp']>0 for r in private_rows))
        with zipfile.ZipFile(io.BytesIO(outputs['csv'])) as package:
            self.assertEqual(set(package.namelist()),{'methods.json','results.csv'})
            table=list(csv.DictReader(io.StringIO(package.read('results.csv').decode(),newline='')))
        self.assertEqual(len(table),130)
        self.assertEqual(table[-1]['match'],"'Hello")
        self.assertEqual(table[-1]['start_cp'],str(rows[-1]['start_cp']))

    def test_export_permission_is_separate_and_download_rechecks_it(self):
        run=self.completed()
        with self.assertRaises(ApiError) as denied:
            self.create_export([run])
        self.assertEqual(denied.exception.code,'EXPORT_POLICY_DENIED')
        self.export_policy('allow')
        key=uuid4().hex
        action=self.create_export([run],key=key)
        replay=self.create_export([run],key=key)
        self.assertEqual(action['job_id'],replay['job_id'])
        self.generate(action)
        self.assertEqual(len(json.loads(self.download(action))['rows']),120)
        self.export_policy('deny')
        with self.assertRaises(ApiError):
            self.download(action)
        # Independent export denial does not revoke fulltext query permission.
        self.assertEqual(self.page(run)['total_hits'],120)
        with self.assertRaises(ApiError):
            self.create_export([run],actor=self.outsider)

    def test_zero_result_method_note_and_export_fixed_old_revision(self):
        run=self.completed(value='no-such-text')
        self.export_policy('allow')
        first=outcomes.create_note(self.project,NoteInput(title='零命中',body='=原解释\r\n"保留"',
            query_run_ids=[UUID(run['query_run_id'])]),self.owner,uuid4().hex)['note']
        outcomes.update_note(self.project,UUID(first['id']),NoteUpdate(expected_revision=1,title='新标题',body='new'),
                             self.owner,uuid4().hex)
        action=self.create_export(note=first)
        self.generate(action)
        content=json.loads(self.download(action))
        self.assertEqual(content['rows'][0]['body'],'=原解释\r\n"保留"')
        self.assertEqual(content['rows'][0]['revision'],1)
        self.assertEqual(content['rows'][0]['status'],'draft')
        self.assertEqual(content['rows'][0]['query_run_ids'],[run['query_run_id']])
        self.assertEqual(content['methods']['queries'][0]['counts']['total_hits'],0)
        self.policy('deny')
        with self.assertRaises(ApiError):
            outcomes.get_note(self.project,UUID(first['id']),self.viewer,None)

    def test_cancel_and_expired_lease_after_object_write_cannot_publish(self):
        from workers import exports as worker
        run = self.completed()
        original = worker.publish
        api_url = os.environ['DATABASE_URL']
        for condition in ('cancel', 'expire', 'revoke_export'):
            with self.subTest(condition=condition):
                self.export_policy('allow')
                action = self.create_export([run])
                ident = UUID(action['job_id'])
                written = []
                def interrupt(lease, artifact, methods, condition=condition, ident=ident, written=written):
                    written.append(artifact)
                    if condition == 'cancel':
                        with patch.dict(os.environ, {'DATABASE_URL':api_url}):
                            jobs.cancel(ident,jobs.EmptyBody(),self.owner,uuid4().hex)
                    elif condition == 'revoke_export':
                        with patch.dict(os.environ, {'DATABASE_URL':api_url}):
                            self.export_policy('deny')
                    else:
                        with transaction() as db:
                            db.get(Job,ident).lease_expires_at = jobs.now()-timedelta(seconds=1)
                    return original(lease, artifact, methods)
                with worker_role(), patch.object(worker,'publish',side_effect=interrupt):
                    self.assertEqual(worker.execute(ident,1)['status'],'fenced')
                with transaction(self.owner.id) as db:
                    job=db.get(Job,ident)
                    self.assertIn(job.state,{'CANCELLED','FAILED'})
                    self.assertEqual(job.reserved_bytes,0)
                    self.assertIsNone(db.get(ExportRecord,ident).artifact)
                self.assertEqual(len(written),1)
                from botocore.exceptions import ClientError
                with self.assertRaises(ClientError) as missing:
                    storage.client().head_object(Bucket=storage.bucket(),
                        Key=written[0]['object_key'],VersionId=written[0]['version_id'])
                self.assertIn(missing.exception.response['Error']['Code'],{'404','NoSuchKey','NoSuchVersion'})
                with worker_role():
                    self.assertEqual(worker.execute(ident,1)['status'],'duplicate_or_ineligible')

    def test_unknown_put_retains_budget_and_blocks_retry(self):
        from services.api import exports
        from workers import exports as worker
        run=self.completed()
        self.export_policy('allow')
        action=self.create_export([run])
        original=storage.put_private
        written=[]
        def unknown(*args):
            receipt=original(*args)
            written.append((args[0],receipt[0]))
            raise TimeoutError('controlled ACK loss after actual private PUT')
        try:
            with worker_role(),patch.object(storage,'put_private',side_effect=unknown):
                self.assertEqual(worker.execute(action['job_id'],1)['status'],'failed')
            self.assertEqual(len(written),1)
            state=exports.get_export(self.project,UUID(action['export_id']),self.viewer)
            self.assertEqual(state['error']['code'],'EXPORT_CLEANUP_REQUIRED')
            self.assertFalse(state['allowed_actions']['retry'])
            self.assertIsNone(state['result'])
            with transaction(self.owner.id) as db:
                self.assertGreater(db.get(Job,UUID(action['job_id'])).reserved_bytes,0)
            with self.assertRaises(ApiError):
                jobs.retry(UUID(action['job_id']),jobs.EmptyBody(),self.owner,uuid4().hex)
        finally:
            # Test-only exact receipt retained externally; the worker never received it.
            for key,version in written:
                storage.client().delete_object(Bucket=storage.bucket(),Key=key,VersionId=version)

    def test_revoked_artifact_still_counts_toward_project_storage_budget(self):
        run=self.completed()
        self.export_policy('allow')
        action=self.create_export([run])
        finished=self.generate(action)
        size=finished['result']['byte_size']
        material=self.imported()
        pure=self.completed(UUID(self.prepared([material['result']['id']])['id']))
        self.policy('deny')
        # RLS hides the old source result, but its persisted bytes still occupy quota.
        with transaction(self.owner.id) as db:
            self.assertIsNone(db.get(ExportRecord,UUID(action['export_id'])))
        with (patch.dict(os.environ,{'EXPORT_MAX_BYTES':'1024','EXPORT_PROJECT_MAX_BYTES':str(size+1023)}),
              self.assertRaises(ApiError) as rejected):
            self.create_export([pure])
        self.assertEqual(rejected.exception.code,'EXPORT_QUOTA_EXCEEDED')


if __name__ == '__main__':
    unittest.main()
