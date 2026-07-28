"""Shared typed validation findings and their canonical fact identity."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

DEFAULT_DETECTOR_VERSION = "fidelity-v3"
CAL_FALSE_POSITIVE = "CAL_FALSE_POSITIVE"


class ValidationSeverity(StrEnum):
    """Delivery effect for one deterministic validation finding."""

    FATAL = "fatal"
    DEGRADE = "degrade"
    WARN = "warn"


_LATEX_ESCAPES: tuple[tuple[str, str], ...] = (
    (r"\&", "&"),
    (r"\%", "%"),
    (r"\$", "$"),
    (r"\#", "#"),
    (r"\_", "_"),
    (r"\textendash", "-"),
    (r"\textemdash", "-"),
)
_DASH_TRANSLATION = str.maketrans({"–": "-", "—": "-", "−": "-"})


def canonicalize_fact(value: str) -> str:
    """Return the single comparison form for facts and calibration keys.

    The same normalizer is applied to extracted facts, source lines, candidate
    lines, and calibration records. It preserves internal hyphens and technical
    punctuation while normalizing ordinary separators and typography.
    """
    normalized = (value or "").translate(_DASH_TRANSLATION)
    normalized = re.sub(r"([A-Za-z0-9])-\s*\n\s*([A-Za-z0-9])", r"\1-\2", normalized)
    for escaped, replacement in _LATEX_ESCAPES:
        normalized = normalized.replace(escaped, replacement)
    normalized = re.sub(r"\\(?:textbf|textit|emph|href|url)\{([^{}]*)\}", r"\1", normalized)
    normalized = normalized.replace("{", " ").replace("}", " ")
    # Sentence punctuation is not part of a fact identity, while ``.NET`` and
    # decimal/version dots remain because they are not terminal dots.
    normalized = re.sub(r"(?<=[A-Za-z0-9])\.(?=\s|$)", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized.casefold()).strip()
    # Slash is a source-boundary separator (``CI/CD``), not part of one fact;
    # internal hyphens remain significant for brands such as ``M-Files``.
    normalized = re.sub(r"[^a-z0-9+#.-]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    """A structured validator result with stable evidence identity.

    The first five fields are the required public contract. ``detector_version``
    and ``original_code`` are additive metadata for exact calibration; neither
    introduces a dependency on kit or API contracts.
    """

    code: str
    severity: ValidationSeverity
    fact: str
    source_span: str
    detail: str
    detector_version: str = DEFAULT_DETECTOR_VERSION
    original_code: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "severity", ValidationSeverity(self.severity))

    @property
    def normalized_fact(self) -> str:
        """Canonical fact identity used by exact calibration."""
        return canonicalize_fact(self.fact)

    @property
    def detector_code(self) -> str:
        """The originating detector code, retained after calibration."""
        return self.original_code or self.code

    def __str__(self) -> str:
        """Keep legacy string consumers on the existing human-readable detail."""
        return self.detail


__all__ = [
    "CAL_FALSE_POSITIVE",
    "DEFAULT_DETECTOR_VERSION",
    "ValidationFinding",
    "ValidationSeverity",
    "canonicalize_fact",
]
