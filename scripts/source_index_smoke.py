"""One real official acquisition and private index via HTTP and resident workers."""

import argparse
import hashlib
import json
import secrets
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from scripts.source_sync_smoke import COMPOSE, ROOT, checked
from scripts.source_sync_smoke import fixture as sync_fixture

INDEX_FIXTURE = r"""
import hashlib,json,os,sys,time,subprocess,tarfile,tempfile
from pathlib import Path
from uuid import UUID
from sqlalchemy import create_engine,text
from services.api import storage
from workers.app import app
body=json.load(sys.stdin)
engine=create_engine(os.environ['TEST_ADMIN_DATABASE_URL'],hide_parameters=True)
args={'actor':UUID(body['id'])}
if body['mode']=='verify':
 temporary=tempfile.TemporaryDirectory(prefix='reopen-',dir='/app/tmp/index-build')
 workspace=Path(temporary.name)
 with engine.connect() as db:
  row=db.execute(text('SELECT i.* FROM app.source_indexes i JOIN app.index_build_runs r ON r.id=i.run_id WHERE r.actor_id=:actor AND r.id=:run'),{**args,'run':UUID(body['run_id'])}).mappings().one()
  verified=[]
  for item in row['objects']:
   stream=storage.read_private(item['object_key'],item['version_id'],item['etag'])
   digest=hashlib.sha256(); size=0; raw=[] if item['name']=='manifest.json' else None
   output=(workspace/'index.tar').open('wb') if item['name']=='index.tar' else None
   try:
    while chunk:=stream.read(1024*1024):
     digest.update(chunk);size+=len(chunk)
     if raw is not None: raw.append(chunk)
     if output is not None: output.write(chunk)
   finally:
    stream.close()
    if output is not None: output.close()
   assert size==item['bytes'] and digest.hexdigest()==item['sha256']
   if raw is not None:
    assert json.loads(b''.join(raw))==row['manifest']
    assert digest.hexdigest()==row['manifest_sha256']
   else:
    assert row['manifest']['package']['sha256']==digest.hexdigest()
   verified.append({k:item[k] for k in ('name','bytes','sha256','version_id')})
  assert sum(x['bytes'] for x in verified)==row['artifact_bytes']
  source=db.execute(text('SELECT manifest,manifest_sha256 FROM app.source_acquisitions WHERE id=:id'),{'id':row['acquisition_id']}).mappings().one()
  assert row['manifest']['identity']['acquisition_manifest_sha256']==source['manifest_sha256']
  assert row['manifest']['counts']['sentences']==source['manifest']['quality']['sentences']
  assert row['manifest']['counts']['direct_edges']==source['manifest']['quality']['direct_edges']
  extracted=workspace/'extracted'
  with tarfile.open(workspace/'index.tar') as archive:
   allowed={item['name'] for item in row['manifest']['files']}|{'manifest.json'}
   members=archive.getmembers()
   assert {item.name for item in members}==allowed and len(members)==len(allowed)
   assert all(item.isfile() and not Path(item.name).is_absolute() and '..' not in Path(item.name).parts for item in members)
   archive.extractall(extracted,filter='data')
  reopened=subprocess.run([sys.executable,'-c',body['reader_code'],str(extracted),str(workspace/'reader-runtime')],capture_output=True,text=True,encoding='utf-8',timeout=180,check=True)
  reopened=json.loads(reopened.stdout)
  print(json.dumps({'index_id':str(row['id']),'manifest_sha256':row['manifest_sha256'],
   'manifest':row['manifest'],'files':verified,'all_version_pinned_objects_verified':True,
   'counts_match_acquisition':True,'fresh_process_reopen':reopened}))
 temporary.cleanup()
else:
 with engine.begin() as db:
  ids=list(db.execute(text('SELECT id FROM app.index_build_runs WHERE actor_id=:actor'),args).scalars())
  db.execute(text("UPDATE app.index_build_runs SET state='CANCELLED',stage='CANCELLED',lease_epoch=lease_epoch+1,lease_token=NULL,lease_expires_at=NULL WHERE actor_id=:actor AND state IN ('QUEUED','RUNNING')"),args)
 deadline=time.monotonic()+90
 while ids:
  active=app.control.inspect(timeout=3).active()
  if active is None: raise RuntimeError('CLEANUP_WORKER_STATUS_UNAVAILABLE')
  own=[task for tasks in active.values() for task in tasks if task.get('name')=='workers.build_source_index' and any(str(i) in str(task.get('args',[])) for i in ids)]
  if not own: break
  if time.monotonic()>deadline: raise RuntimeError('CLEANUP_WORKER_STILL_ACTIVE')
  time.sleep(1)
 with engine.begin() as db:
  deleted=0
  for run_id in ids:
   prefix='source-index/'+str(run_id)+'/'
   paginator=storage.client().get_paginator('list_object_versions')
   for page in paginator.paginate(Bucket=storage.bucket(),Prefix=prefix):
    for item in page.get('Versions',[])+page.get('DeleteMarkers',[]):
     assert item['Key'].startswith(prefix)
     storage.client().delete_object(Bucket=storage.bucket(),Key=item['Key'],VersionId=item['VersionId'])
     deleted+=1
  for table in ('source_indexes','index_build_outbox','index_build_events','index_build_attempts'):
   db.execute(text('DELETE FROM app.'+table+' WHERE run_id IN (SELECT id FROM app.index_build_runs WHERE actor_id=:actor)'),args)
  db.execute(text('DELETE FROM app.index_build_runs WHERE actor_id=:actor'),args)
  db.execute(text('DELETE FROM app.index_build_actions WHERE actor_id=:actor'),args)
 print(json.dumps({'cleaned':True,'run_count':len(ids),'object_versions_deleted':deleted}))
engine.dispose()
"""

READER_CODE = r"""
import json,sys
from pipelines.query.source_reader import SourceIndexReader
from pipelines.query.source_index import TOKEN
with SourceIndexReader(sys.argv[1],sys.argv[2]) as reader:
 text=reader.text(0)
 sid=reader.record(0)[0]
 position=reader.record(0)[5]
 _,left,right=TOKEN.unpack_from(reader.maps['tokens.map'],position*TOKEN.size)
 form=text[left:right]
 def query(unit,pattern):
  return {'dsl_version':'corpus-query/v1','unit':unit,'within':'sentence','pattern':pattern,'normalization':'none','overlap':'all'}
 character=reader.character_page(query('character',{'type':'literal','value':text[0]}))
 token=reader.token_page(query('token',{'type':'term','attr':'form','op':'eq','value':form}))
 assert any(hit['source_sentence_id']==sid for hit in character['page'])
 assert any(hit['source_sentence_id']==sid and hit['match']==form for hit in token['page'])
 print(json.dumps({'status':'passed','fresh_process':True,'cold_disk':False,
  'source_sentence_id':sid,'character_query':character,'token_query':token},ensure_ascii=False))
"""


def index_fixture(body):
    if body["mode"] == "verify":
        body = {**body, "reader_code": READER_CODE}
    result = subprocess.run(
        COMPOSE + ["run", "--rm", "-T", "test-index", "python", "-c", INDEX_FIXTURE],
        input=json.dumps(body),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=360,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("INDEX_FIXTURE_" + body["mode"].upper() + "_FAILED")
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ui-hold-seconds", type=int, default=0)
    options = parser.parse_args()
    if not 0 <= options.ui_hold_seconds <= 900:
        parser.error("--ui-hold-seconds must be between 0 and 900")
    env = dict(
        line.split("=", 1)
        for line in (ROOT / "deploy/.env").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    base = "http://127.0.0.1:" + env["CORPUS_HTTP_PORT"]
    actor = {
        "id": str(uuid4()),
        "email": f"index-smoke-{uuid4().hex}@example.test",
        "password": secrets.token_urlsafe(24),
    }
    destination = ROOT / "tmp" / "source-index-smoke" / uuid4().hex
    destination.mkdir(parents=True)
    report = {
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "runs": [],
        "sync_runs": [],
        "transport": "real_HTTP",
        "worker": "resident_Celery_via_durable_outbox",
        "formal_capacity_acceptance": False,
        "searchable": False,
    }
    created, failure, phase = False, None, "create_account"

    def save():
        (destination / "progress.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def wait(client, entry, route, limit):
        began, stages = time.monotonic(), []
        while True:
            current = checked(client.get(route))
            entry.update(
                run=current,
                duration_seconds=time.monotonic() - began,
                observed_stages=stages,
            )
            if current["stage"] not in stages:
                stages.append(current["stage"])
                print(
                    json.dumps(
                        {
                            "phase": phase,
                            "stage": current["stage"],
                            "progress": current["progress"],
                        }
                    ),
                    flush=True,
                )
            save()
            if current["state"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                break
            if time.monotonic() - began > limit:
                raise RuntimeError("INDEX_SMOKE_TIMEOUT")
            time.sleep(3)
        entry["events"] = []
        after = 0
        while True:
            page = checked(
                client.get(
                    route + "/events",
                    params={"after_sequence": after, "page_size": 100},
                )
            )
            entry["events"].extend(page["items"])
            if not page["items"]:
                break
            after = page["next_sequence"]
        save()
        assert [event["sequence"] for event in entry["events"]] == list(
            range(1, len(entry["events"]) + 1)
        )
        if current["state"] != "SUCCEEDED":
            code = (current.get("error") or {}).get("code", "TASK_NOT_SUCCEEDED")
            raise RuntimeError(
                code
                if isinstance(code, str) and code.replace("_", "").isalnum()
                else "TASK_NOT_SUCCEEDED"
            )
        return current

    try:
        sync_fixture({"mode": "create", **actor})
        created = True
        with httpx.Client(
            base_url=base, timeout=20, headers={"Origin": base}
        ) as client:
            phase = "login"
            session = checked(
                client.post(
                    "/api/v1/auth/login",
                    json={"email": actor["email"], "password": actor["password"]},
                )
            )
            client.headers["X-CSRF-Token"] = session["csrf_token"]
            report["public_versions_before"] = checked(
                client.get("/api/v1/sources/D12/versions")
            )
            phase = "official_acquisition"
            source_path = "/api/v1/admin/sources/D12/sync-runs"
            start = checked(
                client.post(
                    source_path, json={}, headers={"Idempotency-Key": uuid4().hex}
                )
            )
            sync = {
                "start": start,
                "run": start["run"],
                "list": checked(client.get(source_path)),
            }
            report["sync_runs"].append(sync)
            save()
            current = wait(
                client, sync, "/api/v1/admin/sync-runs/" + start["sync_run_id"], 3900
            )
            sync["objects"] = sync_fixture(
                {"mode": "verify", "id": actor["id"], "run_id": current["id"]}
            )
            acquisition_id = current["result"]["acquisition_id"]
            phase = "private_index"
            path = "/api/v1/admin/sources/D12/index-builds"
            key = uuid4().hex
            payload = {"acquisition_id": acquisition_id}
            start = checked(
                client.post(path, json=payload, headers={"Idempotency-Key": key})
            )
            entry = {
                "start": start,
                "run": start["run"],
                "list": checked(client.get(path)),
            }
            report["runs"].append(entry)
            save()
            assert (
                checked(
                    client.post(path, json=payload, headers={"Idempotency-Key": key})
                )
                == start
            )
            current = wait(
                client,
                entry,
                "/api/v1/admin/index-builds/" + start["index_run_id"],
                7500,
            )
            assert (
                current["result"]["state"] == "INDEXED"
                and not current["result"]["searchable"]
            )
            phase = "verify_objects"
            verified = index_fixture(
                {"mode": "verify", "id": actor["id"], "run_id": current["id"]}
            )
            entry["objects"] = verified
            assert verified["manifest_sha256"] == current["result"]["manifest_sha256"]
            assert verified["manifest"]["counts"] == current["result"]["counts"]
            phase = "reuse"
            duplicate = checked(
                client.post(
                    path, json=payload, headers={"Idempotency-Key": uuid4().hex}
                )
            )
            report["existing_action"] = duplicate
            report["actions"] = [duplicate]
            assert duplicate["existing"] and duplicate["index_run_id"] == current["id"]
            assert duplicate["run"] == current
            repeated = index_fixture(
                {"mode": "verify", "id": actor["id"], "run_id": current["id"]}
            )
            assert repeated == verified
            report["list_after_reuse"] = checked(client.get(path))
            report["lists"] = [report["list_after_reuse"]]
            assert report["list_after_reuse"]["total"] == entry["list"]["total"]
            report["public_versions_after"] = checked(
                client.get("/api/v1/sources/D12/versions")
            )
            assert report["public_versions_after"] == report["public_versions_before"]
            assert report["public_versions_after"]["items"] == []
            checked(client.post("/api/v1/auth/logout", json={}))
        report.update(
            status="passed",
            same_input_reused_without_new_artifacts=True,
            unchanged_published_versions=True,
        )
        if options.ui_hold_seconds:
            release = destination / "cleanup-release"
            report["ui_hold"] = {
                "seconds_limit": options.ui_hold_seconds,
                "release_marker": str(release),
                "status": "waiting",
            }
            save()
            print(
                json.dumps(
                    {
                        "status": "passed_waiting_for_ui",
                        "report": str(destination / "progress.json"),
                        "release_marker": str(release),
                    }
                ),
                flush=True,
            )
            deadline = time.monotonic() + options.ui_hold_seconds
            while not release.exists() and time.monotonic() < deadline:
                time.sleep(1)
            report["ui_hold"]["status"] = "released" if release.exists() else "expired"
            save()
    except Exception as exc:  # noqa: BLE001 - no credentials or provider exception messages
        failure = exc
        report.update(status="failed", phase=phase, error_type=type(exc).__name__)
        report["code"] = (
            str(exc) if isinstance(exc, RuntimeError) else "VERIFICATION_FAILED"
        )
    finally:
        if created:
            try:
                report["index_cleanup"] = index_fixture(
                    {"mode": "cleanup", "id": actor["id"]}
                )
                report["sync_cleanup"] = sync_fixture(
                    {"mode": "cleanup", "id": actor["id"]}
                )
            except Exception:  # noqa: BLE001
                report.update(
                    status="failed",
                    cleanup={
                        "cleaned": False,
                        "actor_id": actor["id"],
                        "reason": "FIXTURE_CLEANUP_FAILED",
                    },
                )
                failure = RuntimeError("FIXTURE_CLEANUP_FAILED")
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["script_sha256"] = hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest()
        path = destination / "result.json"
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"status": report["status"], "report": str(path)}), flush=True)
    if failure:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
