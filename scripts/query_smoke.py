"""Deployed manual research workflow; synthetic approved fixture, no real D12 approval."""

import argparse
import hashlib
import json
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from scripts.source_release_smoke import checked
from scripts.source_sync_smoke import COMPOSE, ROOT


def fixture(mode, body):
    result = subprocess.run(
        COMPOSE
        + ["run", "--rm", "-T", "test-index", "python", "-m", "scripts.query_fixture"],
        input=json.dumps({**body, "mode": mode}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("QUERY_FIXTURE_" + mode.upper() + "_FAILED")
    return json.loads(result.stdout.strip().splitlines()[-1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:60636")
    parser.add_argument("--ui-hold-seconds", type=int, default=0)
    parser.add_argument("--credentials-stdin", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.ui_hold_seconds <= 900:
        parser.error("UI hold must be between 0 and 900 seconds")
    password = (
        json.load(sys.stdin)["password"]
        if args.credentials_stdin
        else secrets.token_urlsafe(32)
    )
    if not isinstance(password, str) or len(password) < 16:
        parser.error("A test password of at least 16 characters is required")
    tag = uuid4().hex
    body = {
        "source_id": "fixture-release-" + tag,
        "accounts": {
            name: {
                "id": str(uuid4()),
                "email": f"query-{name}-{tag}@example.test",
                "password": password,
            }
            for name in ("admin", "owner", "editor", "viewer", "outsider")
        },
    }
    output = ROOT / "tmp" / "query-smoke" / tag
    output.mkdir(parents=True)
    report = {
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "fixture_only": True,
        "source_id": body["source_id"],
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        **{
            name: []
            for name in (
                "snapshots",
                "snapshot_actions",
                "snapshot_lists",
                "queries",
                "query_actions",
                "query_lists",
                "hit_pages",
                "contexts",
                "negative_checks",
            )
        },
    }
    clients = {}

    def save():
        (output / "result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def request(who, method, path, data=None, expected=200, record=None, key=None):
        client, csrf = clients[who]
        headers = {"Origin": args.base_url, "X-CSRF-Token": csrf}
        if method != "GET":
            headers["Idempotency-Key"] = key or uuid4().hex
        response = client.request(
            method,
            "/api/v1" + path,
            json=data if method != "GET" else None,
            headers=headers,
        )
        if isinstance(expected, tuple):
            if response.status_code not in expected:
                checked(response, expected[0])
            value = response.json()
        else:
            value = checked(response, expected)
        if record:
            report[record].append(value)
        save()
        return value

    def poll(path, target, record):
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            item = request("viewer", "GET", path)
            if item["state"] == target:
                report[record].append(item)
                save()
                return item
            if item["state"] in {"FAILED", "CANCELLED"}:
                report[record].append(item)
                save()
                raise RuntimeError("RESEARCH_TASK_FAILED")
            time.sleep(0.25)
        raise RuntimeError("RESEARCH_TASK_TIMEOUT")

    try:
        report["fixture"] = fixture("setup", body)
        for who, account in body["accounts"].items():
            client = httpx.Client(base_url=args.base_url, timeout=30)
            login = checked(
                client.post(
                    "/api/v1/auth/login",
                    headers={"Origin": args.base_url},
                    json={"email": account["email"], "password": password},
                ),
                200,
            )
            clients[who] = client, login["csrf_token"]
        project = request(
            "owner",
            "POST",
            "/projects",
            {"name": "真实研究检索验收 " + tag[:8]},
            expected=201,
        )
        project_id = project["id"]
        request(
            "owner",
            "PUT",
            f"/projects/{project_id}/members/{body['accounts']['viewer']['id']}",
            {"role": "viewer"},
        )
        report["project_id"] = project_id
        version = report["fixture"]["versions"][0]
        policy_path = (
            f"/admin/sources/{body['source_id']}/policies/{version['acquisition_id']}"
        )
        approved = request(
            "admin",
            "POST",
            policy_path,
            {
                "expected_revision": 0,
                "decision": "allow",
                "review_note": "Authored query fixture only; not real Tatoeba permission",
                "evidence_urls": ["https://example.test/query-fixture"],
            },
        )
        release = request(
            "admin",
            "POST",
            f"/admin/sources/{body['source_id']}/releases",
            {
                "index_id": version["index_id"],
                "expected_policy_revision": approved["policy"]["revision"],
            },
            expected=201,
        )["release"]
        mounted = request(
            "owner",
            "POST",
            f"/projects/{project_id}/mounts",
            {"source_snapshot_id": release["source_snapshot_id"]},
            expected=201,
        )
        mount_id = mounted["mount"]["id"]
        request(
            "viewer",
            "POST",
            f"/projects/{project_id}/snapshots",
            {"mount_ids": [mount_id]},
            expected=403,
            record="negative_checks",
        )
        created = request(
            "owner",
            "POST",
            f"/projects/{project_id}/snapshots",
            {"mount_ids": [mount_id]},
            expected=202,
            record="snapshot_actions",
        )
        snapshot_id = created["snapshot"]["id"]
        report["snapshot_id"] = snapshot_id
        poll(f"/projects/{project_id}/snapshots/{snapshot_id}", "READY", "snapshots")
        request(
            "viewer",
            "GET",
            f"/projects/{project_id}/snapshots",
            record="snapshot_lists",
        )
        ast = {
            "dsl_version": "corpus-query/v1",
            "unit": "character",
            "within": "sentence",
            "overlap": "all",
            "pattern": {"type": "literal", "value": "Hello"},
        }
        key = uuid4().hex
        started = request(
            "viewer",
            "POST",
            f"/projects/{project_id}/queries",
            {
                "snapshot_id": snapshot_id,
                "query": ast,
                "page_size": 50,
                "context_codepoints": 40,
            },
            expected=202,
            record="query_actions",
            key=key,
        )
        report["query_run_id"], report["result_set_id"] = (
            started["query_run_id"],
            started["result_set_id"],
        )
        result_path = f"/projects/{project_id}/result-sets/{started['result_set_id']}"
        request(
            "viewer",
            "GET",
            result_path + "/hits",
            expected=(200, 202),
            record="hit_pages",
        )
        complete = poll(
            f"/projects/{project_id}/queries/{started['query_run_id']}",
            "SUCCEEDED",
            "queries",
        )
        assert (
            complete["total_hits"] == 120
            and complete["matched_segments"] == complete["matched_documents"] == 60
        )
        cursor, all_hits = None, []
        while True:
            page = request(
                "viewer",
                "GET",
                result_path + "/hits" + ("?cursor=" + cursor if cursor else ""),
                record="hit_pages",
            )
            all_hits.extend(page["hits"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        text_value = "Hello 😀 é Hello."
        expected = [
            (str(i), p, p + 5)
            for i in range(100, 160)
            for p in range(len(text_value))
            if text_value.startswith("Hello", p)
        ]
        assert [
            (h["source_sentence_id"], h["start_cp"], h["end_cp"]) for h in all_hits
        ] == expected
        detail = request(
            "viewer", "GET", result_path + "/hits/51/context", record="contexts"
        )
        assert detail["text"] == text_value and detail["hit_ref"]["ordinal"] == 51
        request(
            "viewer", "GET", f"/projects/{project_id}/queries", record="query_lists"
        )
        request(
            "admin",
            "GET",
            result_path + "/hits",
            expected=404,
            record="negative_checks",
        )
        replay = request(
            "viewer",
            "POST",
            f"/projects/{project_id}/queries",
            {
                "snapshot_id": snapshot_id,
                "query": ast,
                "page_size": 50,
                "context_codepoints": 40,
            },
            expected=202,
            record="query_actions",
            key=key,
        )
        assert replay["query_run_id"] == started["query_run_id"]
        report["status"] = "passed"
        report["ui_accounts"] = {
            name: {"id": account["id"], "email": account["email"]}
            for name, account in body["accounts"].items()
        }
        save()
        if args.ui_hold_seconds:
            marker = output / "continue"
            print("UI_HOLD " + str(marker), flush=True)
            deadline = time.monotonic() + args.ui_hold_seconds
            while time.monotonic() < deadline and not marker.exists():
                time.sleep(1)
        current = request("admin", "GET", policy_path)
        request(
            "admin",
            "POST",
            policy_path,
            {
                "expected_revision": current["revision"],
                "decision": "deny",
                "review_note": "End fixture authorization",
                "evidence_urls": ["https://example.test/query-fixture"],
            },
        )
        request(
            "viewer",
            "GET",
            result_path + "/hits",
            expected=404,
            record="negative_checks",
        )
        report["authorization_withdrawal_verified"] = True
        save()
        if args.ui_hold_seconds:
            marker = output / "revoked-continue"
            print("REVOKED_UI_HOLD " + str(marker), flush=True)
            deadline = time.monotonic() + args.ui_hold_seconds
            while time.monotonic() < deadline and not marker.exists():
                time.sleep(1)
    except BaseException as error:
        report["status"] = "failed"
        report["error_type"] = type(error).__name__
        raise
    finally:
        for client, _ in clients.values():
            client.close()
        try:
            report["cleanup"] = fixture("cleanup", body)
        finally:
            report["finished_at"] = datetime.now(UTC).isoformat()
            save()
            print(str(output / "result.json"), flush=True)


if __name__ == "__main__":
    main()
