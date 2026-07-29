"""Compatibility shim over PRAMANA -- the authoritative scoring algorithm.

``AtsScoreV2``/``score_resume_v2`` used to contain the whole scoring formula.
The formula itself now lives in ``ats_engine.pramana.scoring`` (the fractional,
saturating, evidence-gated PRAMANA score); this module only projects its
richer ``PramanaScore`` result onto the older, stable ``AtsScoreV2`` shape so
every existing caller (the optimizer's accept/reject loop, job-fit scoring,
the match report, change-ledger recomputation) keeps working unchanged. There
is exactly one scoring implementation in this engine; this is a thin adapter
over it, not a second one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ats_engine.models import EvidenceLink, PlacementAction, RequirementTerm
from ats_engine.pramana.scoring import PramanaScore, score_resume


@dataclass(frozen=True, slots=True)
class AtsScoreV2:
    """The authoritative v2 ATS result before its stable contract projection."""

    score: float
    base_score: float
    density_penalty: float
    placement_bonus: float
    matched_keywords: list[str] = field(default_factory=list)
    missing_keywords: list[str] = field(default_factory=list)
    total_keywords: int = 0
    required_matched: int = 0
    required_total: int = 0
    preferred_matched: int = 0
    preferred_total: int = 0
    term_frequencies: dict[str, int] = field(default_factory=dict)


def score_resume_v2(
    resume_text: str,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
    *,
    source_resume_text: str = "",
    tailored: bool = False,
    placements: Iterable[PlacementAction] = (),
) -> AtsScoreV2:
    """Score a resume only for JD requirements with source-backed evidence.

    Delegates to PRAMANA (``pramana.scoring.score_resume``) and projects the
    result onto the stable ``AtsScoreV2`` shape. See that module for the
    formula and the provenance gate that prevents a trailing pasted JD from
    raising a tailored score.
    """
    result = score_resume(
        resume_text,
        requirements,
        links,
        source_resume_text=source_resume_text,
        tailored=tailored,
        placements=placements,
    )
    return _project(result)


def _project(result: PramanaScore) -> AtsScoreV2:
    matched: list[str] = []
    missing: list[str] = []
    required_matched = required_total = preferred_matched = preferred_total = 0
    frequencies: dict[str, int] = {}

    for credit in result.per_requirement:
        requirement = credit.requirement
        label = requirement.surface or requirement.canonical
        frequencies[requirement.canonical] = credit.supply
        is_required = requirement.section in {"required", "responsibility"} or requirement.weight >= 2.0
        if is_required:
            required_total += 1
        else:
            preferred_total += 1
        if credit.credit > 0:
            matched.append(label)
            if is_required:
                required_matched += 1
            else:
                preferred_matched += 1
        else:
            missing.append(label)

    return AtsScoreV2(
        score=result.score,
        base_score=result.keyword_score,
        density_penalty=result.stuffing_penalty,
        placement_bonus=result.placement_bonus,
        matched_keywords=matched,
        missing_keywords=missing,
        total_keywords=len(result.per_requirement),
        required_matched=required_matched,
        required_total=required_total,
        preferred_matched=preferred_matched,
        preferred_total=preferred_total,
        term_frequencies=frequencies,
    )


__all__ = ["AtsScoreV2", "score_resume_v2"]
