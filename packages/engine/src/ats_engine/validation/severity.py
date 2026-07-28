"""Validation severity policy for structured and legacy validation results."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from ats_engine.validation.findings import CAL_FALSE_POSITIVE, ValidationFinding, ValidationSeverity

FIDELITY_MISSING_SOURCE_FACT = "FIDELITY_MISSING_SOURCE_FACT"
FIDELITY_UNSUPPORTED_METRIC = "FIDELITY_UNSUPPORTED_METRIC"
FIDELITY_UNSUPPORTED_CREDENTIAL_ID = "FIDELITY_UNSUPPORTED_CREDENTIAL_ID"
FIDELITY_MISSING_ORIGINAL_METRIC = "FIDELITY_MISSING_ORIGINAL_METRIC"
FIDELITY_MISSING_TEAM_FACT = "FIDELITY_MISSING_TEAM_FACT"
FIDELITY_MISSING_NAMED_ENTITY = "FIDELITY_MISSING_NAMED_ENTITY"
FIDELITY_MISSING_TECHNOLOGY = "FIDELITY_MISSING_TECHNOLOGY"
FIDELITY_MISSING_RESPONSIBILITY = "FIDELITY_MISSING_RESPONSIBILITY"
FIDELITY_UNSUPPORTED_NAMED_ENTITY = "FIDELITY_UNSUPPORTED_NAMED_ENTITY"
FIDELITY_TERMINAL_CLAUSE_LOST = "FIDELITY_TERMINAL_CLAUSE_LOST"
FIDELITY_RAW_BULLET_CONTENT_LOST = "FIDELITY_RAW_BULLET_CONTENT_LOST"

# Keep truth-critical codes explicit. Unknown future detector codes start as
# warnings instead of silently becoming delivery blockers before policy review.
SEVERITY_BY_CODE: dict[str, ValidationSeverity] = {
    FIDELITY_MISSING_SOURCE_FACT: ValidationSeverity.FATAL,
    FIDELITY_UNSUPPORTED_METRIC: ValidationSeverity.FATAL,
    FIDELITY_UNSUPPORTED_CREDENTIAL_ID: ValidationSeverity.FATAL,
    FIDELITY_MISSING_ORIGINAL_METRIC: ValidationSeverity.FATAL,
    FIDELITY_MISSING_TEAM_FACT: ValidationSeverity.FATAL,
    FIDELITY_MISSING_NAMED_ENTITY: ValidationSeverity.FATAL,
    FIDELITY_MISSING_TECHNOLOGY: ValidationSeverity.FATAL,
    FIDELITY_MISSING_RESPONSIBILITY: ValidationSeverity.FATAL,
    FIDELITY_UNSUPPORTED_NAMED_ENTITY: ValidationSeverity.FATAL,
    FIDELITY_TERMINAL_CLAUSE_LOST: ValidationSeverity.FATAL,
    FIDELITY_RAW_BULLET_CONTENT_LOST: ValidationSeverity.FATAL,
}

# Compatibility fallback for validators not yet migrated to structured codes.
# Do not include a blanket ``fidelity:`` marker: fidelity strings must map to a
# reviewed code below, otherwise they remain advisory instead of accidentally
# blocking delivery.
FATAL_MARKERS: tuple[str, ...] = (
    "completeness:",
    "invented or unsupported employer",
    "unsupported metric",
    "email not present in resume",
    "retired email used",
    "official title altered",
    "stuffing:",
    "extraction_suspect",
    "missing \\end{document}",
    "unbalanced braces",
)

_LEGACY_FIDELITY_CODE_MARKERS: tuple[tuple[str, str], ...] = (
    ("fidelity: missing source", FIDELITY_MISSING_SOURCE_FACT),
    ("fidelity: unsupported certification credential id", FIDELITY_UNSUPPORTED_CREDENTIAL_ID),
    ("fidelity: unsupported metric", FIDELITY_UNSUPPORTED_METRIC),
    ("fidelity: missing original metric", FIDELITY_MISSING_ORIGINAL_METRIC),
    ("fidelity: missing original team fact", FIDELITY_MISSING_TEAM_FACT),
    ("fidelity: missing original named entity", FIDELITY_MISSING_NAMED_ENTITY),
    ("fidelity: missing original technology or methodology", FIDELITY_MISSING_TECHNOLOGY),
    ("fidelity: missing original responsibility", FIDELITY_MISSING_RESPONSIBILITY),
    ("fidelity: unsupported named entity", FIDELITY_UNSUPPORTED_NAMED_ENTITY),
    ("fidelity: terminal clause facts not retained", FIDELITY_TERMINAL_CLAUSE_LOST),
    ("fidelity: raw source bullet content not retained", FIDELITY_RAW_BULLET_CONTENT_LOST),
)

_ValidationResult = TypeVar("_ValidationResult", str, ValidationFinding)


def severity_for_code(code: str) -> ValidationSeverity:
    """Return the reviewed policy severity for one structured detector code."""
    if code == CAL_FALSE_POSITIVE:
        return ValidationSeverity.WARN
    return SEVERITY_BY_CODE.get(code, ValidationSeverity.WARN)


def legacy_fidelity_code(error: str) -> str | None:
    """Map a legacy fidelity string to a reviewed structured code, if known."""
    lowered = error.casefold()
    for marker, code in _LEGACY_FIDELITY_CODE_MARKERS:
        if marker in lowered:
            return code
    return None


def is_fatal_validation_error(error: str | ValidationFinding) -> bool:
    """True when a validation result is truth-critical or structural.

    Structured calibrated findings use ``CAL_FALSE_POSITIVE`` plus ``warn`` and
    are never fatal. Legacy fidelity strings receive the same result only when
    their text maps to one of the reviewed detector codes.
    """
    if isinstance(error, ValidationFinding):
        return error.severity is ValidationSeverity.FATAL

    lowered = error.casefold()
    if "validation [warn:" in lowered or "validation [degrade:" in lowered:
        return False
    if "validation [fatal:" in lowered:
        return True

    fidelity_code = legacy_fidelity_code(error)
    if fidelity_code is not None:
        return severity_for_code(fidelity_code) is ValidationSeverity.FATAL

    # The older production-naturalness detector can observe a duplicate that
    # already exists in candidate-authored source bullets. It is deliberately
    # advisory: deleting that source evidence would violate the stronger
    # preservation invariant. The v2 ``validation.stuffing`` gate remains
    # blocking and is emitted without this naturalness prefix.
    if "naturalness: stuffing:" in lowered:
        return False
    return any(marker in lowered for marker in FATAL_MARKERS)


def partition_validation_errors(
    errors: Sequence[_ValidationResult],
) -> tuple[list[_ValidationResult], list[_ValidationResult]]:
    """Split validation results into ``(fatal, warnings)`` preserving order."""
    fatal = [error for error in errors if is_fatal_validation_error(error)]
    warnings = [error for error in errors if not is_fatal_validation_error(error)]
    return fatal, warnings


__all__ = [
    "CAL_FALSE_POSITIVE",
    "FIDELITY_MISSING_NAMED_ENTITY",
    "FIDELITY_MISSING_ORIGINAL_METRIC",
    "FIDELITY_MISSING_RESPONSIBILITY",
    "FIDELITY_MISSING_SOURCE_FACT",
    "FIDELITY_MISSING_TEAM_FACT",
    "FIDELITY_MISSING_TECHNOLOGY",
    "FIDELITY_RAW_BULLET_CONTENT_LOST",
    "FIDELITY_TERMINAL_CLAUSE_LOST",
    "FIDELITY_UNSUPPORTED_CREDENTIAL_ID",
    "FIDELITY_UNSUPPORTED_METRIC",
    "FIDELITY_UNSUPPORTED_NAMED_ENTITY",
    "FATAL_MARKERS",
    "SEVERITY_BY_CODE",
    "ValidationFinding",
    "ValidationSeverity",
    "is_fatal_validation_error",
    "legacy_fidelity_code",
    "partition_validation_errors",
    "severity_for_code",
]
