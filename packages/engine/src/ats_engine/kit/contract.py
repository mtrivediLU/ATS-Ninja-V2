from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

"""The versioned ApplicationKit contract.

This module is the engine's *public, persistable* representation of a generated
application kit. It is deliberately:

- **Versioned.** ``SCHEMA_VERSION`` is an explicit, human-readable string
  (currently ``application-kit/v4``) so a stored kit always declares which contract it was
  written under. A bare integer with ambiguous meaning is intentionally avoided.
- **Truthful by construction.** Every candidate-specific claim the AI produced is
  represented as a :class:`ClaimRecord` with an explicit :class:`ClaimStatus` and
  evidence references, so the question *"why was ATS-Ninja allowed to say this
  about the candidate?"* always has a structured answer.
- **JSON-compatible.** These are plain dataclasses of primitives, enums, and
  nested dataclasses — no engine-internal implementation objects, no pickled
  state (see :mod:`ats_engine.kit.serialization`).

Scope note (Phase 2B3): the modelled artifacts are a tailored resume, cover
letter, application answers, an optional grounded job-fit assessment, and an
optional grounded interview-preparation artifact, plus optional grounded
LinkedIn outreach drafts. Draft generation never sends messages or accesses an
external platform.
"""

# Explicit, self-describing contract identifiers. Bump these when the shape or
# meaning of the persisted contract changes; the value is stored on every kit.
APPLICATION_KIT_V1 = "application-kit/v1"
APPLICATION_KIT_V2 = "application-kit/v2"
APPLICATION_KIT_V3 = "application-kit/v3"
SCHEMA_VERSION = "application-kit/v4"

# The orchestration contract version identifies the grounded-generation behavior
# (claim extraction + repair/rejection policy). It participates in cache identity
# (see ADR-0013) so a change in grounding behavior never reuses prose produced by
# an older contract.
ORCHESTRATION_VERSION = "grounded-orchestration/v4"

# Bound every evidence excerpt so the trace never becomes a second copy of the
# candidate's resume (privacy: see ADR-0008).
EVIDENCE_EXCERPT_MAX_CHARS = 160
CLAIM_TEXT_MAX_CHARS = 200


class ArtifactKind(StrEnum):
    """Which generated artifact a record belongs to."""

    RESUME = "resume"
    COVER_LETTER = "cover_letter"
    ANSWERS = "answers"
    JOB_FIT = "job_fit"
    INTERVIEW_PREP = "interview_prep"
    LINKEDIN_OUTREACH = "linkedin_outreach"


class OutreachAudience(StrEnum):
    """Recipient class explicitly selected or supplied by the user."""

    RECRUITER = "recruiter"
    HIRING_MANAGER = "hiring_manager"
    EMPLOYEE = "employee"
    TEAMMATE = "teammate"
    ALUMNI = "alumni"
    PROFESSIONAL_CONTACT = "professional_contact"


class OutreachIntent(StrEnum):
    """User-requested purpose for an outreach draft."""

    CONNECT = "connect"
    DIRECT_MESSAGE = "direct_message"
    FOLLOW_UP = "follow_up"
    INFORMATIONAL = "informational"
    REFERRAL_REQUEST = "referral_request"
    SHARED_AFFILIATION = "shared_affiliation"


class OutreachFormat(StrEnum):
    """Product format whose centrally configured length policy applies."""

    CONNECTION_NOTE = "connection_note"
    DIRECT_MESSAGE = "direct_message"
    FOLLOW_UP = "follow_up"
    REFERRAL_REQUEST = "referral_request"


class OutreachContextKind(StrEnum):
    """Privilege boundary for a fact used in outreach."""

    CANDIDATE_EVIDENCE = "candidate_evidence"
    TARGET_JOB = "target_job"
    RECIPIENT = "recipient"
    RELATIONSHIP = "relationship"


class InterviewQuestionCategory(StrEnum):
    """Deterministic category for a question to prepare for."""

    MOTIVATION = "motivation"
    BEHAVIORAL = "behavioral"
    TECHNICAL = "technical"
    ROLE_SPECIFIC = "role_specific"
    STAKEHOLDER = "stakeholder"
    PROBLEM_SOLVING = "problem_solving"
    GAP_CLARIFICATION = "gap_clarification"


class InterviewPriority(StrEnum):
    """Rule-derived preparation priority; never a probability."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class StarCompleteness(StrEnum):
    """Whether every material STAR field has direct source evidence."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class StarSourceType(StrEnum):
    """Source context that a STAR candidate must remain within."""

    PROFESSIONAL = "professional"
    EDUCATION = "education"


class FitBand(StrEnum):
    """Deterministic fit band derived from requirement coverage policy."""

    LOW = "low"
    PARTIAL = "partial"
    COMPETITIVE = "competitive"
    STRONG = "strong"


class RequirementClassification(StrEnum):
    """Truth-grounded disposition of a JD requirement."""

    PROVEN = "proven"
    ADJACENT = "adjacent"
    WORKING_KNOWLEDGE = "working_knowledge"
    GENUINE_GAP = "genuine_gap"


class RequirementRisk(StrEnum):
    """Candidate-facing risk attached to a requirement assessment."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    MUST_HAVE_GAP = "must_have_gap"


class ClaimType(StrEnum):
    """The category of a candidate-specific claim extracted from generated prose.

    These are the fabrication-sensitive fact categories. Each has a distinct
    grounding rule (see :mod:`ats_engine.kit.grounding`).
    """

    EMPLOYER = "employer"
    TITLE = "title"
    SKILL = "skill"
    METRIC = "metric"
    MONETARY = "monetary"
    TEAM_SIZE = "team_size"
    MANAGEMENT = "management"
    TENURE = "tenure"
    CERTIFICATION = "certification"
    EDUCATION = "education"


class ClaimStatus(StrEnum):
    """Disposition of a single claim after grounding.

    - ``supported``: the claim traces to the candidate's own evidence and is kept.
    - ``repaired``: the claim was unsupported and was deterministically removed
      from the artifact (the fabricated text is absent from the final output).
    - ``rejected``: the claim was unsupported and could not be safely removed, so
      the artifact is withheld and the kit is marked fatally invalid.
    """

    SUPPORTED = "supported"
    REPAIRED = "repaired"
    REJECTED = "rejected"


class ArtifactStatus(StrEnum):
    """Delivery state of a single artifact."""

    GENERATED = "generated"  # produced with no truth-grounding intervention
    REPAIRED = "repaired"  # produced, but one or more claims were removed
    REJECTED = "rejected"  # withheld: an unsupported claim could not be removed
    ABSENT = "absent"  # not requested for this kit


@dataclass(slots=True)
class EvidenceRef:
    """A bounded, privacy-conscious pointer to the evidence supporting a claim.

    ``excerpt`` is a short snippet (never the whole resume) and is truncated to
    :data:`EVIDENCE_EXCERPT_MAX_CHARS`. ``locator`` is a stable identifier of
    where the support came from (e.g. ``"supported_metric"``, ``"experience"``).
    """

    source: str
    locator: str
    excerpt: str = ""


@dataclass(slots=True)
class ClaimRecord:
    """One candidate-specific claim and its grounding disposition."""

    id: str
    artifact: ArtifactKind
    claim_type: ClaimType
    text: str
    status: ClaimStatus
    disposition: str
    reason: str = ""
    evidence: list[EvidenceRef] = field(default_factory=list)


@dataclass(slots=True)
class ArtifactValidation:
    """Per-artifact validation outcome."""

    status: ArtifactStatus
    fatal: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    repaired_claims: int = 0
    rejected_claims: int = 0


@dataclass(slots=True)
class ResumeSkillGroup:
    label: str
    items: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ResumeExperienceEntry:
    employer: str = ""
    title: str = ""
    location: str = ""
    date_range: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ResumeEducationEntry:
    institution: str = ""
    degree: str = ""
    location: str = ""
    date_range: str = ""
    details: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ResumeCertificationEntry:
    name: str
    date: str = ""
    link: str = ""


@dataclass(slots=True)
class ResumeDocument:
    """Optional presentation data assembled only from the grounded resume plan."""

    candidate_name: str = ""
    professional_headline: str = ""
    contact_lines: list[str] = field(default_factory=list)
    summary: str = ""
    skill_groups: list[ResumeSkillGroup] = field(default_factory=list)
    experience: list[ResumeExperienceEntry] = field(default_factory=list)
    education: list[ResumeEducationEntry] = field(default_factory=list)
    certifications: list[ResumeCertificationEntry] = field(default_factory=list)
    remaining_sections: list[tuple[str, list[str]]] = field(default_factory=list)


@dataclass(slots=True)
class CoverLetterDocument:
    """Optional grounded cover-letter presentation data; blank fields are omitted."""

    sender_name: str = ""
    sender_contact_lines: list[str] = field(default_factory=list)
    date: str = ""
    recipient_name: str = ""
    recipient_title: str = ""
    recipient_company: str = ""
    recipient_address: list[str] = field(default_factory=list)
    target_role: str = ""
    greeting: str = ""
    body_paragraphs: list[str] = field(default_factory=list)
    closing: str = ""
    signature_name: str = ""


@dataclass(slots=True)
class ResumeArtifact:
    """The tailored resume artifact and its truth-grounding trace."""

    text: str
    latex: str
    validation: ArtifactValidation
    claims: list[ClaimRecord] = field(default_factory=list)
    interview_probability: int | None = None
    document: ResumeDocument | None = None


@dataclass(slots=True)
class CoverLetterArtifact:
    """The tailored cover-letter artifact and its truth-grounding trace."""

    text: str
    latex: str
    validation: ArtifactValidation
    claims: list[ClaimRecord] = field(default_factory=list)
    document: CoverLetterDocument | None = None


@dataclass(slots=True)
class AnswerItem:
    """One application/screening question and its grounded answer."""

    question: str
    answer: str


@dataclass(slots=True)
class AnswerArtifact:
    """Application answers as structured items plus paste-ready text.

    Modelled on the engine's real behavior: a flat list of (question, answer)
    pairs. No invented questionnaire structure is imposed.
    """

    items: list[AnswerItem]
    text: str
    validation: ArtifactValidation
    claims: list[ClaimRecord] = field(default_factory=list)
    placeholders: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RequirementAssessment:
    """Authoritative deterministic assessment of one relevant JD requirement."""

    id: str
    requirement: str
    importance: str
    must_have: bool
    classification: RequirementClassification
    explanation: str
    risk: RequirementRisk
    permitted_positioning: str
    evidence: list[EvidenceRef] = field(default_factory=list)


@dataclass(slots=True)
class PositioningRecommendation:
    """Honest language a candidate may use for a requirement."""

    requirement_id: str
    text: str


@dataclass(slots=True)
class ConsistencyValidation:
    """Job-fit narrative consistency outcome after deterministic enforcement."""

    passed: bool
    errors: list[str] = field(default_factory=list)
    repaired_violations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class JobFitArtifact:
    """Structured, truth-grounded job-fit analysis.

    ``requirement_coverage_score`` is a reproducible policy index, not an
    interview probability or model confidence. ``ats_keyword_score`` is the
    engine's existing literal keyword-match score and is supplemental.
    """

    summary: str
    requirement_coverage_score: float
    fit_band: FitBand
    ats_keyword_score: float
    interview_probability: int | None
    requirements: list[RequirementAssessment]
    strongest_matches: list[str]
    adjacent_capabilities: list[str]
    working_knowledge: list[str]
    genuine_gaps: list[str]
    must_have_gaps: list[str]
    positioning_recommendations: list[PositioningRecommendation]
    validation: ArtifactValidation
    consistency: ConsistencyValidation
    generation: GenerationMetadata
    claims: list[ClaimRecord] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    withheld: bool = False


@dataclass(slots=True)
class InterviewFocusArea:
    """One requirement-derived topic the candidate should prepare."""

    requirement_id: str
    topic: str
    classification: RequirementClassification
    priority: InterviewPriority
    guidance: str
    evidence: list[EvidenceRef] = field(default_factory=list)


@dataclass(slots=True)
class InterviewAnswerGuide:
    """Grounded outline for answering one likely interview question."""

    key_points: list[str]
    statements_to_avoid: list[str]
    suggested_answer: str
    honest_gap_language: str = ""
    evidence: list[EvidenceRef] = field(default_factory=list)


@dataclass(slots=True)
class InterviewQuestion:
    """A deterministic question-to-prepare contract."""

    id: str
    category: InterviewQuestionCategory
    question: str
    rationale: str
    related_requirement_ids: list[str]
    priority: InterviewPriority
    answer_guide: InterviewAnswerGuide
    evidence: list[EvidenceRef] = field(default_factory=list)
    gap_relevance: str = ""
    validation: ArtifactValidation = field(default_factory=lambda: ArtifactValidation(status=ArtifactStatus.GENERATED))


@dataclass(slots=True)
class StarStoryCandidate:
    """One single-context, evidence-bounded STAR outline."""

    id: str
    source_type: StarSourceType
    employer_or_institution: str
    title_or_degree: str
    situation: str
    task: str
    action: str
    result: str
    completeness: StarCompleteness
    missing_components: list[str]
    safe_usage_guidance: str
    evidence: list[EvidenceRef] = field(default_factory=list)
    validation: ArtifactValidation = field(default_factory=lambda: ArtifactValidation(status=ArtifactStatus.GENERATED))


@dataclass(slots=True)
class TechnicalStudyTopic:
    """A JD topic to study, explicitly not a candidate-experience claim."""

    requirement_id: str
    topic: str
    reason: str
    boundary: str
    priority: InterviewPriority


@dataclass(slots=True)
class GapHandlingGuide:
    """Honest guidance for discussing a genuine or bounded capability gap."""

    requirement_id: str
    requirement: str
    classification: RequirementClassification
    must_have: bool
    guidance: str
    what_to_avoid: list[str]
    evidence: list[EvidenceRef] = field(default_factory=list)


@dataclass(slots=True)
class InterviewerQuestion:
    """A neutral question based only on the supplied JD or missing role detail."""

    id: str
    question: str
    rationale: str
    source: str


@dataclass(slots=True)
class InterviewPrepArtifact:
    """Structured, truth-grounded interview preparation."""

    strategy_summary: str
    focus_areas: list[InterviewFocusArea]
    questions: list[InterviewQuestion]
    star_stories: list[StarStoryCandidate]
    technical_study_topics: list[TechnicalStudyTopic]
    gap_handling: list[GapHandlingGuide]
    positioning_recommendations: list[PositioningRecommendation]
    interviewer_questions: list[InterviewerQuestion]
    validation: ArtifactValidation
    consistency: ConsistencyValidation
    generation: GenerationMetadata
    claims: list[ClaimRecord] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    withheld: bool = False


@dataclass(slots=True)
class OutreachContext:
    """Optional, user-supplied personalization facts.

    None of these values are candidate evidence. Relationship and action fields
    authorize only the exact relationship/action they describe.
    """

    recipient_name: str = ""
    recipient_title: str = ""
    recipient_company: str = ""
    audience: OutreachAudience | None = None
    requested_intent: OutreachIntent | None = None
    has_applied: bool | None = None
    application_date: str = ""
    application_status: str = ""
    referral_contact_name: str = ""
    shared_affiliation: str = ""
    mutual_connection: str = ""
    prior_meeting: str = ""
    prior_conversation: str = ""
    personalization_note: str = ""
    portfolio_url: str = ""


@dataclass(slots=True)
class OutreachContextRef:
    """Bounded trace to a target, recipient, or relationship input."""

    kind: OutreachContextKind
    field: str
    excerpt: str


@dataclass(slots=True)
class OutreachDraft:
    """One concise LinkedIn outreach draft; never a sent-message record."""

    id: str
    audience: OutreachAudience
    intent: OutreachIntent
    format: OutreachFormat
    text: str
    character_count: int
    character_limit: int
    target_company: str
    target_role: str
    personalization_fields: list[str]
    call_to_action: str
    evidence: list[EvidenceRef] = field(default_factory=list)
    target_context: list[OutreachContextRef] = field(default_factory=list)
    relationship_context: list[OutreachContextRef] = field(default_factory=list)
    validation: ArtifactValidation = field(default_factory=lambda: ArtifactValidation(status=ArtifactStatus.GENERATED))


@dataclass(slots=True)
class RelationshipValidation:
    """Grounding result for recipient, relationship, and user-action claims."""

    passed: bool
    errors: list[str] = field(default_factory=list)
    repaired_violations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LinkedInOutreachArtifact:
    """Structured, truth-grounded LinkedIn draft collection."""

    strategy_summary: str
    drafts: list[OutreachDraft]
    validation: ArtifactValidation
    consistency: ConsistencyValidation
    relationship_validation: RelationshipValidation
    generation: GenerationMetadata
    claims: list[ClaimRecord] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    target_context: list[OutreachContextRef] = field(default_factory=list)
    relationship_context: list[OutreachContextRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    withheld: bool = False


@dataclass(slots=True)
class ValidationSummary:
    """Kit-wide validation roll-up.

    ``fatal`` is true when any truth-critical issue could not be repaired away
    (an artifact was rejected/withheld). ``passed`` is true when there were no
    fatal issues.
    """

    passed: bool
    fatal: bool
    error_count: int = 0
    warning_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GenerationMetadata:
    """Provider-neutral, persistence-safe generation metadata.

    Only values the implementation can accurately produce are included. Token
    counts, cost, and latency are deliberately omitted because the current
    providers cannot report them accurately. No provider key or secret is ever
    stored here.
    """

    generation_mode: str  # "deterministic" | "provider"
    llm_available: bool
    provider: str = ""  # normalized provider identity (e.g. "ollama:llama3.2"); "" when deterministic
    model: str = ""
    provider_calls: int = 0
    fallback_used: bool = False


@dataclass(slots=True)
class ApplicationKit:
    """The complete, versioned, truth-grounded application kit."""

    schema_version: str
    engine_version: str
    orchestration_version: str
    requested_mode: str
    resolved_mode: str
    generation: GenerationMetadata
    validation: ValidationSummary
    resume: ResumeArtifact | None = None
    cover_letter: CoverLetterArtifact | None = None
    answers: AnswerArtifact | None = None
    job_fit: JobFitArtifact | None = None
    interview_prep: InterviewPrepArtifact | None = None
    linkedin_outreach: LinkedInOutreachArtifact | None = None
    warnings: list[str] = field(default_factory=list)

    def all_claims(self) -> list[ClaimRecord]:
        """Every claim record across all artifacts (the full grounding trace)."""
        claims: list[ClaimRecord] = []
        for artifact in (
            self.resume,
            self.cover_letter,
            self.answers,
            self.job_fit,
            self.interview_prep,
            self.linkedin_outreach,
        ):
            if artifact is not None:
                claims.extend(artifact.claims)
        return claims
