"""Browser-facing Agent control and safe transcript projection, K09 subset.

This contract grants neither model network access nor material-bearing scope.
The SDK checkpoint remains private and is never a browser message response.
"""

from datetime import datetime
from typing import Annotated, Any, ClassVar, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from contracts.releases import StrictView

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
AgentState = Literal[
    "QUEUED", "RUNNING", "WAITING_JOB", "WAITING_REVIEW",
    "CANCELLED", "SUCCEEDED", "FAILED",
]
ConfigID = Annotated[str, Field(pattern=r"^(local-fixture-v1|openai-[a-f0-9]{48})$")]


class AccountScope(StrictView):
    scope_kind: Literal["account"]


class PlatformScope(StrictView):
    scope_kind: Literal["platform"]


class ProjectScope(StrictView):
    scope_kind: Literal["project"]
    project_id: UUID
    snapshot_ids: list[UUID] = Field(default_factory=list, max_length=0)
    material_revision_ids: list[UUID] = Field(default_factory=list, max_length=0)
    alignment_overlay_revision: None = None
    result_refs: list[str] = Field(default_factory=list, max_length=0)


AgentScope = Annotated[
    AccountScope | PlatformScope | ProjectScope, Field(discriminator="scope_kind")
]


class SessionInput(StrictView):
    scope: AgentScope


class RunInput(StrictView):
    request_key: UUID
    message: str = Field(min_length=1, max_length=8000)
    scope_digest: Digest

    @field_validator("message")
    @classmethod
    def nonblank_message(cls, value):
        if not value.strip():
            raise ValueError("Message must not be blank")
        return value


class ManifestBase(StrictView):
    sdk_package: Literal["@earendil-works/pi-coding-agent"]
    sdk_version: Literal["1.3.0"]
    session_version: Literal[3]
    tool_schema: Literal["s3-outcomes-tools-v1"]


class FixtureManifest(ManifestBase):
    host_policy: Literal["corpus-k09-linear-v1"]
    provider: Literal["corpus-s1-fixed"]
    model: Literal["fixed-project-v1"]
    resource_config: Literal["corpus-empty-resources-v1"]


class OpenAIManifest(ManifestBase):
    host_policy: Literal["corpus-k09-openai-v1"]
    provider: Literal["corpus-openai-compatible"]
    model: str = Field(min_length=1)
    resource_config: Literal["corpus-explicit-resources-v1"]
    model_api: Literal["openai-completions", "openai-responses"]
    model_config_sha256: Digest


RuntimeManifest = Annotated[FixtureManifest | OpenAIManifest, Field(discriminator="provider")]


class RuntimeView(StrictView):
    model_config: ClassVar[ConfigDict] = {"json_schema_extra": {"oneOf": [
        {"properties": {
            "mode": {"const": "unconfigured"}, "fixture_enabled": {"const": False},
            "can_submit": {"const": False}, "config_id": {"type": "null"},
            "runtime_manifest": {"type": "null"}, "reason": {"const": "MODEL_NOT_CONFIGURED"},
        }},
        {"properties": {
            "mode": {"const": "fixture"}, "fixture_enabled": {"const": True},
            "can_submit": {"const": True}, "config_id": {"const": "local-fixture-v1"},
            "runtime_manifest": {"type": "object", "properties": {"provider": {"const": "corpus-s1-fixed"}}},
            "reason": {"type": "null"},
        }},
        {"properties": {
            "mode": {"const": "openai-compatible"}, "fixture_enabled": {"const": False},
            "can_submit": {"const": False}, "config_id": {"type": "null"},
            "runtime_manifest": {"type": "null"}, "reason": {"const": "MODEL_CONFIGURATION_INVALID"},
        }},
        {"properties": {
            "mode": {"const": "openai-compatible"}, "fixture_enabled": {"const": False},
            "can_submit": {"const": True}, "config_id": {"type": "string", "pattern": "^openai-[a-f0-9]{48}$"},
            "runtime_manifest": {"type": "object", "properties": {"provider": {"const": "corpus-openai-compatible"}}},
            "reason": {"type": "null"},
        }},
    ]}}
    production_ready: Literal[False]
    mode: Literal["unconfigured", "fixture", "openai-compatible"]
    fixture_enabled: bool
    can_submit: bool
    config_id: ConfigID | None
    reason: Literal["MODEL_NOT_CONFIGURED", "MODEL_CONFIGURATION_INVALID"] | None
    runtime_manifest: RuntimeManifest | None

    @model_validator(mode="after")
    def consistent_runtime(self):
        if self.mode == "unconfigured":
            valid = (not self.fixture_enabled and not self.can_submit
                     and self.config_id is None and self.runtime_manifest is None
                     and self.reason == "MODEL_NOT_CONFIGURED")
        elif self.mode == "fixture":
            valid = (self.fixture_enabled and self.can_submit
                     and self.config_id == "local-fixture-v1" and self.reason is None
                     and isinstance(self.runtime_manifest, FixtureManifest))
        elif self.reason == "MODEL_CONFIGURATION_INVALID":
            valid = (not self.fixture_enabled and not self.can_submit
                     and self.config_id is None and self.runtime_manifest is None)
        else:
            valid = (not self.fixture_enabled and self.can_submit and self.reason is None
                     and isinstance(self.runtime_manifest, OpenAIManifest)
                     and self.config_id == "openai-" + self.runtime_manifest.model_config_sha256[:48])
        if not valid:
            raise ValueError("Runtime mode, configuration and submission state disagree")
        return self


class SessionView(StrictView):
    session_id: UUID
    scope: AgentScope
    scope_digest: Digest
    config_id: ConfigID
    active_run_id: UUID | None
    latest_checkpoint_id: UUID | None
    lease_epoch: int = Field(ge=0)
    created_at: datetime


class SessionList(StrictView):
    items: list[SessionView]
    next_before: UUID | None


class WaitingJob(StrictView):
    invocation_id: UUID
    job_id: UUID
    kind: Literal["job", "sync", "index", "research"]
    report_tool: str
    report_arguments: dict[str, Any]
    state: str


class RunView(StrictView):
    run_id: UUID
    session_id: UUID
    state: AgentState
    reason: str | None
    scope_digest: Digest
    config_id: ConfigID
    lease_epoch: int = Field(ge=0)
    lease_expires_at: datetime | None
    event_sequence: int = Field(ge=0)
    allowed_tools: list[str]
    base_checkpoint_id: UUID | None
    final_checkpoint_id: UUID | None
    resume_checkpoint_id: UUID | None
    waiting_jobs: list[WaitingJob]
    active_deadline_at: datetime | None
    wait_deadline_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RunList(StrictView):
    items: list[RunView]
    next_before: UUID | None


class ResultView(StrictView):
    kind: Literal["project", "material", "snapshot", "query", "evidence", "note", "export", "job"]
    resource_id: str = Field(min_length=1, max_length=200)


class ToolMessage(StrictView):
    invocation_id: UUID
    tool_name: str
    status: str
    result_view: ResultView | None


class AssistantMessage(StrictView):
    id: str = Field(min_length=1)
    text: str


class MessageTurn(StrictView):
    run_id: UUID
    user_message: str
    assistant_messages: list[AssistantMessage]
    tools: list[ToolMessage]
    state: AgentState
    created_at: datetime


class MessageList(StrictView):
    items: list[MessageTurn]
    next_before: UUID | None


class AgentEvent(StrictView):
    event_id: UUID
    sequence: int = Field(ge=1)
    kind: str
    payload: dict[str, Any]
    created_at: datetime


class EventList(StrictView):
    items: list[AgentEvent]
    next_after: int = Field(ge=0)


def build_agent(save):
    for name, model in [
        ("runtime", RuntimeView), ("session-create", SessionInput),
        ("session", SessionView), ("session-list", SessionList),
        ("run-create", RunInput), ("run", RunView), ("run-list", RunList),
        ("messages", MessageList), ("events", EventList),
    ]:
        save(f"k09-agent-{name}", model.model_json_schema())
