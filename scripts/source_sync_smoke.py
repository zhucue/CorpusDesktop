"""Two complete official Tatoeba acquisitions through HTTP and resident workers.

Temporary administrator credentials travel only through stdin/in-memory HTTP.
Run only in the coordinated corpus-s0 verification window, after deployment.
"""

import hashlib
import json
import secrets
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    "deploy/.env",
    "-f",
    "deploy/compose.yaml",
]
FIXTURE = r"""
import hashlib,json,os,sys,time
from uuid import UUID
from sqlalchemy import create_engine,text
from services.api.auth import HASHER
from services.api import storage
from workers.app import app
body=json.load(sys.stdin)
engine=create_engine(os.environ['TEST_OWNER_DATABASE_URL'] if body['mode']=='create' else os.environ['TEST_ADMIN_DATABASE_URL'],hide_parameters=True)
args={'actor':UUID(body['id'])}
if body['mode']=='create':
 with engine.begin() as db:
  db.execute(text('INSERT INTO app.users(id,email,password_hash,is_active,is_platform_admin) VALUES(:actor,:email,:hash,true,true)'),{**args,'email':body['email'],'hash':HASHER.hash(body['password'])})
 print(json.dumps({'created':True}))
elif body['mode']=='verify':
 with engine.connect() as db:
  row=db.execute(text('SELECT a.* FROM app.source_acquisitions a JOIN app.source_sync_runs r ON r.id=a.run_id WHERE r.actor_id=:actor AND r.id=:run'),{**args,'run':UUID(body['run_id'])}).mappings().one()
  expected=row['manifest']['artifacts']
  objects=row['objects']
  assert len(objects)==len(expected)+1
  verified=[]
  for item in objects:
   stream=storage.read_private(item['object_key'],item['version_id'],item['etag'])
   digest=hashlib.sha256(); size=0; raw=[] if item['name']=='manifest.json' else None
   try:
    while chunk:=stream.read(1024*1024):
     digest.update(chunk);size+=len(chunk)
     if raw is not None: raw.append(chunk)
   finally: stream.close()
   assert size==item['bytes'] and digest.hexdigest()==item['sha256']
   if raw is not None:
    assert json.loads(b''.join(raw))==row['manifest']
    assert digest.hexdigest()==row['manifest_sha256']
   else:
    listed=next(x for x in expected if x['name']==item['name'])
    assert listed['sha256']==digest.hexdigest() and listed['bytes']==size
   verified.append({k:item[k] for k in ('name','bytes','sha256','version_id')})
  print(json.dumps({'acquisition_id':str(row['id']),'manifest_sha256':row['manifest_sha256'],
    'quality':row['manifest']['quality'],'diff':row['manifest']['diff'],'license':row['manifest']['license'],
    'files':verified,'all_version_pinned_objects_verified':True}))
else:
 with engine.begin() as db:
  ids=list(db.execute(text('SELECT id FROM app.source_sync_runs WHERE actor_id=:actor'),args).scalars())
  db.execute(text("UPDATE app.source_sync_runs SET state='CANCELLED',stage='CANCELLED',lease_epoch=lease_epoch+1,lease_token=NULL,lease_expires_at=NULL WHERE actor_id=:actor AND state IN ('QUEUED','RUNNING')"),args)
 # Cancellation fences publication; wait for actual resident task exit before removing its keys.
 deadline=time.monotonic()+90
 while ids:
  active=app.control.inspect(timeout=3).active()
  if active is None: raise RuntimeError('CLEANUP_WORKER_STATUS_UNAVAILABLE')
  own=[task for tasks in active.values() for task in tasks if task.get('name')=='workers.sync_tatoeba' and any(str(i) in str(task.get('args',[])) for i in ids)]
  if not own: break
  if time.monotonic()>deadline: raise RuntimeError('CLEANUP_WORKER_STILL_ACTIVE')
  time.sleep(1)
 with engine.begin() as db:
  referenced=db.scalar(text('SELECT count(*) FROM app.source_sync_runs r JOIN app.source_acquisitions a ON a.id=r.previous_acquisition_id JOIN app.source_sync_runs original ON original.id=a.run_id WHERE original.actor_id=:actor AND r.actor_id<>:actor'),args)
  if referenced: raise RuntimeError('CLEANUP_EXTERNAL_BASELINE_REFERENCE')
  # Exact per-run prefixes also find only our unregistered staging objects.
  deleted=0
  for run_id in ids:
   prefix='source-sync/'+str(run_id)+'/'
   paginator=storage.client().get_paginator('list_object_versions')
   for page in paginator.paginate(Bucket=storage.bucket(),Prefix=prefix):
    for item in page.get('Versions',[])+page.get('DeleteMarkers',[]):
     assert item['Key'].startswith(prefix)
     storage.client().delete_object(Bucket=storage.bucket(),Key=item['Key'],VersionId=item['VersionId'])
     deleted+=1
  db.execute(text('UPDATE app.source_sync_runs SET previous_acquisition_id=NULL WHERE actor_id=:actor'),args)
  for table in ('source_acquisitions','source_sync_outbox','source_sync_events','source_sync_attempts'):
   db.execute(text('DELETE FROM app.'+table+' WHERE run_id IN (SELECT id FROM app.source_sync_runs WHERE actor_id=:actor)'),args)
  db.execute(text('DELETE FROM app.source_sync_runs WHERE actor_id=:actor'),args)
  db.execute(text('DELETE FROM app.source_sync_actions WHERE actor_id=:actor'),args)
  db.execute(text('DELETE FROM app.users WHERE id=:actor'),args)
 print(json.dumps({'cleaned':True,'run_count':len(ids),'object_versions_deleted':deleted}))
engine.dispose()
"""


def fixture(body):
    process = subprocess.run(
        COMPOSE + ["run", "--rm", "-T", "test-auth", "python", "-c", FIXTURE],
        input=json.dumps(body),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=240,
        check=False,
    )
    if process.returncode:
        raise RuntimeError("SYNC_FIXTURE_" + body["mode"].upper() + "_FAILED")
    return json.loads(process.stdout)


def checked(response):
    if response.status_code >= 400:
        try:
            code = response.json().get("code", "HTTP_ERROR")
        except ValueError:
            code = "HTTP_ERROR"
        raise RuntimeError(
            code
            if isinstance(code, str) and code.replace("_", "").isalnum()
            else "HTTP_ERROR"
        )
    return response.json() if response.content else None


def main():
    env = dict(
        line.split("=", 1)
        for line in (ROOT / "deploy/.env").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    base = "http://127.0.0.1:" + env["CORPUS_HTTP_PORT"]
    actor = {
        "id": str(uuid4()),
        "email": f"source-smoke-{uuid4().hex}@example.test",
        "password": secrets.token_urlsafe(24),
    }
    destination = ROOT / "tmp" / "source-sync-smoke" / uuid4().hex
    destination.mkdir(parents=True)
    report = {
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "runs": [],
        "transport": "real_HTTP",
        "worker": "resident_Celery_via_durable_outbox",
        "formal_capacity_acceptance": False,
        "searchable": False,
    }
    phase = "create_account"
    created = False
    failure = None
    try:
        fixture({"mode": "create", **actor})
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
            public_before = checked(client.get("/api/v1/sources/D12/versions"))
            first_view = None
            for index in range(2):
                phase = f"sync_{index + 1}"
                began = time.monotonic()
                path = "/api/v1/admin/sources/D12/sync-runs"
                key = uuid4().hex
                start = checked(
                    client.post(path, json={}, headers={"Idempotency-Key": key})
                )
                result = {"start": start, "run": start["run"], "events": []}
                report["runs"].append(result)
                (destination / "progress.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                selfsame = checked(
                    client.post(path, json={}, headers={"Idempotency-Key": key})
                )
                assert start == selfsame
                ident = start["sync_run_id"]
                listing = checked(client.get(path))
                result["list"] = listing
                seen_stages = []
                while True:
                    current = checked(client.get(f"/api/v1/admin/sync-runs/{ident}"))
                    result.update(
                        run=current,
                        duration_seconds=time.monotonic() - began,
                        observed_stages=seen_stages,
                    )
                    if current["stage"] not in seen_stages:
                        seen_stages.append(current["stage"])
                        print(
                            json.dumps(
                                {
                                    "run": index + 1,
                                    "stage": current["stage"],
                                    "progress": current["progress"],
                                }
                            ),
                            flush=True,
                        )
                        (destination / "progress.json").write_text(
                            json.dumps(report, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                    if current["state"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                        break
                    if time.monotonic() - began > 3900:
                        raise RuntimeError("SYNC_SMOKE_TIMEOUT")
                    time.sleep(2)
                after, events = 0, []
                while True:
                    page = checked(
                        client.get(
                            f"/api/v1/admin/sync-runs/{ident}/events",
                            params={"after_sequence": after, "page_size": 100},
                        )
                    )
                    events.extend(page["items"])
                    if not page["items"]:
                        break
                    after = page["next_sequence"]
                assert [event["sequence"] for event in events] == list(
                    range(1, len(events) + 1)
                )
                result["events"] = events
                (destination / "progress.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                if current["state"] != "SUCCEEDED":
                    code = (current.get("error") or {}).get(
                        "code", "SYNC_NOT_SUCCEEDED"
                    )
                    raise RuntimeError(
                        code
                        if isinstance(code, str) and code.replace("_", "").isalnum()
                        else "SYNC_NOT_SUCCEEDED"
                    )
                assert (
                    current["result"]["state"] == "VALIDATED"
                    and current["result"]["searchable"] is False
                )
                verified = fixture(
                    {"mode": "verify", "id": actor["id"], "run_id": ident}
                )
                result["objects"] = verified
                assert verified["quality"] == current["result"]["quality"]
                assert (
                    verified["manifest_sha256"] == current["result"]["manifest_sha256"]
                )
                if index == 0:
                    first_view = current
                else:
                    diff = current["result"]["diff"]
                    assert diff["status"] == "compared"
                    assert all(
                        diff[k] == 0
                        for k in (
                            "sentence_added",
                            "sentence_removed",
                            "sentence_changed",
                            "text_changed",
                            "edge_added",
                            "edge_removed",
                        )
                    )
                    old = checked(
                        client.get(f"/api/v1/admin/sync-runs/{first_view['id']}")
                    )
                    assert old == first_view
                    assert (
                        current["result"]["acquisition_id"]
                        != old["result"]["acquisition_id"]
                    )
                    first_files = {
                        x["name"]: x["sha256"]
                        for x in report["runs"][0]["objects"]["files"]
                    }
                    for item in verified["files"]:
                        if item["name"].endswith(".tsv.bz2"):
                            assert item["sha256"] == first_files[item["name"]]
                assert (
                    checked(client.get("/api/v1/sources/D12/versions")) == public_before
                )
                (destination / "progress.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            assert public_before["items"] == []
            checked(client.post("/api/v1/auth/logout", json={}))
        report.update(
            status="passed",
            unchanged_published_versions=True,
            second_complete_sync_zero_diff=True,
        )
    except Exception as exc:  # noqa: BLE001 - safe report, never credentials/response bodies
        failure = exc
        report.update(status="failed", phase=phase, error_type=type(exc).__name__)
        if isinstance(exc, RuntimeError):
            report["code"] = str(exc)
        elif isinstance(exc, AssertionError):
            report["code"] = "VERIFICATION_ASSERTION_FAILED"
    finally:
        if created:
            try:
                report["cleanup"] = fixture({"mode": "cleanup", "id": actor["id"]})
            except Exception:  # noqa: BLE001
                report["cleanup"] = {
                    "cleaned": False,
                    "reason": "FIXTURE_CLEANUP_FAILED",
                    "actor_id": actor["id"],
                }
                report["status"] = "failed"
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
