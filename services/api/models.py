"""S1 account/project persistence; material and job models live separately."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from services.api.db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    is_platform_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.users.id", ondelete="CASCADE"), index=True
    )
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("id", "owner_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "owner_id"],
            ["app.projects.id", "app.projects.owner_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("role IN ('owner','editor','viewer')", name="member_role"),
        CheckConstraint(
            "(role = 'owner') = (user_id = owner_id)", name="owner_role_identity"
        ),
    )
    project_id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    role: Mapped[str] = mapped_column(String(10))
