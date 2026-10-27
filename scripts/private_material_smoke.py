"""Deployed private TXT import and mixed research workflow; synthetic shared permission only."""

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
                "email": f"private-{name}-{tag}@example.test",
                "password": password,
            }
            for name in ("admin", "owner", "editor", "viewer", "outsider")
        },
    }
    output = ROOT / "tmp" / "private-material-smoke" / tag
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
                "imports",
                "import_actions",
                "import_lists",
                "materials",
                "material_lists",
                "validated_upload_lists",
                "validation_jobs",
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
        raw_files = [
            (
                "unicode-first.txt",
                b"\xef\xbb\xbf" + "Hello.\r\nHello 😀 é.\nHello!".encode(),
            ),
            ("second-file.txt", b"Hello.\r\nHello!"),
        ]
        imports, canonical = [], {}
        for filename, raw in raw_files:
            uploaded = request(
                "owner",
                "POST",
                f"/projects/{project_id}/uploads",
                {
                    "filename": filename,
                    "size": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "media_type": "text/plain",
                },
                expected=201,
            )
            owner_client, csrf = clients["owner"]
            checked(
                owner_client.put(
                    uploaded["upload_url"],
                    content=raw,
                    headers={
                        "Origin": args.base_url,
                        "X-CSRF-Token": csrf,
                        "Content-Type": "text/plain",
                    },
                ),
                200,
            )
            validation = request(
                "owner",
                "POST",
                f"/uploads/{uploaded['upload_id']}/complete",
                {},
                expected=202,
            )
            poll(f"/jobs/{validation['job_id']}", "SUCCEEDED", "validation_jobs")
            action = request(
                "owner",
                "POST",
                f"/projects/{project_id}/imports",
                {"upload_id": uploaded["upload_id"], "language": "eng"},
                expected=202,
                record="import_actions",
            )
            imported = poll(
                f"/projects/{project_id}/imports/{action['import_id']}",
                "SUCCEEDED",
                "imports",
            )
            imports.append(imported)
            canonical[imported["material_id"]] = raw.decode("utf-8-sig")
            request(
                "viewer",
                "GET",
                f"/projects/{project_id}/materials/{imported['material_id']}",
                record="materials",
            )
        for path, record in (
            ("uploads?state=VALIDATED", "validated_upload_lists"),
            ("imports", "import_lists"),
            ("materials", "material_lists"),
        ):
            request("viewer", "GET", f"/projects/{project_id}/{path}", record=record)
        repeated = request(
            "owner",
            "POST",
            f"/projects/{project_id}/imports",
            {"upload_id": imports[0]["upload_id"], "language": "eng"},
            expected=202,
            record="import_actions",
        )
        assert repeated["import_id"] == imports[0]["id"]
        request(
            "viewer",
            "POST",
            f"/projects/{project_id}/imports",
            {"upload_id": imports[0]["upload_id"], "language": "eng"},
            expected=403,
            record="negative_checks",
        )
        request(
            "admin",
            "GET",
            f"/projects/{project_id}/materials",
            expected=404,
            record="negative_checks",
        )
        revisions = [item["result"]["id"] for item in imports]
        ast = {
            "dsl_version": "corpus-query/v1",
            "unit": "character",
            "within": "sentence",
            "overlap": "all",
            "pattern": {"type": "literal", "value": "Hello"},
        }
        results = {}
        for mode, mounts, total, segments, docs in (
            ("private", [], 5, 5, 2),
            ("mixed", [mount_id], 125, 65, 62),
        ):
            created = request(
                "owner",
                "POST",
                f"/projects/{project_id}/snapshots",
                {"mount_ids": mounts, "material_revision_ids": revisions},
                expected=202,
                record="snapshot_actions",
            )
            snapshot_id = created["snapshot"]["id"]
            snapshot = poll(
                f"/projects/{project_id}/snapshots/{snapshot_id}", "READY", "snapshots"
            )
            assert snapshot["counts"]["document_units"] == {
                "source_records": 62 if mode == "mixed" else 0,
                "private_files": 2,
            }
            request(
                "viewer",
                "GET",
                f"/projects/{project_id}/snapshots",
                record="snapshot_lists",
            )
            key = uuid4().hex
            payload = {
                "snapshot_id": snapshot_id,
                "query": ast,
                "page_size": 50,
                "context_codepoints": 40,
            }
            started = request(
                "viewer",
                "POST",
                f"/projects/{project_id}/queries",
                payload,
                expected=202,
                record="query_actions",
                key=key,
            )
            result_path = (
                f"/projects/{project_id}/result-sets/{started['result_set_id']}"
            )
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
                complete["total_hits"],
                complete["matched_segments"],
                complete["matched_documents"],
            ) == (total, segments, docs)
            assert complete["matched_document_units"] == {
                "source_records": 60 if mode == "mixed" else 0,
                "private_files": 2,
            }
            all_hits, cursor = [], None
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
            assert len(all_hits) == total
            actual_private = sorted(
                (h["material_id"], h["start_cp"], h["end_cp"])
                for h in all_hits
                if h["origin_kind"] == "private"
            )
            expected_private = sorted(
                (ident, offset, offset + 5)
                for ident, text in canonical.items()
                for offset in range(len(text))
                if text.startswith("Hello", offset)
            )
            assert actual_private == expected_private
            for hit in all_hits:
                if hit["origin_kind"] == "private":
                    assert (
                        hit["source_id"] is None
                        and hit["source_sentence_id"] is None
                        and hit["source_url"] is None
                    )
            private_hit = next(
                h
                for h in all_hits
                if h["origin_kind"] == "private" and h["context_start_cp"] > 0
            )
            detail = request(
                "viewer",
                "GET",
                result_path + f"/hits/{private_hit['hit_ref']['ordinal']}/context",
                record="contexts",
            )
            assert (
                detail["text"][
                    detail["start_cp"] - detail["context_start_cp"] : detail["end_cp"]
                    - detail["context_start_cp"]
                ]
                == "Hello"
            )
            if mode == "mixed":
                source_hits = [h for h in all_hits if h["origin_kind"] == "source"]
                source_text = "Hello 😀 é Hello."
                expected_source = [
                    (str(sid), pos, pos + 5)
                    for sid in range(100, 160)
                    for pos in range(len(source_text))
                    if source_text.startswith("Hello", pos)
                ]
                assert [
                    (h["source_sentence_id"], h["start_cp"], h["end_cp"])
                    for h in source_hits
                ] == expected_source
                assert all(h["source_id"] == body["source_id"] for h in source_hits)
            replay = request(
                "viewer",
                "POST",
                f"/projects/{project_id}/queries",
                payload,
                expected=202,
                record="query_actions",
                key=key,
            )
            assert replay["result_set_id"] == started["result_set_id"]
            results[mode] = {
                "snapshot_id": snapshot_id,
                "query_run_id": started["query_run_id"],
                "result_set_id": started["result_set_id"],
                "result_path": result_path,
            }
        request(
            "viewer", "GET", f"/projects/{project_id}/queries", record="query_lists"
        )
        # Correcting the human-selected language adds a revision without modifying the pinned snapshot.
        corrected = request(
            "owner",
            "POST",
            f"/projects/{project_id}/imports",
            {"upload_id": imports[0]["upload_id"], "language": "cmn"},
            expected=202,
            record="import_actions",
        )
        correction = poll(
            f"/projects/{project_id}/imports/{corrected['import_id']}",
            "SUCCEEDED",
            "imports",
        )
        assert (
            correction["material_id"] == imports[0]["material_id"]
            and correction["result"]["id"] != revisions[0]
        )
        material = request(
            "viewer",
            "GET",
            f"/projects/{project_id}/materials/{correction['material_id']}",
            record="materials",
        )
        assert len(material["revisions"]) == 2
        fixed = request(
            "viewer",
            "GET",
            f"/projects/{project_id}/snapshots/{results['private']['snapshot_id']}",
            record="snapshots",
        )
        assert {m["material_revision_id"] for m in fixed["members"]} == set(revisions)
        request(
            "owner",
            "POST",
            f"/projects/{project_id}/snapshots",
            {"material_revision_ids": [revisions[0], correction["result"]["id"]]},
            expected=409,
            record="negative_checks",
        )
        report["results"] = results
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
                "review_note": "End fixture shared authorization",
                "evidence_urls": ["https://example.test/query-fixture"],
            },
        )
        request(
            "viewer",
            "GET",
            results["mixed"]["result_path"] + "/hits",
            expected=404,
            record="negative_checks",
        )
        surviving = request(
            "viewer",
            "GET",
            results["private"]["result_path"] + "/hits",
            record="hit_pages",
        )
        assert surviving["total_hits"] == 5
        report["shared_withdrawal_blocks_mixed_but_preserves_private"] = True
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
