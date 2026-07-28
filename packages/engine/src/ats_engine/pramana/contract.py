"""The PRAMANA score contract.

Dataclasses only -- no scoring logic lives here. See ``pramana/scoring.py``
for the algorithm that produces a ``PramanaScore``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ats_engine.models import RequirementTerm


@dataclass(frozen=True, slots=True)
class RequirementCredit:
    """One requirement's measured target, supply, and resulting credit.

    ``target`` and ``supply`` are the raw counts before saturation; ``credit``
    is the final, saturating 0..1 value actually used in the weighted score.
    Keeping the raw counts on the record (rather than only the credit) is what
    lets a caller show *why* a term did or didn't earn full credit.
    """

    requirement: RequirementTerm
    target: int
    supply: int
    tier: str
    credit: float


@dataclass(frozen=True, slots=True)
class PramanaScore:
    """The PRAMANA result: a 0-100 score with its components and an explanation.

    ``score`` is the only number most callers need; everything else exists so
    a caller can show *why* -- which requirement earned how much credit, which
    gaps are genuinely unreachable versus merely undeclared, and which bonus
    or penalty moved the score and by how much.
    """

    score: float
    keyword_score: float
    title_alignment: float
    placement_bonus: float
    stuffing_penalty: float
    confidence: str  # "high" | "medium" | "low"
    required_coverage: float
    preferred_coverage: float
    per_requirement: list[RequirementCredit] = field(default_factory=list)
    # Tier "missing": no evidence at all, and not helped by wording. Distinct
    # from a requirement simply scoring low -- these are flagged separately so
    # the product can say "these need real experience, not better wording."
    unreachable_gaps: list[str] = field(default_factory=list)
    # Tier "declared": the candidate confirmed this through the not-yet-built
    # declared-evidence questionnaire (KATA/RACHANA §3.9). Always empty today
    # -- no resolver path produces this tier yet -- kept so the field exists
    # ahead of that work landing rather than being added as a breaking change.
    declared_gaps: list[str] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)
