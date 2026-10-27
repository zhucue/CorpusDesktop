"""Durable host control records; model transcripts and raw credentials are absent."""

from uuid import uuid4

from sqlalchemy import BigInteger, DateTime, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column

from services.api.db import Base


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    id = mapped_column(Uuid, primary_key=True, default=uuid4)
    actor_id = mapped_column(Uuid, nullable=False)
    scope = mapped_column(JSONB, nullable=False)
    scope_digest = mapped_column(String(64), nullable=False)
    config_id = mapped_column(String(60), nullable=False, default="local-fixture-v1")
    active_run_id = mapped_column(Uuid)
    latest_checkpoint_id = mapped_column(Uuid)
    lease_epoch = mapped_column(Integer, nullable=False, default=0)
    created_at = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id = mapped_column(Uuid, nullable=False)
    actor_id = mapped_column(Uuid, nullable=False)
    request_key = mapped_column(Uuid, nullable=False)
    config_id = mapped_column(String(60), nullable=False, default="local-fixture-v1")
    user_message = mapped_column(String(8000), nullable=False, default="")
    request_digest = mapped_column(String(64), nullable=False, default="")
    scope_digest = mapped_column(String(64), nullable=False)
    state = mapped_column(String(30), nullable=False)
    reason = mapped_column(String(80))
    allowed_tools = mapped_column(JSONB, nullable=False)
    lease_epoch = mapped_column(Integer, nullable=False, default=0)
    lease_expires_at = mapped_column(DateTime(timezone=True))
    host_id = mapped_column(Uuid)
    base_checkpoint_id = mapped_column(Uuid)
    final_checkpoint_id = mapped_column(Uuid)
    resume_checkpoint_id = mapped_column(Uuid)
    active_deadline_at = mapped_column(DateTime(timezone=True))
    wait_deadline_at = mapped_column(DateTime(timezone=True))
    waiting_jobs = mapped_column(JSONB, nullable=False, default=list)
    event_sequence = mapped_column(BigInteger, nullable=False, default=0)
    created_at = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), nullable=False)


class AgentCredential(Base):
    __tablename__ = "agent_credentials"
    token_hash = mapped_column(String(64), primary_key=True)
    run_id = mapped_column(Uuid, nullable=False)
    actor_id = mapped_column(Uuid, nullable=False)
    session_id = mapped_column(Uuid, nullable=False)
    scope_digest = mapped_column(String(64), nullable=False)
    lease_epoch = mapped_column(Integer, nullable=False)
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)


class AgentInvocation(Base):
    __tablename__ = "agent_invocations"
    id = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id = mapped_column(Uuid, nullable=False)
    actor_id = mapped_column(Uuid, nullable=False)
    request_key = mapped_column(Uuid, nullable=False)
    tool_call_id = mapped_column(String(160), nullable=False)
    tool_name = mapped_column(String(80), nullable=False)
    arguments_digest = mapped_column(String(64), nullable=False)
    action_id = mapped_column(Uuid)
    response = mapped_column(JSONB, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False)


class AgentEvent(Base):
    __tablename__ = "agent_events"
    id = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id = mapped_column(Uuid, nullable=False)
    actor_id = mapped_column(Uuid, nullable=False)
    sequence = mapped_column(BigInteger, nullable=False)
    kind = mapped_column(String(60), nullable=False)
    payload = mapped_column(JSONB, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False)


class AgentCheckpoint(Base):
    __tablename__ = "agent_checkpoints"
    id = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id = mapped_column(Uuid, nullable=False)
    run_id = mapped_column(Uuid, nullable=False)
    actor_id = mapped_column(Uuid, nullable=False)
    request_key = mapped_column(Uuid, nullable=False)
    base_checkpoint_id = mapped_column(Uuid)
    lease_epoch = mapped_column(Integer, nullable=False)
    event_sequence = mapped_column(BigInteger, nullable=False)
    object_key = mapped_column(String(255), nullable=False)
    version_id = mapped_column(String(255), nullable=False)
    etag = mapped_column(String(255), nullable=False)
    sha256 = mapped_column(String(64), nullable=False)
    byte_size = mapped_column(BigInteger, nullable=False)
    sdk_session_id = mapped_column(Uuid, nullable=False)
    leaf_id = mapped_column(String(160), nullable=False)
    runtime_manifest = mapped_column(JSONB, nullable=False)
    dependencies = mapped_column(JSONB, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False)
