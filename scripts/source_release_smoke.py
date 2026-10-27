"""Deployed HTTP policy/publication/mount acceptance using synthetic real indexes.

Run only in the parent's coordinated window. No real D12 permission is modified.
Optional stdin password allows browser inspection without a credential file/log.
"""

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

from scripts.source_sync_smoke import COMPOSE, ROOT


def fixture(mode, body):
    result = subprocess.run(
        COMPOSE
        + [
            "run",
            "--rm",
            "-T",
            "test-index",
            "python",
            "-m",
            "scripts.release_fixture",
        ],
        input=json.dumps({**body, "mode": mode}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        # The child never prints credentials, but do not echo arbitrary subprocess output.
        raise RuntimeError("RELEASE_FIXTURE_" + mode.upper() + "_FAILED")
    return json.loads(result.stdout.strip().splitlines()[-1])


def checked(response, expected):
    if response.status_code != expected:
        try:
            code = response.json().get("code", "HTTP_STATUS_MISMATCH")
        except ValueError:
            code = "HTTP_STATUS_MISMATCH"
        raise RuntimeError(
            code
            if isinstance(code, str) and code.replace("_", "").isalnum()
            else "HTTP_STATUS_MISMATCH"
        )
    return response.json() if response.content else None


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
                "email": f"release-{name}-{tag}@example.test",
                "password": password,
            }
            for name in ("admin", "owner", "editor", "viewer", "outsider")
        },
    }
    output = ROOT / "tmp" / "source-release-smoke" / tag
    output.mkdir(parents=True)
    report = {
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "fixture_only": True,
        "source_id": body["source_id"],
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "policies": [],
        "policy_actions": [],
        "releases": [],
        "release_actions": [],
        "mounts": [],
        "mount_actions": [],
        "mount_lists": [],
        "manifests": [],
        "version_lists": [],
        "negative_checks": [],
    }
    clients = {}

    def save():
        (output / "result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def request(who, method, path, data=None, *, key=None, expected=200, record=None):
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
        value = checked(response, expected)
        if record:
            report[record].append(value)
        save()
        return value

    try:
        report["fixture"] = fixture("setup", body)
        for name, account in body["accounts"].items():
            client = httpx.Client(base_url=args.base_url, timeout=60, trust_env=False)
            clients[name] = (client, "")
            login = checked(
                client.post(
                    "/api/v1/auth/login",
                    json={"email": account["email"], "password": password},
                    headers={"Origin": args.base_url},
                ),
                200,
            )
            clients[name] = (client, login["csrf_token"])
        source = body["source_id"]
        versions = report["fixture"]["versions"]
        admin_path = f"/admin/sources/{source}"
        first_project = request(
            "owner",
            "POST",
            "/projects",
            {"name": "Release fixture project"},
            expected=201,
        )["id"]
        second_project = request(
            "owner",
            "POST",
            "/projects",
            {"name": "Release fixture second project"},
            expected=201,
        )["id"]
        for name in ("viewer", "editor"):
            request(
                "owner",
                "PUT",
                f"/projects/{first_project}/members/{body['accounts'][name]['id']}",
                {"role": name},
            )
        project_path = f"/projects/{first_project}/mounts"

        def policy(version, decision):
            path = admin_path + "/policies/" + version["acquisition_id"]
            old = request("admin", "GET", path, record="policies")
            return request(
                "admin",
                "POST",
                path,
                {
                    "expected_revision": old["revision"],
                    "decision": decision,
                    "review_note": "Explicit authored synthetic fixture permission; not Tatoeba approval",
                    "evidence_urls": ["https://example.test/authored-fixture"],
                },
                record="policy_actions",
            )

        first_policy = policy(versions[0], "allow")
        publish_body = {
            "index_id": versions[0]["index_id"],
            "expected_policy_revision": first_policy["policy"]["revision"],
        }
        publish_key = uuid4().hex
        published = request(
            "admin",
            "POST",
            admin_path + "/releases",
            publish_body,
            key=publish_key,
            expected=201,
            record="release_actions",
        )["release"]
        same = request(
            "admin",
            "POST",
            admin_path + "/releases",
            publish_body,
            expected=201,
            record="release_actions",
        )
        assert (
            same["existing"]
            and same["release"]["release_id"] == published["release_id"]
        )
        mount_body = {"source_snapshot_id": published["source_snapshot_id"]}
        mount_key = uuid4().hex
        mounted = request(
            "owner",
            "POST",
            project_path,
            mount_body,
            key=mount_key,
            expected=201,
            record="mount_actions",
        )["mount"]
        request(
            "owner",
            "POST",
            f"/projects/{second_project}/mounts",
            mount_body,
            expected=201,
            record="mount_actions",
        )
        mount_path = project_path + "/" + mounted["id"]
        manifest = request(
            "viewer", "GET", mount_path + "/manifest", record="manifests"
        )
        assert manifest["manifest_sha256"] == versions[0]["manifest_sha256"]
        assert manifest["manifest"]["counts"]["sentences"] == 4
        assert "object_key" not in json.dumps(
            manifest
        ) and "version_id" not in json.dumps(manifest)
        request("viewer", "GET", project_path, record="mount_lists")
        for who in ("admin", "outsider"):
            error = request(who, "GET", mount_path + "/manifest", expected=404)
            report["negative_checks"].append(
                {"actor": who, "operation": "private_manifest", "code": error["code"]}
            )
        error = request("viewer", "POST", project_path, mount_body, expected=403)
        report["negative_checks"].append(
            {"actor": "viewer", "operation": "mount_create", "code": error["code"]}
        )
        second_policy = policy(versions[1], "allow")
        new_release = request(
            "admin",
            "POST",
            admin_path + "/releases",
            {
                "index_id": versions[1]["index_id"],
                "expected_policy_revision": second_policy["policy"]["revision"],
            },
            expected=201,
            record="release_actions",
        )["release"]
        old_mount = request("viewer", "GET", mount_path, record="mounts")
        assert old_mount["release"]["index_id"] == versions[0]["index_id"]
        assert (
            old_mount["release"]["source_snapshot_id"]
            != new_release["source_snapshot_id"]
        )
        policy(versions[0], "deny")
        for who, method, path, data, key in (
            ("viewer", "GET", mount_path + "/manifest", None, None),
            ("owner", "POST", project_path, mount_body, mount_key),
            ("admin", "POST", admin_path + "/releases", publish_body, publish_key),
        ):
            error = request(who, method, path, data, key=key, expected=403)
            report["negative_checks"].append(
                {
                    "actor": who,
                    "operation": "denied_replay_or_read",
                    "code": error["code"],
                }
            )
        policy(versions[0], "allow")
        replay = request(
            "owner",
            "POST",
            project_path,
            mount_body,
            key=mount_key,
            expected=201,
            record="mount_actions",
        )
        assert replay["mount"]["release"]["current_policy_revision"] == 3
        removable = request(
            "editor",
            "POST",
            project_path,
            {"source_snapshot_id": new_release["source_snapshot_id"]},
            expected=201,
            record="mount_actions",
        )["mount"]
        request(
            "editor",
            "POST",
            project_path + "/" + removable["id"] + "/remove",
            {},
            record="mount_actions",
        )
        request("viewer", "GET", project_path, record="mount_lists")
        request("viewer", "GET", mount_path + "/manifest", record="manifests")
        request("viewer", "GET", f"/sources/{source}/versions", record="version_lists")
        request(
            "viewer",
            "GET",
            f"/sources/{source}/releases/{published['release_id']}",
            record="releases",
        )
        real_source = request("viewer", "GET", "/sources/D12")
        assert (
            real_source["license_status"] == "pending_review"
            and not real_source["capabilities"]["fulltext_analysis"]
        )
        report["real_d12_unchanged"] = True
        report["publication_verification"] = (
            "Small manifest exact SHA and fixed-version tar HEAD/length/etag; full tar SHA not recomputed at publication"
        )
        report["status"] = "passed"
        report["ui"] = {
            "source_id": source,
            "project_id": first_project,
            "second_project_id": second_project,
            "mount_id": mounted["id"],
            "accounts": {
                name: {"id": value["id"], "email": value["email"]}
                for name, value in body["accounts"].items()
            },
        }
        save()
        if args.ui_hold_seconds:
            marker = output / "continue"
            print(
                json.dumps(
                    {
                        "status": "awaiting_ui",
                        "report": str(output / "result.json"),
                        "continue_marker": str(marker),
                    }
                ),
                flush=True,
            )
            until = time.monotonic() + args.ui_hold_seconds
            while time.monotonic() < until and not marker.exists():
                time.sleep(1)
    except BaseException as exc:
        report["status"] = "failed"
        report["failure_type"] = type(exc).__name__
        save()
        raise
    finally:
        for client, _ in clients.values():
            client.close()
        report["cleanup"] = fixture("cleanup", body)
        report["finished_at"] = datetime.now(UTC).isoformat()
        save()
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(output / "result.json"),
                "cleaned": report["cleanup"]["cleaned"],
            }
        )
    )


if __name__ == "__main__":
    main()
