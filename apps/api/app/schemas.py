from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from ats_engine import normalize_persisted_result
from pydantic import BaseModel, ConfigDict, Field, field_validator

"""API request/response schemas for the kit lifecycle.

These are the transport contracts. They are deliberately separate from the ORM
model (`app.models.Kit`) and from the engine's domain models — the API owns its
wire format and never leaks database or engine internals directly.

The completed-kit result mirrors the engine's versioned ApplicationKit contract
(Phase 2A). A persisted result is normalized through the engine's serialization
boundary before validation, so a completed kit written under the older Phase 1
schema is adapted rather than crashing the response (see ADR-0012).
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


class EvidenceRefResponse(BaseModel):
    """A bounded pointer to the evidence supporting a claim."""

    source: str = ""
    locator: str = ""
    excerpt: str = ""


class ClaimResponse(BaseModel):
    """One candidate-specific claim and its truth-grounding disposition."""

    id: str = ""
    artifact: str = ""
    claim_type: str = ""
    text: str = ""
    status: str = ""
    disposition: str = ""
    reason: str = ""
    evidence: list[EvidenceRefResponse] = Field(default_factory=list)


class ArtifactValidationResponse(BaseModel):
    """Per-artifact validation outcome."""

    status: str = "generated"
    fatal: bool = False
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    repaired_claims: int = 0
    rejected_claims: int = 0


class ResumeArtifactResponse(BaseModel):
    """The tailored resume artifact and its truth-grounding trace."""

    text: str = ""
    latex: str = ""
    validation: ArtifactValidationResponse = Field(default_factory=ArtifactValidationResponse)
    claims: list[ClaimResponse] = Field(default_factory=list)
    interview_probability: int | None = None


class CoverLetterArtifactResponse(BaseModel):
    """The tailored cover-letter artifact and its truth-grounding trace."""

    text: str = ""
    latex: str = ""
    validation: ArtifactValidationResponse = Field(default_factory=ArtifactValidationResponse)
    claims: list[ClaimResponse] = Field(default_factory=list)


class AnswerItemResponse(BaseModel):
    """One application question and its grounded answer."""

    question: str = ""
    answer: str = ""


class AnswerArtifactResponse(BaseModel):
    """Application answers as structured items plus paste-ready text."""

    items: list[AnswerItemResponse] = Field(default_factory=list)
    text: str = ""
    validation: ArtifactValidationResponse = Field(default_factory=ArtifactValidationResponse)
    claims: list[ClaimResponse] = Field(default_factory=list)
    placeholders: list[str] = Field(default_factory=list)


class GenerationMetadataResponse(BaseModel):
    """Provider-neutral, persistence-safe generation metadata."""

    generation_mode: str = "deterministic"
    llm_available: bool = False
    provider: str = ""
    model: str = ""
    provider_calls: int = 0
    fallback_used: bool = False


class ValidationSummaryResponse(BaseModel):
    """Kit-wide validation roll-up. ``fatal`` means an artifact was withheld."""

    passed: bool = True
    fatal: bool = False
    error_count: int = 0
    warning_count: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ApplicationKitResponse(BaseModel):
    """The versioned, truth-grounded application kit as returned by the API."""

    schema_version: str
    engine_version: str = ""
    orchestration_version: str = ""
    requested_mode: str = ""
    resolved_mode: str = ""
    generation: GenerationMetadataResponse = Field(default_factory=GenerationMetadataResponse)
    validation: ValidationSummaryResponse = Field(default_factory=ValidationSummaryResponse)
    resume: ResumeArtifactResponse | None = None
    cover_letter: CoverLetterArtifactResponse | None = None
    answers: AnswerArtifactResponse | None = None
    warnings: list[str] = Field(default_factory=list)


class KitRead(BaseModel):
    """Full kit representation, including the result once completed."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: KitStatus
    requested_mode: str
    result: ApplicationKitResponse | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("result", mode="before")
    @classmethod
    def _normalize_result(cls, value: Any) -> Any:
        """Normalize a persisted result (v1 or legacy Phase 1) before validation.

        Reading a stored kit must never crash on an older result shape; the
        engine's boundary adapts legacy records into the canonical response.
        """
        if value is None or isinstance(value, (ApplicationKitResponse, dict)):
            return normalize_persisted_result(value) if isinstance(value, dict) else value
        return value


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
