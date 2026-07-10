from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

"""API request/response schemas for the kit lifecycle.

These are the transport contracts. They are deliberately separate from the ORM
model (`app.models.Kit`) and from the engine's domain models — the API owns its
wire format and never leaks database or engine internals directly.
"""


class KitStatus(StrEnum):
    """Lifecycle state of an application kit."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class KitCreate(BaseModel):
    """Input to create a kit generation job.

    Phase 1 accepts already-extracted resume text (the engine also has a PDF
    path; wiring multipart upload is a later concern). No candidate identity is
    required or stored beyond what the resume text itself contains.
    """

    resume_text: str = Field(min_length=1, description="Candidate resume as plain text.")
    job_description: str = Field(min_length=1, description="Target job description as plain text.")
    requested_mode: str = Field(default="", description="Optional generation intent, e.g. 'resume and cover letter'.")
    questions_text: str = Field(default="", description="Optional application/screening questions.")


class KitResult(BaseModel):
    """The generated artifacts and truth-grounding signals for a completed kit."""

    resume_text: str = ""
    cover_letter_text: str = ""
    answers_text: str = ""
    resume_latex: str = ""
    cover_letter_latex: str = ""
    interview_probability: int | None = None
    # Empty ``validation_errors`` means every truth-grounding gate passed.
    validation_errors: list[str] = Field(default_factory=list)
    # Subset of validation_errors that are truth-critical/structural (would block delivery).
    fatal_validation_errors: list[str] = Field(default_factory=list)
    engine_metadata: dict[str, Any] = Field(default_factory=dict)


class KitRead(BaseModel):
    """Full kit representation, including the result once completed."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: KitStatus
    requested_mode: str
    result: KitResult | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class KitSummary(BaseModel):
    """Lightweight kit representation for list responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: KitStatus
    created_at: datetime
    updated_at: datetime


class KitList(BaseModel):
    items: list[KitSummary]
    total: int
    limit: int
    offset: int
