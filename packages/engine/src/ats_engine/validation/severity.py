from __future__ import annotations

"""Validation-error severity classification.

Whether a validation error should *block* delivery or merely be surfaced as a
warning is a product truth-policy decision, not a UI concern, so it lives in the
engine (the legacy code kept this inside the presentation layer). Structural or
truth-critical failures — invented employers/metrics/emails, altered titles,
dropped source content, broken LaTeX — mean the output cannot be trusted or
compiled and must block. Everything else (residual wording, word counts) is a
warning shown alongside otherwise-usable output.
"""

FATAL_MARKERS: tuple[str, ...] = (
    "completeness:",
    "invented or unsupported employer",
    "unsupported metric",
    "email not present in resume",
    "retired email used",
    "official title altered",
    "missing \\end{document}",
    "unbalanced braces",
)


def is_fatal_validation_error(error: str) -> bool:
    """True when a validation error is truth-critical or structural and must block."""
    return any(marker in error for marker in FATAL_MARKERS)


def partition_validation_errors(errors: list[str]) -> tuple[list[str], list[str]]:
    """Split validation errors into ``(fatal, warnings)`` preserving order."""
    fatal = [error for error in errors if is_fatal_validation_error(error)]
    warnings = [error for error in errors if not is_fatal_validation_error(error)]
    return fatal, warnings
