"""Project-private immutable parsed documents and revisions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from services.api.db import Base


class Material(Base):
    __tablename__ = "material_documents"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column()
    upload_id: Mapped[UUID] = mapped_column()
    name: Mapped[str] = mapped_column(String(255))
    latest_revision_id: Mapped[UUID | None] = mapped_column()
    import_id: Mapped[UUID] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MaterialRevision(Base):
    __tablename__ = "material_revisions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column()
    material_id: Mapped[UUID] = mapped_column()
    upload_id: Mapped[UUID] = mapped_column()
    import_id: Mapped[UUID] = mapped_column()
    revision: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(3))
    manifest: Mapped[dict] = mapped_column(JSONB)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    objects: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
