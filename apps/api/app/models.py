from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.schemas import KitStatus

"""ORM models (the persistence shape of the kit lifecycle).

Column types are chosen to be portable across PostgreSQL (production) and
SQLite (tests): ``Uuid`` and the generic ``JSON`` type map to native types on
Postgres and to portable equivalents on SQLite, so the same models and
migration run in both.
"""


class Kit(Base):
    """An application kit: the inputs, lifecycle status, and generated result."""

    __tablename__ = "kits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), default=KitStatus.PENDING, nullable=False, index=True)

    # Inputs (candidate evidence + targeting). No separate candidate identity is stored.
    resume_text: Mapped[str] = mapped_column(Text, nullable=False)
    job_description: Mapped[str] = mapped_column(Text, nullable=False)
    requested_mode: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    questions_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    include_resume: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    include_cover_letter: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    include_application_answers: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    include_job_fit: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    include_interview_prep: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    include_linkedin_outreach: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    outreach_context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Output (serialized KitResult) and failure detail.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # v5 lineage + revision. ``revision`` is the authoritative optimistic-
    # concurrency counter for change actions (0 at creation, +1 per applied
    # batch). ``parent_kit_id`` links a regenerated kit to the kit it was
    # regenerated from; the source kit is never overwritten.
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    parent_kit_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
