"""The versioned ApplicationKit contract and grounded generation orchestration.

Public surface for Phase 2A. Callers (the API service, the worker, tests) should
import from here rather than from private submodules.

- :func:`generate_application_kit` — the single orchestration entry point.
- :class:`ApplicationKit` and its artifact/claim/validation models — the typed,
  versioned, JSON-serializable contract.
- :func:`application_kit_to_dict` / :func:`normalize_persisted_result` — the
  serialization boundary (including Phase 1 legacy compatibility).
"""

from __future__ import annotations

from ats_engine.kit.contract import (
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
    CoverLetterArtifact,
    EvidenceRef,
    GenerationMetadata,
    ResumeArtifact,
    ValidationSummary,
)
from ats_engine.kit.orchestrator import generate_application_kit
from ats_engine.kit.serialization import (
    LEGACY_SCHEMA_VERSION,
    application_kit_from_dict,
    application_kit_to_dict,
    is_application_kit_v1,
    normalize_persisted_result,
)

__all__ = [
    "ORCHESTRATION_VERSION",
    "SCHEMA_VERSION",
    "LEGACY_SCHEMA_VERSION",
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
    "ResumeArtifact",
    "ValidationSummary",
    "generate_application_kit",
    "application_kit_from_dict",
    "application_kit_to_dict",
    "is_application_kit_v1",
    "normalize_persisted_result",
]
