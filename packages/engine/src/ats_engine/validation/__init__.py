"""Validation gates: treat LLM output as untrusted until it passes these checks.

Truth-grounding (claims), structural correctness (latex), output shape
(output_format), completeness (no silently dropped source facts), style, and the
deterministic style repair used to avoid blocking the candidate's own wording.
``severity`` decides which failures must block delivery versus warn.
"""

from __future__ import annotations

from ats_engine.validation.claims import validate_claims
from ats_engine.validation.completeness import validate_completeness
from ats_engine.validation.latex import validate_latex
from ats_engine.validation.output_format import (
    validate_cover_letter_word_count,
    validate_output_format,
)
from ats_engine.validation.repair import soften_banned_style
from ats_engine.validation.severity import (
    is_fatal_validation_error,
    partition_validation_errors,
)
from ats_engine.validation.style import assert_style, validate_style

__all__ = [
    "assert_style",
    "is_fatal_validation_error",
    "partition_validation_errors",
    "soften_banned_style",
    "validate_claims",
    "validate_completeness",
    "validate_cover_letter_word_count",
    "validate_latex",
    "validate_output_format",
    "validate_style",
]
