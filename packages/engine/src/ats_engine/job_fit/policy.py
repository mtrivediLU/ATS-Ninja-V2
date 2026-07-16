from __future__ import annotations

from ats_engine.kit.contract import FitBand
from ats_engine.models import EvidenceItem

"""Central deterministic fit policy.

The coverage score is a transparent requirement-weighted index, not a
probability. Required items have twice the weight of preferred items. Evidence
rungs retain their existing meaning and receive fixed coverage credit:
A=100, B=80, adjacency=55, C=35, missing=0. The result is reproducible from the
existing evidence matrix alone.
"""

FIT_BAND_THRESHOLDS: tuple[tuple[float, FitBand], ...] = (
    (85.0, FitBand.STRONG),
    (70.0, FitBand.COMPETITIVE),
    (50.0, FitBand.PARTIAL),
    (0.0, FitBand.LOW),
)

_TIER_CREDIT: dict[str, float] = {
    "A": 100.0,
    "B": 80.0,
    "adjacency": 55.0,
    "C": 35.0,
    "missing": 0.0,
}


def fit_band_for_score(score: float) -> FitBand:
    """Map a bounded deterministic coverage score to its documented band."""
    bounded = min(100.0, max(0.0, score))
    for threshold, band in FIT_BAND_THRESHOLDS:
        if bounded >= threshold:
            return band
    return FitBand.LOW


def requirement_coverage_score(evidence: list[EvidenceItem]) -> float:
    """Return the requirement-weighted evidence coverage index (0..100)."""
    if not evidence:
        return 0.0
    earned = 0.0
    possible = 0.0
    for item in evidence:
        weight = 2.0 if item.required_or_preferred == "required" else 1.0
        earned += weight * _TIER_CREDIT.get(item.evidence_tier, 0.0)
        possible += weight * 100.0
    return round((earned / possible) * 100.0, 2) if possible else 0.0
