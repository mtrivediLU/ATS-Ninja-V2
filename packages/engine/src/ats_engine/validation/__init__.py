"""Validation gates: treat LLM output as untrusted until it passes these checks.

Truth-grounding (claims), structural correctness (latex), output shape
(output_format), completeness (no silently dropped source facts), style, and the
deterministic style repair used to avoid blocking the candidate's own wording.
``severity`` decides which failures must block delivery versus warn.
"""

from __future__ import annotations

from ats_engine.validation.calibration import (
    CalibrationKey,
    CalibrationProfile,
    apply_calibration,
    calibrate_identity,
    suppression_audit,
)
from ats_engine.validation.claims import validate_claims
from ats_engine.validation.completeness import resume_completeness_errors, validate_completeness
from ats_engine.validation.latex import validate_latex
from ats_engine.validation.output_format import (
    validate_cover_letter_word_count,
    validate_output_format,
)
from ats_engine.validation.repair import soften_banned_style
from ats_engine.validation.severity import (
    CAL_FALSE_POSITIVE,
    ValidationFinding,
    ValidationSeverity,
    is_fatal_validation_error,
    partition_validation_errors,
)
from ats_engine.validation.style import assert_style, validate_style

# NOTE: ``naturalness`` is intentionally NOT imported here. It imports
# ``scoring.ats`` (→ match_report → job_fit → kit), so importing it at
# validation-package init time forms an import cycle. Callers that need the
# authoritative naturalness gate import it directly from
# ``ats_engine.validation.naturalness``.

__all__ = [
    "assert_style",
    "apply_calibration",
    "CAL_FALSE_POSITIVE",
    "CalibrationKey",
    "CalibrationProfile",
    "calibrate_identity",
    "is_fatal_validation_error",
    "partition_validation_errors",
    "resume_completeness_errors",
    "soften_banned_style",
    "suppression_audit",
    "validate_claims",
    "validate_completeness",
    "validate_cover_letter_word_count",
    "validate_latex",
    "validate_output_format",
    "validate_style",
    "ValidationFinding",
    "ValidationSeverity",
]
