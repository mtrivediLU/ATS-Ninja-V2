from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

"""Typed domain models for the ATS-Ninja engine.

These dataclasses are the shared vocabulary of the whole engine: parsing
produces them, matching/scoring/gap analysis reason over them, generation
consumes them, and validation checks generated output against them. They are
deliberately free of any web-framework, LLM-SDK, or persistence concern.
"""


class Mode(StrEnum):
    """Generation modes supported by the pipeline."""

    RESUME = "R"
    COVER_LETTER = "C"
    RESUME_AND_COVER = "RC"
    QUESTIONS = "Q"
    RESUME_AND_QUESTIONS = "RQ"


@dataclass(frozen=True, slots=True)
class ArtifactSelection:
    """Independent primary-artifact selection resolved from API intent.

    The legacy :class:`Mode` values remain supported, while this model lets new
    callers request resume, cover letter, and application answers in any
    combination without inventing more ambiguous mode strings.
    """

    resume: bool
    cover_letter: bool
    application_answers: bool

    @property
    def code(self) -> str:
        """Return a stable compact representation for result metadata."""
        return "".join(
            token
            for enabled, token in (
                (self.resume, "R"),
                (self.cover_letter, "C"),
                (self.application_answers, "Q"),
            )
            if enabled
        )


@dataclass(slots=True)
class ContactInfo:
    name: str = ""
    phone: str = ""
    email: str = ""
    linkedin: str = ""
    website: str = ""
    location: str = ""
    availability: str = ""
    work_mode: str = ""
    work_authorization: str = ""
    sponsorship: str = ""
    relocation: str = ""
    source: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Experience:
    company: str
    title: str
    location: str
    dates: str
    bullets: list[str]


@dataclass(slots=True)
class Education:
    institution: str
    location: str
    degree: str
    dates: str
    bullets: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Certification:
    name: str
    date: str = ""
    link: str = ""


@dataclass(slots=True)
class Profile:
    """The candidate's source of truth, derived strictly from their own resume.

    Skills are tiered by the strength of their evidence in the resume:
    ``tier_a`` (proven in experience bullets), ``tier_b`` (stated in the
    summary), and ``tier_c`` (listed only, i.e. working knowledge). Nothing in
    a Profile is ever fabricated or defaulted to a hardcoded identity.
    """

    contact: ContactInfo
    retired_emails: list[str]
    role_identities: list[str]
    tier_a: dict[str, str]
    tier_b: dict[str, str]
    tier_c: dict[str, str]
    adjacency: dict[str, str]
    experiences: list[Experience]
    education: list[Education]
    certifications: list[Certification]
    supported_metrics: list[str]
    raw_markdown: str = ""

    @property
    def official_titles(self) -> dict[str, str]:
        return {experience.company.lower(): experience.title for experience in self.experiences}

    @property
    def allowed_companies(self) -> set[str]:
        return {experience.company for experience in self.experiences}


@dataclass(slots=True)
class ParsedInput:
    resume_text: str
    job_description: str
    contacts: ContactInfo
    questions: list[str]
    logistics: dict[str, str]
    mode: Mode


@dataclass(slots=True)
class JDProfile:
    title: str = "Target Role"
    company: str = "Target Company"
    work_mode: str = "unknown"
    location: str = ""
    required_qualifications: list[str] = field(default_factory=list)
    preferred_qualifications: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    technical_keywords: list[str] = field(default_factory=list)
    domain: str = ""
    ats_platform: str = "unknown"


@dataclass(slots=True)
class EvidenceItem:
    """One JD keyword mapped to the candidate's real evidence and its gap tier.

    ``evidence_tier`` is the gap ladder rung: ``A`` proven, ``B`` medium,
    ``adjacency`` honest same-category substitute, ``C`` working knowledge,
    ``missing`` genuine gap. ``allowed_placement`` encodes where the claim may
    truthfully appear so downstream generation cannot over-claim.
    """

    keyword: str
    required_or_preferred: str
    evidence_tier: str
    real_evidence: str
    allowed_placement: str
    strength: str
    planned_placement: str


@dataclass(slots=True)
class ResumePlan:
    contacts: ContactInfo
    jd_profile: JDProfile
    evidence: list[EvidenceItem]
    role_identity: str
    headline: str
    work_mode_line: str
    summary: str
    skill_groups: list[tuple[str, list[str]]]
    experience: list[Experience]
    education: list[Education]
    certifications: list[Certification]
    working_knowledge: list[str]
    residual_gap: str
    interview_probability: int
    analysis: list[str]


@dataclass(slots=True)
class CoverLetterPlan:
    contacts: ContactInfo
    jd_profile: JDProfile
    angle: str
    body_paragraphs: list[str]
    word_count: int
    needs_fast_ramp: bool


@dataclass(slots=True)
class AnswerPlan:
    questions: list[str]
    answers: list[str]
    placeholders: list[str]


@dataclass(slots=True)
class PipelineResult:
    parsed_input: ParsedInput
    jd_profile: JDProfile
    resume_plan: ResumePlan | None = None
    cover_letter_plan: CoverLetterPlan | None = None
    answer_plan: AnswerPlan | None = None
    resume_latex: str = ""
    cover_letter_latex: str = ""
    answers_text: str = ""
    resume_text: str = ""
    cover_letter_text: str = ""
    mode_outputs: dict[str, str] = field(default_factory=dict)
    validation_errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
