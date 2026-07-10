from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text, Uuid, func
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

    # Output (serialized KitResult) and failure detail.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
