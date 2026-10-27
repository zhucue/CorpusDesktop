"""Material egress and independent export approval cannot be granted by tool input."""

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.api import agent_tools, source_releases
from services.api.errors import ApiError


def test_tool_cannot_supply_export_approval_or_confirm_note_acceptance():
    args = {
        "policy_kind": "source",
        "source_id": "D12",
        "acquisition_id": str(uuid4()),
        "expected_revision": 0,
        "decision": "allow",
        "review_note": "review",
        "evidence_urls": ["https://example.test/license"],
        "export_decision": "allow",
    }
    with pytest.raises(ValidationError):
        agent_tools.PolicyUpdate.model_validate(args)
    for tool, code in [
        ("notes.accept", "HUMAN_AUTHORIZATION_REQUIRED"),
        ("notes.get", "MODEL_EGRESS_DENIED"),
        ("evidence.get", "MODEL_EGRESS_DENIED"),
        ("notes.create", "MODEL_EGRESS_DENIED"),
    ]:
        with pytest.raises(ApiError) as caught:
            agent_tools.dispatch(
                None,
                None,
                {"scope_kind": "project"},
                tool,
                {"confirmed": True},
                uuid4(),
            )
        assert caught.value.code == code


def test_tool_preserves_only_same_epoch_fixed_license_approval():
    source = SimpleNamespace(identity_revision=4)
    acquired = SimpleNamespace(
        source_identity={"source": "D12"},
        manifest_sha256="a" * 64,
        manifest={"license": {"text": "fixture"}},
    )
    policy = SimpleNamespace(
        source_identity_revision=4,
        acquisition_manifest_sha256="a" * 64,
        license_sha256=source_releases.digest(acquired.manifest["license"]),
        export_decision="allow",
    )
    with patch.object(source_releases, "identity", return_value={"source": "D12"}):
        assert agent_tools.retained_export_decision(source, acquired, policy) == "allow"
        source.identity_revision = 5
        assert agent_tools.retained_export_decision(source, acquired, policy) == "deny"
        source.identity_revision = 4
        acquired.manifest_sha256 = "b" * 64
        assert agent_tools.retained_export_decision(source, acquired, policy) == "deny"


def test_outcome_metadata_drops_body_excerpt_counts_and_transport():
    item = {
        "id": str(uuid4()),
        "job_id": str(uuid4()),
        "project_id": str(uuid4()),
        "state": "SUCCEEDED",
        "title": "private",
        "body": "private",
        "counts": {"total_hits": 999},
        "result": {"filename": "secret", "sha256": "a" * 64},
        "url": "private",
    }
    result = agent_tools.export_metadata(item)
    assert set(result) == {"export_id", "job_id", "project_id", "state", "next_action"}
    item.update(kind="EXPORT")
    assert set(agent_tools.job_metadata(None, item, None)) == {
        "job_id",
        "export_id",
        "project_id",
        "kind",
        "state",
        "next_action",
    }


def test_export_checkpoint_requires_success_and_observed_exact_job():
    from services.api.agent_checkpoints import necessary_results

    ident = uuid4()
    invocation = SimpleNamespace(
        tool_name="exports.create",
        response={
            "result": {"status": "accepted", "job_id": str(ident)},
            "data": {"export_id": str(ident)},
        },
    )
    job = SimpleNamespace(id=ident, kind="EXPORT", state="RUNNING")
    calls = [invocation]
    db = SimpleNamespace(scalars=lambda _: calls, get=lambda *_: job)
    run = SimpleNamespace(id=uuid4())
    with pytest.raises(ApiError) as pending:
        necessary_results(db, run)
    assert pending.value.code == "JOBS_PENDING"
    job.state = "SUCCEEDED"
    with pytest.raises(ApiError) as missing:
        necessary_results(db, run)
    assert missing.value.code == "JOB_RESULT_NOT_OBSERVED"
    calls.append(
        SimpleNamespace(
            tool_name="exports.get",
            response={
                "result": {"status": "succeeded"},
                "data": {"export_id": str(ident), "state": "SUCCEEDED"},
            },
        )
    )
    necessary_results(db, run)
