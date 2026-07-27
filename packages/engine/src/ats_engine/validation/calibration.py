"""Exact, identity-only calibration for structured validation findings.

A reviewed false positive may downgrade exactly one detector result. It is not
a fuzzy suppression list: detector version, original code, normalized fact,
and source span must all match.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace

from ats_engine.validation.findings import (
    CAL_FALSE_POSITIVE,
    DEFAULT_DETECTOR_VERSION,
    ValidationFinding,
    ValidationSeverity,
    canonicalize_fact,
)

FIDELITY_DETECTOR_VERSION = DEFAULT_DETECTOR_VERSION


@dataclass(frozen=True, slots=True)
class CalibrationKey:
    """Exact reviewed-false-positive identity; never a broad suppression rule."""

    detector_version: str
    code: str
    normalized_fact: str
    source_span: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "normalized_fact", canonicalize_fact(self.normalized_fact))

    @classmethod
    def from_finding(cls, finding: ValidationFinding) -> CalibrationKey:
        """Build a key using the original detector code and exact source span."""
        return cls(
            detector_version=finding.detector_version,
            code=finding.detector_code,
            normalized_fact=finding.normalized_fact,
            source_span=finding.source_span,
        )


# ``CalibrationEntry`` reads naturally in persisted-review code while keeping
# one concrete exact-key type for equality and serialization.
CalibrationEntry = CalibrationKey


@dataclass(frozen=True, slots=True)
class CalibrationProfile:
    """An immutable set of exact false-positive review decisions."""

    entries: frozenset[CalibrationKey] = field(default_factory=frozenset)

    @classmethod
    def from_entries(cls, entries: Iterable[CalibrationKey]) -> CalibrationProfile:
        """Construct a deterministic profile from persisted review entries."""
        return cls(entries=frozenset(entries))

    def contains(self, finding: ValidationFinding) -> bool:
        """Return whether this profile exactly calibrates the finding identity."""
        return CalibrationKey.from_finding(finding) in self.entries


def calibration_key_for(finding: ValidationFinding) -> CalibrationKey:
    """Compatibility helper for callers that prefer a function over a property."""
    return CalibrationKey.from_finding(finding)


def calibrate_identity(findings: Iterable[ValidationFinding]) -> CalibrationProfile:
    """Create exact calibration entries from an unchanged-source projection.

    Callers should pass only detector findings observed while rendering the
    candidate's source identity projection. Each resulting entry includes the
    detector version, original code, normalized fact, and source span; there is
    no text-only or code-only wildcard path.
    """
    return CalibrationProfile.from_entries(CalibrationKey.from_finding(finding) for finding in findings)


def suppression_audit(calibrations: Iterable[CalibrationKey] | CalibrationProfile) -> tuple[str, ...]:
    """Return the sorted unique original detector codes eligible for suppression.

    This is deliberately code-only reporting, not matching logic. Actual
    calibration remains the exact four-field identity check in
    :func:`apply_calibration`.
    """
    entries = calibrations.entries if isinstance(calibrations, CalibrationProfile) else frozenset(calibrations)
    return tuple(sorted({entry.code for entry in entries}))


def suppressed_codes(calibrations: Iterable[CalibrationKey] | CalibrationProfile) -> tuple[str, ...]:
    """Compatibility alias for :func:`suppression_audit`."""
    return suppression_audit(calibrations)


def apply_calibration(
    findings: Iterable[ValidationFinding],
    calibrations: Iterable[CalibrationKey] | CalibrationProfile,
    *,
    fact_is_present: Callable[[str], bool] | None = None,
) -> tuple[ValidationFinding, ...]:
    """Apply exact calibrations by changing only code/severity classification.

    A match becomes ``code='CAL_FALSE_POSITIVE'`` and ``severity='warn'``. The
    original detector code is retained in ``original_code`` for audit and for
    stable repeated application. Fact, source span, detail, and detector version
    are copied unchanged, so one calibration cannot hide an unrelated deletion.
    """
    calibration_keys = calibrations.entries if isinstance(calibrations, CalibrationProfile) else frozenset(calibrations)
    output: list[ValidationFinding] = []
    for finding in findings:
        exact_match = CalibrationKey.from_finding(finding) in calibration_keys
        # Fidelity calibration is fail-closed: an exact reviewed identity may
        # be downgraded only while the protected fact is still present in the
        # current candidate. Otherwise a later genuine deletion produces the
        # same detector tuple as the identity false positive and would be
        # incorrectly suppressed. Stuffing findings use a separate detector
        # version and encode current/source repetition magnitudes in the fact,
        # so their exact-key calibration does not use this presence guard.
        presence_confirmed = finding.detector_version != FIDELITY_DETECTOR_VERSION or (
            fact_is_present is not None and fact_is_present(finding.fact)
        )
        if exact_match and presence_confirmed:
            output.append(
                replace(
                    finding,
                    code=CAL_FALSE_POSITIVE,
                    severity=ValidationSeverity.WARN,
                    original_code=finding.detector_code,
                )
            )
        else:
            output.append(finding)
    return tuple(output)


def apply_calibrations(
    findings: Iterable[ValidationFinding],
    calibrations: Iterable[CalibrationKey] | CalibrationProfile,
    *,
    fact_is_present: Callable[[str], bool] | None = None,
) -> tuple[ValidationFinding, ...]:
    """Plural alias for :func:`apply_calibration`."""
    return apply_calibration(findings, calibrations, fact_is_present=fact_is_present)


__all__ = [
    "CAL_FALSE_POSITIVE",
    "CalibrationEntry",
    "CalibrationKey",
    "CalibrationProfile",
    "FIDELITY_DETECTOR_VERSION",
    "apply_calibration",
    "apply_calibrations",
    "calibrate_identity",
    "calibration_key_for",
    "suppressed_codes",
    "suppression_audit",
]
