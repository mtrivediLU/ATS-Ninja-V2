from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

"""The versioned ApplicationKit contract (Phase 2A).

This module is the engine's *public, persistable* representation of a generated
application kit. It is deliberately:

- **Versioned.** ``SCHEMA_VERSION`` is an explicit, human-readable string
  (``application-kit/v1``) so a stored kit always declares which contract it was
  written under. A bare integer with ambiguous meaning is intentionally avoided.
- **Truthful by construction.** Every candidate-specific claim the AI produced is
  represented as a :class:`ClaimRecord` with an explicit :class:`ClaimStatus` and
  evidence references, so the question *"why was ATS-Ninja allowed to say this
  about the candidate?"* always has a structured answer.
- **JSON-compatible.** These are plain dataclasses of primitives, enums, and
  nested dataclasses — no engine-internal implementation objects, no pickled
  state (see :mod:`ats_engine.kit.serialization`).

Scope note (Phase 2A): the modelled artifacts are exactly what the real engine
generates today — a tailored resume, a tailored cover letter, and application
answers. Job-fit analysis, interview preparation, and LinkedIn outreach are
Phase 2B and are intentionally NOT modelled here.
"""

# Explicit, self-describing contract identifiers. Bump these when the shape or
# meaning of the persisted contract changes; the value is stored on every kit.
SCHEMA_VERSION = "application-kit/v1"

# The orchestration contract version identifies the grounded-generation behavior
# (claim extraction + repair/rejection policy). It participates in cache identity
# (see ADR-0013) so a change in grounding behavior never reuses prose produced by
# an older contract.
ORCHESTRATION_VERSION = "grounded-orchestration/v1"

# Bound every evidence excerpt so the trace never becomes a second copy of the
# candidate's resume (privacy: see ADR-0008).
EVIDENCE_EXCERPT_MAX_CHARS = 160
CLAIM_TEXT_MAX_CHARS = 200


class ArtifactKind(StrEnum):
    """Which real Phase 2A artifact a record belongs to."""

    RESUME = "resume"
    COVER_LETTER = "cover_letter"
    ANSWERS = "answers"


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
class ResumeArtifact:
    """The tailored resume artifact and its truth-grounding trace."""

    text: str
    latex: str
    validation: ArtifactValidation
    claims: list[ClaimRecord] = field(default_factory=list)
    interview_probability: int | None = None


@dataclass(slots=True)
class CoverLetterArtifact:
    """The tailored cover-letter artifact and its truth-grounding trace."""

    text: str
    latex: str
    validation: ArtifactValidation
    claims: list[ClaimRecord] = field(default_factory=list)


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
    warnings: list[str] = field(default_factory=list)

    def all_claims(self) -> list[ClaimRecord]:
        """Every claim record across all artifacts (the full grounding trace)."""
        claims: list[ClaimRecord] = []
        for artifact in (self.resume, self.cover_letter, self.answers):
            if artifact is not None:
                claims.extend(artifact.claims)
        return claims
