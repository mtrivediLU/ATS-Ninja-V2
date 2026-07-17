"""ATS-Ninja engine: deterministic-first, truth-grounded career intelligence.

This is the public surface of the engine. Callers (the API service, an async
worker, tests, notebooks) should import from here or from the documented
subpackages (``ats_engine.parsing``, ``.evidence``, ``.scoring``,
``.validation``, ``.generation``, ``.providers``) rather than reaching into
private modules.

Design contract (enforced by architecture, see AGENTS.md):
  * No web-framework or LLM-vendor SDK is imported by this package.
  * LLM output is untrusted until it passes the validation gates.
  * Candidate-specific claims must be backed by evidence from the resume.
"""

from __future__ import annotations

from ats_engine.config import EngineSettings
from ats_engine.evidence import (
    build_evidence_matrix,
    classify_keyword,
    interview_probability,
)
from ats_engine.generation import (
    build_resume_plan,
    resolve_artifact_selection,
    run_pipeline,
    validate_pipeline_result,
)
from ats_engine.kit import (
    APPLICATION_KIT_V1,
    APPLICATION_KIT_V2,
    APPLICATION_KIT_V3,
    ORCHESTRATION_VERSION,
    SCHEMA_VERSION,
    AnswerArtifact,
    AnswerItem,
    ApplicationKit,
    ArtifactKind,
    ArtifactStatus,
    ArtifactValidation,
    ClaimRecord,
    ClaimStatus,
    ClaimType,
    ConsistencyValidation,
    CoverLetterArtifact,
    EvidenceRef,
    FitBand,
    GapHandlingGuide,
    GenerationMetadata,
    InterviewAnswerGuide,
    InterviewerQuestion,
    InterviewFocusArea,
    InterviewPrepArtifact,
    InterviewPriority,
    InterviewQuestion,
    InterviewQuestionCategory,
    JobFitArtifact,
    LinkedInOutreachArtifact,
    OutreachAudience,
    OutreachContext,
    OutreachContextKind,
    OutreachContextRef,
    OutreachDraft,
    OutreachFormat,
    OutreachIntent,
    PositioningRecommendation,
    RelationshipValidation,
    RequirementAssessment,
    RequirementClassification,
    RequirementRisk,
    ResumeArtifact,
    StarCompleteness,
    StarSourceType,
    StarStoryCandidate,
    TechnicalStudyTopic,
    ValidationSummary,
    application_kit_from_dict,
    application_kit_to_dict,
    generate_application_kit,
    is_application_kit_v1,
    is_application_kit_v2,
    is_application_kit_v3,
    is_application_kit_v4,
    normalize_persisted_result,
)
from ats_engine.models import (
    AnswerPlan,
    ArtifactSelection,
    Certification,
    ContactInfo,
    CoverLetterPlan,
    Education,
    EvidenceItem,
    Experience,
    JDProfile,
    Mode,
    ParsedInput,
    PipelineResult,
    Profile,
    ResumePlan,
)
from ats_engine.parsing import (
    build_profile,
    extract_profile,
    extract_text_from_pdf,
    parse_input,
    parse_jd,
)
from ats_engine.providers import LLMProvider, OllamaProvider
from ats_engine.scoring import calculate_ats_score, compare_scores, extract_keywords
from ats_engine.validation import (
    is_fatal_validation_error,
    partition_validation_errors,
    validate_claims,
)

__version__ = "0.1.0"

__all__ = [
    # settings
    "EngineSettings",
    # models
    "AnswerPlan",
    "ArtifactSelection",
    "Certification",
    "ContactInfo",
    "CoverLetterPlan",
    "Education",
    "EvidenceItem",
    "Experience",
    "JDProfile",
    "Mode",
    "ParsedInput",
    "PipelineResult",
    "Profile",
    "ResumePlan",
    # parsing
    "build_profile",
    "extract_profile",
    "extract_text_from_pdf",
    "parse_input",
    "parse_jd",
    # evidence
    "build_evidence_matrix",
    "classify_keyword",
    "interview_probability",
    # scoring
    "calculate_ats_score",
    "compare_scores",
    "extract_keywords",
    # validation
    "is_fatal_validation_error",
    "partition_validation_errors",
    "validate_claims",
    # generation
    "build_resume_plan",
    "resolve_artifact_selection",
    "run_pipeline",
    "validate_pipeline_result",
    # kit contract + orchestration (Phase 2A)
    "ORCHESTRATION_VERSION",
    "APPLICATION_KIT_V1",
    "APPLICATION_KIT_V2",
    "APPLICATION_KIT_V3",
    "SCHEMA_VERSION",
    "AnswerArtifact",
    "AnswerItem",
    "ApplicationKit",
    "ArtifactKind",
    "ArtifactStatus",
    "ArtifactValidation",
    "ClaimRecord",
    "ClaimStatus",
    "ClaimType",
    "CoverLetterArtifact",
    "EvidenceRef",
    "GenerationMetadata",
    "GapHandlingGuide",
    "InterviewAnswerGuide",
    "InterviewFocusArea",
    "InterviewPrepArtifact",
    "InterviewPriority",
    "InterviewQuestion",
    "InterviewQuestionCategory",
    "InterviewerQuestion",
    "ConsistencyValidation",
    "FitBand",
    "JobFitArtifact",
    "LinkedInOutreachArtifact",
    "OutreachAudience",
    "OutreachContext",
    "OutreachContextKind",
    "OutreachContextRef",
    "OutreachDraft",
    "OutreachFormat",
    "OutreachIntent",
    "PositioningRecommendation",
    "RequirementAssessment",
    "RequirementClassification",
    "RequirementRisk",
    "RelationshipValidation",
    "ResumeArtifact",
    "StarCompleteness",
    "StarSourceType",
    "StarStoryCandidate",
    "TechnicalStudyTopic",
    "ValidationSummary",
    "application_kit_from_dict",
    "application_kit_to_dict",
    "generate_application_kit",
    "is_application_kit_v1",
    "is_application_kit_v2",
    "is_application_kit_v3",
    "is_application_kit_v4",
    "normalize_persisted_result",
    # providers
    "LLMProvider",
    "OllamaProvider",
    "__version__",
]
