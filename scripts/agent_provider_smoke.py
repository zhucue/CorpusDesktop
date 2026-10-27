"""Synthetic loopback OpenAI protocol, two real Node processes, PG/S3/job continuation.

The API must be configured to the same explicit localhost model configuration.
This script never contacts a real model service or uses a real provider key.
"""

import hashlib
import json
import os
import secrets
import subprocess
import time
from datetime import UTC, datetime
from threading import Timer
from uuid import uuid4

import httpx

from scripts.agent_runtime_smoke import COMPOSE, ROOT, fixture

INSPECT = """
import json,os,sys
from uuid import UUID
from sqlalchemy import create_engine,text
from services.api import storage
body=json.load(sys.stdin)
engine=create_engine(os.environ['TEST_ADMIN_DATABASE_URL'],hide_parameters=True)
args={'id':UUID(body['actor_id'])}
with engine.begin() as db:
 email=db.execute(text('SELECT email FROM app.users WHERE id=:id'),args).scalar_one()
 assert email==body['email'] and email.startswith('k09-wait-') and email.endswith('@example.test')
 if body['mode']=='inspect':
  run=db.execute(text('SELECT state,lease_epoch,lease_expires_at,base_checkpoint_id,resume_checkpoint_id,final_checkpoint_id FROM app.agent_runs WHERE actor_id=:id'),args).mappings().one()
  session=db.execute(text('SELECT latest_checkpoint_id,active_run_id FROM app.agent_sessions WHERE actor_id=:id'),args).mappings().one()
  invocations=db.execute(text('SELECT id,tool_name,action_id,response FROM app.agent_invocations WHERE actor_id=:id ORDER BY created_at,id'),args).mappings().all()
  jobs=db.execute(text('SELECT id,state,attempt,action_id,result FROM app.jobs WHERE actor_id=:id'),args).mappings().all()
  actions=db.execute(text("SELECT count(*) FROM app.job_actions WHERE actor_id=:id AND operation='uploads.complete'"),args).scalar_one()
  result={'run':dict(run),'session':dict(session),'invocations':[dict(v) for v in invocations],'jobs':[dict(v) for v in jobs],'complete_actions':actions}
 else:
  objects=db.execute(text('SELECT object_key,version_id FROM app.upload_sessions WHERE actor_id=:id AND version_id IS NOT NULL'),args).all()
  for key,version in objects:
   storage.client().delete_object(Bucket=storage.bucket(),Key=key,VersionId=version)
  for table in ('job_outbox','job_events','job_attempts','jobs','job_actions','upload_sessions'):
   db.execute(text('DELETE FROM app.'+table+' WHERE project_id IN (SELECT id FROM app.projects WHERE owner_id=:id)'),args)
  result={'upload_versions_deleted':len(objects)}
engine.dispose()
print(json.dumps(result,default=str))
"""


def inspect_fixture(actor, mode="inspect"):
    result = subprocess.run(
        COMPOSE + ["run", "--rm", "-T", "test-auth", "python", "-c", INSPECT],
        input=json.dumps({"mode": mode, "actor_id": actor["id"], "email": actor["email"]}),
        text=True, encoding="utf-8", capture_output=True, cwd=ROOT, timeout=60,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("FIXTURE_INSPECTION_FAILED")
    return json.loads(result.stdout)


def expect(response, status=200):
    if response.status_code != status:
        raise RuntimeError(f"HTTP_STATUS_{response.status_code}_EXPECTED_{status}")
    return response.json()


def assert_no_strings(value, forbidden):
    """Inspect decoded JSON leaves; escaping/CRLF must not hide private text."""
    if isinstance(value, str):
        assert all(secret not in value for secret in forbidden)
    elif isinstance(value, dict):
        for item in value.values():
            assert_no_strings(item, forbidden)
    elif isinstance(value, list):
        for item in value:
            assert_no_strings(item, forbidden)


def node_segment(config):
    process = subprocess.run(
        [os.getenv("CORPUS_NODE", "node"), "services/agent-runtime/src/model-segment-smoke.ts"],
        input=json.dumps(config), text=True, encoding="utf-8", capture_output=True,
        cwd=ROOT, timeout=150, check=False,
        env={**os.environ, "AGENT_MODEL_API_KEY": "synthetic-provider-key-NOT-A-CREDENTIAL"},
    )
    if process.returncode:
        failure = json.loads(process.stderr) if process.stderr.startswith("{") else {}
        code = failure.get("code", "NODE_SEGMENT_FAILED")
        raise RuntimeError(code if isinstance(code, str) and code.replace("_", "").isalnum() else "NODE_SEGMENT_FAILED")
    return json.loads(process.stdout)


def server_line(server):
    timer = Timer(30, server.terminate)
    timer.start()
    try:
        line = server.stdout.readline()
        if not line:
            raise RuntimeError("SYNTHETIC_SERVER_FAILED")
        return json.loads(line)
    finally:
        timer.cancel()


def main():
    from urllib.parse import urlsplit
    endpoint = os.environ.get("AGENT_MODEL_BASE_URL", "")
    parsed = urlsplit(endpoint)
    assert parsed.hostname == "127.0.0.1" and parsed.scheme == "http" and parsed.path == "/v1"
    assert parsed.port and os.environ.get("AGENT_MODEL_ALLOW_LOOPBACK_HTTP") == "true"
    assert os.environ.get("AGENT_MODEL_API") in {"openai-completions", "openai-responses"}
    server = None
    env = dict(line.split("=", 1) for line in (ROOT / "deploy/.env").read_text().splitlines()
               if "=" in line and not line.startswith("#"))
    base = "http://127.0.0.1:" + env["CORPUS_HTTP_PORT"]
    actor = {"id": str(uuid4()), "email": f"k09-wait-{uuid4().hex}@example.test", "password": secrets.token_urlsafe(32)}
    destination = ROOT / "tmp/pi-provider" / uuid4().hex
    destination.mkdir(parents=True)
    report = {"status": "running", "started_at": datetime.now(UTC).isoformat(),
              "production_available": False, "model_network_mode": "synthetic_loopback_builtin_adapter"}
    for family in ("runtimes", "sessions", "session_lists", "runs", "run_lists", "messages", "events"):
        report[family] = []
    run_id = None
    fixture({"mode": "create", **actor})
    client = httpx.Client(base_url=base, timeout=20, headers={"Origin": base}, trust_env=False)
    try:
        login = expect(client.post("/api/v1/auth/login", json={"email": actor["email"], "password": actor["password"]}))
        client.headers["X-CSRF-Token"] = login["csrf_token"]
        runtime = expect(client.get("/api/v1/agent/runtime"))
        report["runtimes"].append(runtime)
        assert runtime["mode"] == "openai-compatible" and runtime["can_submit"] and not runtime["production_ready"]
        project = expect(client.post("/api/v1/projects", json={"name": "K09 waiting checkpoint fixture"}), 201)
        content = "Private fixture正文 stays in S3, never in model input.\r\n".encode()
        upload = expect(client.post(f"/api/v1/projects/{project['id']}/uploads", headers={"Idempotency-Key": str(uuid4())},
                                    json={"filename": "waiting-fixture.txt", "size": len(content), "media_type": "text/plain", "sha256": hashlib.sha256(content).hexdigest()}), 201)
        expect(client.put(upload["upload_url"], content=content, headers={"Content-Type": "application/octet-stream"}))
        session = expect(client.post("/api/v1/agent/sessions", json={"scope": {"scope_kind": "project", "project_id": project["id"]}}), 201)
        report["sessions"].append(session)
        server = subprocess.Popen(
            [os.getenv("CORPUS_NODE", "node"), "services/agent-runtime/test/provider-server-cli.ts"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", cwd=ROOT,
        )
        server.stdin.write(json.dumps({"api": os.environ["AGENT_MODEL_API"], "port": parsed.port,
                                      "uploadId": upload["upload_id"], "model": os.environ["AGENT_MODEL_ID"]}) + "\n")
        server.stdin.flush()
        assert server_line(server)["ready"]
        message = f"protocol-test:complete-upload:{upload['upload_id']}"
        queued = expect(client.post(f"/api/v1/agent/sessions/{session['session_id']}/runs", json={
            "request_key": str(uuid4()), "scope_digest": session["scope_digest"], "message": message}), 201)
        run_id = queued["run_id"]
        report["runs"].append(queued)
        config = {"baseUrl": base, "hostKey": env["CORPUS_AGENT_HOST_KEY"], "runId": run_id}
        first = node_segment({**config, "directory": str(destination / "process-one")})
        assert first["final"]["state"] == "WAITING_JOB" and first["new_tool_executions"] == 1
        report["runs"].append(expect(client.get(f"/api/v1/agent/runs/{run_id}")))
        paused = inspect_fixture(actor)
        assert paused["run"]["state"] == "WAITING_JOB" and paused["run"]["lease_expires_at"] is None
        assert paused["session"]["latest_checkpoint_id"] is None
        assert paused["run"]["resume_checkpoint_id"] == first["checkpoint"]["checkpoint_id"]
        assert len(paused["jobs"]) == paused["complete_actions"] == 1
        job_id = paused["jobs"][0]["id"]
        deadline = time.monotonic() + 90
        while True:
            job = expect(client.get(f"/api/v1/jobs/{job_id}"))
            if job["state"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                break
            if time.monotonic() > deadline:
                raise RuntimeError("REAL_JOB_TIMEOUT")
            time.sleep(.5)
        assert job["state"] == "SUCCEEDED"
        assert job["result"]["sha256"] == hashlib.sha256(content).hexdigest()
        assert job["result"]["size"] == len(content)
        second = node_segment({**config, "directory": str(destination / "process-two")})
        assert second["final"]["state"] == "SUCCEEDED" and second["restored"]
        assert second["lease_epoch"] > first["lease_epoch"]
        assert second["tool_names"] == ["jobs_get"] and second["new_tool_executions"] == 1
        final = inspect_fixture(actor)
        assert final["session"]["latest_checkpoint_id"] == second["checkpoint"]["checkpoint_id"]
        assert len(final["jobs"]) == final["complete_actions"] == 1
        assert final["jobs"][0]["id"] == job_id and final["jobs"][0]["attempt"] == 1
        assert [row["tool_name"] for row in final["invocations"]] == ["uploads.complete", "jobs.get"]
        assert final["invocations"][0] == paused["invocations"][0]
        assert second["resume_checkpoint"] == first["checkpoint"]
        report["runs"].append(expect(client.get(f"/api/v1/agent/runs/{run_id}")))
        report["sessions"].append(expect(client.get(f"/api/v1/agent/sessions/{session['session_id']}")))
        report["session_lists"].append(expect(client.get("/api/v1/agent/sessions")))
        report["run_lists"].append(expect(client.get(f"/api/v1/agent/sessions/{session['session_id']}/runs")))
        report["messages"].append(expect(client.get(f"/api/v1/agent/sessions/{session['session_id']}/messages")))
        report["events"].append(expect(client.get(f"/api/v1/agent/runs/{run_id}/events")))
        forbidden = (env["CORPUS_AGENT_HOST_KEY"], actor["password"], login["csrf_token"],
                     content.decode().splitlines()[0], "synthetic-provider-key-NOT-A-CREDENTIAL")
        for archive in destination.rglob("*.jsonl"):
            for line in archive.read_text(encoding="utf-8").splitlines():
                assert_no_strings(json.loads(line), forbidden)
        server.stdin.write("stop\n")
        server.stdin.flush()
        protocol = server_line(server)
        server.wait(timeout=15)
        assert server.returncode == 0 and len(protocol["requests"]) == 4
        assert_no_strings(protocol, forbidden)
        report["protocol_requests"] = protocol["requests"]
        report["protocol"] = os.environ["AGENT_MODEL_API"]
        old_archive = next((destination / "process-two").rglob("base-checkpoint.jsonl"))
        assert hashlib.sha256(old_archive.read_bytes()).hexdigest() == first["checkpoint"]["sha256"]
        report.update(status="passed", processes=[first, second], paused=paused, final=final,
                      job=job, runtime=runtime, original_message=message, same_run=True,
                      resumed_epoch=True, duplicate_write=False, private_body_in_model=False)
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__)
        if isinstance(error, RuntimeError):
            report["code"] = str(error)
        raise
    finally:
        if server is not None:
            if server.poll() is None:
                server.terminate()
                server.wait(timeout=15)
            for stream in (server.stdin, server.stdout, server.stderr):
                if stream:
                    stream.close()
        try:
            if run_id:
                client.post(f"/api/v1/agent/runs/{run_id}/cancel", json={})
            report["cleanup"] = inspect_fixture(actor, "cleanup")
            fixture({"mode": "cleanup", "id": actor["id"]})
            report["cleanup"]["completed"] = True
        finally:
            client.close()
            report["finished_at"] = datetime.now(UTC).isoformat()
            path = destination / "result.json"
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"status": report["status"], "report": str(path), "cleanup": report.get("cleanup")}))


if __name__ == "__main__":
    main()
