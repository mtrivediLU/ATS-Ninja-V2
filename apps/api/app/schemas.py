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


class OutreachAudienceInput(StrEnum):
    RECRUITER = "recruiter"
    HIRING_MANAGER = "hiring_manager"
    EMPLOYEE = "employee"
    TEAMMATE = "teammate"
    ALUMNI = "alumni"
    PROFESSIONAL_CONTACT = "professional_contact"


class OutreachIntentInput(StrEnum):
    CONNECT = "connect"
    DIRECT_MESSAGE = "direct_message"
    FOLLOW_UP = "follow_up"
    INFORMATIONAL = "informational"
    REFERRAL_REQUEST = "referral_request"
    SHARED_AFFILIATION = "shared_affiliation"


class OutreachContextInput(BaseModel):
    """Optional explicit personalization; never candidate evidence."""

    model_config = ConfigDict(extra="forbid")

    recipient_name: str = Field(default="", max_length=100)
    recipient_title: str = Field(default="", max_length=120)
    recipient_company: str = Field(default="", max_length=120)
    audience: OutreachAudienceInput | None = None
    requested_intent: OutreachIntentInput | None = None
    has_applied: bool | None = None
    application_date: str = Field(default="", max_length=40)
    application_status: str = Field(default="", max_length=80)
    referral_contact_name: str = Field(default="", max_length=100)
    shared_affiliation: str = Field(default="", max_length=140)
    mutual_connection: str = Field(default="", max_length=100)
    prior_meeting: str = Field(default="", max_length=160)
    prior_conversation: str = Field(default="", max_length=160)
    personalization_note: str = Field(default="", max_length=300)
    portfolio_url: str = Field(default="", max_length=300, pattern=r"^$|^https?://[^\s<>]+$")


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
    include_resume: bool | None = Field(
        default=None,
        description="Explicitly include or omit the tailored resume; omitted preserves requested_mode behavior.",
    )
    include_cover_letter: bool | None = Field(
        default=None,
        description="Explicitly include or omit the cover letter; omitted preserves requested_mode behavior.",
    )
    include_application_answers: bool | None = Field(
        default=None,
        description="Explicitly include or omit application answers; omitted preserves requested_mode behavior.",
    )
    include_job_fit: bool = Field(
        default=True,
        description="Generate the grounded JobFitArtifact (enabled by default).",
    )
    include_interview_prep: bool = Field(
        default=True,
        description="Generate the grounded InterviewPrepArtifact (enabled by default).",
    )
    include_linkedin_outreach: bool = Field(
        default=True,
        description="Generate grounded LinkedIn outreach drafts (enabled by default).",
    )
    outreach_context: OutreachContextInput | None = Field(
        default=None,
        description="Optional recipient, relationship, and application facts supplied by the user.",
    )


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


class RequirementAssessmentResponse(BaseModel):
    id: str = ""
    requirement: str = ""
    importance: str = ""
    must_have: bool = False
    classification: str = "genuine_gap"
    explanation: str = ""
    risk: str = "high"
    permitted_positioning: str = ""
    evidence: list[EvidenceRefResponse] = Field(default_factory=list)


class PositioningRecommendationResponse(BaseModel):
    requirement_id: str = ""
    text: str = ""


class ConsistencyValidationResponse(BaseModel):
    passed: bool = True
    errors: list[str] = Field(default_factory=list)
    repaired_violations: list[str] = Field(default_factory=list)


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


class JobFitArtifactResponse(BaseModel):
    """Structured, deterministic-authoritative job-fit assessment."""

    summary: str = ""
    requirement_coverage_score: float = 0.0
    fit_band: str = "low"
    ats_keyword_score: float = 0.0
    interview_probability: int | None = None
    requirements: list[RequirementAssessmentResponse] = Field(default_factory=list)
    strongest_matches: list[str] = Field(default_factory=list)
    adjacent_capabilities: list[str] = Field(default_factory=list)
    working_knowledge: list[str] = Field(default_factory=list)
    genuine_gaps: list[str] = Field(default_factory=list)
    must_have_gaps: list[str] = Field(default_factory=list)
    positioning_recommendations: list[PositioningRecommendationResponse] = Field(default_factory=list)
    validation: ArtifactValidationResponse = Field(default_factory=ArtifactValidationResponse)
    consistency: ConsistencyValidationResponse = Field(default_factory=ConsistencyValidationResponse)
    generation: GenerationMetadataResponse = Field(default_factory=GenerationMetadataResponse)
    claims: list[ClaimResponse] = Field(default_factory=list)
    evidence: list[EvidenceRefResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    withheld: bool = False


class InterviewFocusAreaResponse(BaseModel):
    requirement_id: str = ""
    topic: str = ""
    classification: str = "genuine_gap"
    priority: str = "medium"
    guidance: str = ""
    evidence: list[EvidenceRefResponse] = Field(default_factory=list)


class InterviewAnswerGuideResponse(BaseModel):
    key_points: list[str] = Field(default_factory=list)
    statements_to_avoid: list[str] = Field(default_factory=list)
    suggested_answer: str = ""
    honest_gap_language: str = ""
    evidence: list[EvidenceRefResponse] = Field(default_factory=list)


class InterviewQuestionResponse(BaseModel):
    id: str = ""
    category: str = "role_specific"
    question: str = ""
    rationale: str = ""
    related_requirement_ids: list[str] = Field(default_factory=list)
    priority: str = "medium"
    answer_guide: InterviewAnswerGuideResponse = Field(default_factory=InterviewAnswerGuideResponse)
    evidence: list[EvidenceRefResponse] = Field(default_factory=list)
    gap_relevance: str = ""
    validation: ArtifactValidationResponse = Field(default_factory=ArtifactValidationResponse)


class StarStoryResponse(BaseModel):
    id: str = ""
    source_type: str = "professional"
    employer_or_institution: str = ""
    title_or_degree: str = ""
    situation: str = ""
    task: str = ""
    action: str = ""
    result: str = ""
    completeness: str = "incomplete"
    missing_components: list[str] = Field(default_factory=list)
    safe_usage_guidance: str = ""
    evidence: list[EvidenceRefResponse] = Field(default_factory=list)
    validation: ArtifactValidationResponse = Field(default_factory=ArtifactValidationResponse)


class TechnicalStudyTopicResponse(BaseModel):
    requirement_id: str = ""
    topic: str = ""
    reason: str = ""
    boundary: str = ""
    priority: str = "medium"


class GapHandlingGuideResponse(BaseModel):
    requirement_id: str = ""
    requirement: str = ""
    classification: str = "genuine_gap"
    must_have: bool = False
    guidance: str = ""
    what_to_avoid: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRefResponse] = Field(default_factory=list)


class InterviewerQuestionResponse(BaseModel):
    id: str = ""
    question: str = ""
    rationale: str = ""
    source: str = ""


class InterviewPrepArtifactResponse(BaseModel):
    """Structured, deterministic-authoritative interview preparation."""

    strategy_summary: str = ""
    focus_areas: list[InterviewFocusAreaResponse] = Field(default_factory=list)
    questions: list[InterviewQuestionResponse] = Field(default_factory=list)
    star_stories: list[StarStoryResponse] = Field(default_factory=list)
    technical_study_topics: list[TechnicalStudyTopicResponse] = Field(default_factory=list)
    gap_handling: list[GapHandlingGuideResponse] = Field(default_factory=list)
    positioning_recommendations: list[PositioningRecommendationResponse] = Field(default_factory=list)
    interviewer_questions: list[InterviewerQuestionResponse] = Field(default_factory=list)
    validation: ArtifactValidationResponse = Field(default_factory=ArtifactValidationResponse)
    consistency: ConsistencyValidationResponse = Field(default_factory=ConsistencyValidationResponse)
    generation: GenerationMetadataResponse = Field(default_factory=GenerationMetadataResponse)
    claims: list[ClaimResponse] = Field(default_factory=list)
    evidence: list[EvidenceRefResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    withheld: bool = False


class OutreachContextRefResponse(BaseModel):
    kind: str = "target_job"
    field: str = ""
    excerpt: str = ""


class OutreachDraftResponse(BaseModel):
    id: str = ""
    audience: str = "recruiter"
    intent: str = "connect"
    format: str = "connection_note"
    text: str = ""
    character_count: int = 0
    character_limit: int = 0
    target_company: str = ""
    target_role: str = ""
    personalization_fields: list[str] = Field(default_factory=list)
    call_to_action: str = ""
    evidence: list[EvidenceRefResponse] = Field(default_factory=list)
    target_context: list[OutreachContextRefResponse] = Field(default_factory=list)
    relationship_context: list[OutreachContextRefResponse] = Field(default_factory=list)
    validation: ArtifactValidationResponse = Field(default_factory=ArtifactValidationResponse)


class RelationshipValidationResponse(BaseModel):
    passed: bool = False
    errors: list[str] = Field(default_factory=list)
    repaired_violations: list[str] = Field(default_factory=list)


class LinkedInOutreachArtifactResponse(BaseModel):
    """Structured drafts only; no sending or external-platform state."""

    strategy_summary: str = ""
    drafts: list[OutreachDraftResponse] = Field(default_factory=list)
    validation: ArtifactValidationResponse = Field(default_factory=ArtifactValidationResponse)
    consistency: ConsistencyValidationResponse = Field(default_factory=ConsistencyValidationResponse)
    relationship_validation: RelationshipValidationResponse = Field(default_factory=RelationshipValidationResponse)
    generation: GenerationMetadataResponse = Field(default_factory=GenerationMetadataResponse)
    claims: list[ClaimResponse] = Field(default_factory=list)
    evidence: list[EvidenceRefResponse] = Field(default_factory=list)
    target_context: list[OutreachContextRefResponse] = Field(default_factory=list)
    relationship_context: list[OutreachContextRefResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    withheld: bool = False


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
    job_fit: JobFitArtifactResponse | None = None
    interview_prep: InterviewPrepArtifactResponse | None = None
    linkedin_outreach: LinkedInOutreachArtifactResponse | None = None
    warnings: list[str] = Field(default_factory=list)


class KitRead(BaseModel):
    """Full kit representation, including the result once completed."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: KitStatus
    requested_mode: str
    include_resume: bool = True
    include_cover_letter: bool = False
    include_application_answers: bool = False
    include_job_fit: bool = True
    include_interview_prep: bool = True
    include_linkedin_outreach: bool = True
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
