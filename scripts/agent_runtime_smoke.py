"""Real Node Pi -> HTTP -> PostgreSQL smoke with ephemeral account and fixed model.

Run from the repository root after API deployment. Secrets remain in memory/stdin;
the saved report contains only non-secret run identifiers and observed outcomes.
"""

import json
import os
import secrets
import subprocess
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
FIXTURE = """
import json,sys,os
from uuid import UUID
from sqlalchemy import create_engine,text
from services.api.auth import HASHER
from services.api import storage
body=json.load(sys.stdin)
role='TEST_ADMIN_DATABASE_URL' if body['mode']=='cleanup' else 'TEST_OWNER_DATABASE_URL'
engine=create_engine(os.environ[role],hide_parameters=True)
with engine.begin() as db:
 if body['mode']=='create':
  db.execute(text('INSERT INTO app.users(id,email,password_hash,is_active,is_platform_admin) VALUES(:id,:email,:hash,true,false)'),
             {'id':UUID(body['id']),'email':body['email'],'hash':HASHER.hash(body['password'])})
 else:
  args={'id':UUID(body['id'])}
  rows=db.execute(text('SELECT object_key,version_id FROM app.agent_checkpoints WHERE actor_id=:id'),args).all()
  for key,version in rows:
   storage.client().delete_object(Bucket=storage.bucket(),Key=key,VersionId=version)
  db.execute(text('UPDATE app.agent_sessions SET active_run_id=NULL,latest_checkpoint_id=NULL WHERE actor_id=:id'),args)
  db.execute(text('UPDATE app.agent_runs SET base_checkpoint_id=NULL,final_checkpoint_id=NULL,resume_checkpoint_id=NULL WHERE actor_id=:id'),args)
  checkpoints=db.execute(text('SELECT id FROM app.agent_checkpoints WHERE actor_id=:id ORDER BY created_at DESC'),args).scalars().all()
  for checkpoint_id in checkpoints:
   db.execute(text('DELETE FROM app.agent_checkpoints WHERE id=:checkpoint_id'),{'checkpoint_id':checkpoint_id})
  for table in ('agent_events','agent_invocations','agent_credentials','agent_runs','agent_sessions'):
   db.execute(text('DELETE FROM app.'+table+' WHERE actor_id=:id'),args)
  db.execute(text('DELETE FROM app.projects WHERE owner_id=:id'),args)
  db.execute(text('DELETE FROM app.users WHERE id=:id'),args)
engine.dispose()
print('fixture-ok')
"""


def fixture(body):
    result = subprocess.run(
        COMPOSE + ["run", "--rm", "-T", "test-auth", "python", "-c", FIXTURE],
        input=json.dumps(body),
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("ACCOUNT_FIXTURE_FAILED")


def main():
    env = dict(
        line.split("=", 1)
        for line in (ROOT / "deploy/.env").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    base = "http://127.0.0.1:" + env["CORPUS_HTTP_PORT"]
    actor = {
        "id": str(uuid4()),
        "email": f"sdk-{uuid4().hex}@example.test",
        "password": secrets.token_urlsafe(24),
    }
    destination = ROOT / "tmp" / "pi-s1" / uuid4().hex
    destination.mkdir(parents=True)
    fixture({"mode": "create", **actor})
    phase = "login"
    results = []
    try:
        with httpx.Client(
            base_url=base, timeout=20, headers={"Origin": base}
        ) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"email": actor["email"], "password": actor["password"]},
            )
            login.raise_for_status()
            client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            created = client.post(
                "/api/v1/agent/sessions", json={"scope": {"scope_kind": "account"}}
            )
            created.raise_for_status()
            sid = created.json()["session_id"]
            scope_digest = created.json()["scope_digest"]
            for attempt in range(2):
                phase = f"run-{attempt + 1}"
                queued = client.post(
                    f"/api/v1/agent/sessions/{sid}/runs", json={
                        "request_key": str(uuid4()), "scope_digest": scope_digest,
                        "message": "Create one project for the checkpoint verification." if attempt == 0
                        else "Continue using the previously created project; do not create another.",
                    }
                )
                queued.raise_for_status()
                run_id = queued.json()["run_id"]
                config = {
                    "baseUrl": base,
                    "hostKey": env["CORPUS_AGENT_HOST_KEY"],
                    "runId": run_id,
                    "directory": str(destination / f"process-{attempt + 1}"),
                }
                # Each run uses a new OS process. No SessionManager or model state
                # survives outside the API-authorized object-store checkpoint.
                process = subprocess.run(
                    [os.getenv("CORPUS_NODE", "node"), "services/agent-runtime/src/s1-run-smoke.ts"],
                    input=json.dumps(config), text=True, encoding="utf-8",
                    capture_output=True, cwd=ROOT, timeout=90, check=False,
                )
                if process.returncode != 0:
                    failure = json.loads(process.stderr) if process.stderr.startswith("{") else {}
                    code = failure.get("code", "FIXED_SDK_HOST_FAILED")
                    raise RuntimeError(code if isinstance(code, str) and code.replace("_", "").isalnum() else "FIXED_SDK_HOST_FAILED")
                result = json.loads(process.stdout)
                assert result["model_requests"] == (2 if attempt == 0 else 1)
                assert result["final"]["state"] == "SUCCEEDED"
                assert result["restored"] is (attempt == 1)
                assert result["new_tool_executions"] == (1 if attempt == 0 else 0)
                assert result["inherited_tool_results"] == attempt
                run = client.get(f"/api/v1/agent/runs/{run_id}")
                run.raise_for_status()
                assert run.json()["state"] == "SUCCEEDED"
                if attempt == 0:
                    output = client.get(f"/api/v1/agent/runs/{run_id}/invocations/{result['invocation_id']}")
                    output.raise_for_status()
                    assert output.json()["data"]["owner_id"] == actor["id"]
                    assert output.json()["data"]["id"] == result["project"]["id"]
                else:
                    assert result["project"] == results[0]["project"]
                    assert result["invocation_id"] == results[0]["invocation_id"]
                    assert result["base_checkpoint"] == results[0]["checkpoint"]
                    assert result["checkpoint"]["checkpoint_id"] != results[0]["checkpoint"]["checkpoint_id"]
                    assert result["project"]["id"] in json.dumps(result["final_model_content"])
                projects = client.get("/api/v1/projects")
                projects.raise_for_status()
                assert len(projects.json()["items"]) == 1
                events = client.get(f"/api/v1/agent/runs/{run_id}/events").json()["items"]
                sequence = [row["sequence"] for row in events]
                assert sequence == list(range(1, len(sequence) + 1))
                kinds = [row["kind"] for row in events]
                assert "sdk.agent_end" in kinds and "sdk.agent_settled" in kinds
                assert kinds.index("sdk.agent_end") < kinds.index("sdk.agent_settled")
                for forbidden in (env["CORPUS_AGENT_HOST_KEY"], actor["password"], login.json()["csrf_token"]):
                    assert forbidden not in process.stdout
                    for archive in destination.rglob("*.jsonl"):
                        assert forbidden not in archive.read_text(encoding="utf-8")
                result.update(durable_event_kinds=kinds, durable_event_count=len(events))
                results.append(result)
            report = {
                "status": "passed", "runs": results,
                "api_database": "actual_postgresql", "transport": "actual_http",
                "archive_storage": "private_versioned_S3_through_API",
                "processes": 2, "same_session": True, "project_count": 1,
                "old_invocation_reexecuted": False,
                "model_network_mode": "disabled_fixed_provider", "production_available": False,
                "limits": ["Completed linear checkpoints only; ambiguous in-flight calls require review.",
                           "No real external model, research material egress, or complete production recovery acceptance."],
            }
            (destination / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({"status": "passed", "report": str(destination / "result.json"),
                              "processes": 2, "model_requests": [2, 1], "terminal_states": ["SUCCEEDED", "SUCCEEDED"]}))
    except Exception as error:
        failure = {"status": "failed", "phase": phase, "error_type": type(error).__name__,
                   "completed_runs": results, "production_available": False}
        if isinstance(error, RuntimeError):
            failure["code"] = str(error)
        (destination / "failure.json").write_text(json.dumps(failure, indent=2), encoding="utf-8")
        print(json.dumps({"status": "failed", "report": str(destination / "failure.json")}))
        raise
    finally:
        fixture({"mode": "cleanup", "id": actor["id"]})


if __name__ == "__main__":
    main()
