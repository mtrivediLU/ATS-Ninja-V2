"""Evidence-grounded, phrase-first ATS scoring for Tailoring Engine v2.

The scorer is intentionally small and deterministic.  It does not discover
requirements, infer evidence, or reward arbitrary text copied from a job
description; those responsibilities belong to the requirement extractor and
resolver.  It merely combines their typed inputs with a rendered resume.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from ats_engine.models import EvidenceLink, PlacementAction, RequirementTerm
from ats_engine.parsing.vocab import normalize_term

_CREDIT_TIERS = frozenset({"A", "B", "C", "cert", "variant"})
_WORD = re.compile(r"[A-Za-z0-9+#.]+")


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

    For a tailored resume, a phrase that was absent from the source receives
    credit only if an accepted placement action carries matching provenance.
    This prevents a trailing pasted JD from raising a score while allowing a
    resolver-backed spelling variant or certification implication to be woven
    into a summary or skills section.
    """
    if not requirements:
        return AtsScoreV2(score=0.0, base_score=0.0, density_penalty=0.0, placement_bonus=0.0)

    links_by_canonical = {link.requirement.canonical: link for link in links}
    placement_terms = {normalize_term(action.term) for action in placements}
    placement_terms.update(normalize_term(action.link.requirement.canonical) for action in placements)
    measured = _without_jd_echo(resume_text, requirements) if tailored else resume_text
    source = source_resume_text or ""

    matched: list[str] = []
    missing: list[str] = []
    frequencies: dict[str, int] = {}
    credited_weight = 0.0
    total_weight = 0.0
    required_matched = required_total = preferred_matched = preferred_total = 0

    for requirement in requirements:
        link = links_by_canonical.get(requirement.canonical)
        weight = max(0.0, requirement.weight)
        total_weight += weight
        is_required = requirement.section in {"required", "responsibility"} or requirement.weight >= 2.0
        if is_required:
            required_total += 1
        else:
            preferred_total += 1

        frequency = _requirement_frequency(measured, requirement)
        frequencies[requirement.canonical] = frequency
        evidence_supported = link is not None and link.tier in _CREDIT_TIERS
        source_present = _requirement_frequency(source, requirement) > 0
        placement_supported = normalize_term(requirement.canonical) in placement_terms
        # Candidate source evidence can be represented by a certificate even
        # when the exact phrase is absent from the source text.  It is usable in
        # an optimized document only through an explicit provenance action.
        provenance_ok = not tailored or source_present or placement_supported
        if frequency > 0 and evidence_supported and provenance_ok:
            matched.append(requirement.surface or requirement.canonical)
            credited_weight += weight
            if is_required:
                required_matched += 1
            else:
                preferred_matched += 1
        else:
            missing.append(requirement.surface or requirement.canonical)

    base = round(100.0 * credited_weight / total_weight, 2) if total_weight else 0.0
    penalty = _density_penalty(measured, requirements, frequencies)
    bonus = _placement_bonus(measured, requirements)
    score = round(max(0.0, min(100.0, base - penalty + bonus)), 2)
    return AtsScoreV2(
        score=score,
        base_score=base,
        density_penalty=penalty,
        placement_bonus=bonus,
        matched_keywords=matched,
        missing_keywords=missing,
        total_keywords=len(requirements),
        required_matched=required_matched,
        required_total=required_total,
        preferred_matched=preferred_matched,
        preferred_total=preferred_total,
        term_frequencies=frequencies,
    )


def _forms(requirement: RequirementTerm) -> tuple[str, ...]:
    forms = (requirement.canonical, requirement.surface, *requirement.aliases)
    seen: set[str] = set()
    result: list[str] = []
    for form in forms:
        normalized = normalize_term(form)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(form)
    return tuple(result)


def _requirement_frequency(text: str, requirement: RequirementTerm) -> int:
    normalized_text = normalize_term(text)
    if not normalized_text:
        return 0
    total = 0
    for form in _forms(requirement):
        normalized = normalize_term(form)
        if not normalized:
            continue
        pattern = rf"(?<![\w+#.]){re.escape(normalized)}(?![\w+#.])"
        count = len(re.findall(pattern, normalized_text))
        if count:
            # Aliases are alternate spellings, never independent keywords.
            return count
    return total


def _without_jd_echo(text: str, requirements: list[RequirementTerm]) -> str:
    """Remove exact JD source lines from an otherwise structured resume.

    A pasted job description is usually appended line-for-line.  We remove only
    exact requirement evidence lines, never a normal tailored summary that
    happens to mention several skills, so this is a narrow defense in addition
    to provenance gating.
    """
    evidence_lines = {normalize_term(item.jd_evidence_line) for item in requirements if item.jd_evidence_line}
    kept = [line for line in (text or "").splitlines() if normalize_term(line) not in evidence_lines]
    return "\n".join(kept)


def _density_penalty(text: str, requirements: list[RequirementTerm], frequencies: dict[str, int]) -> float:
    words = max(1, len(_WORD.findall(text or "")))
    penalty = 0.0
    for requirement in requirements:
        frequency = frequencies.get(requirement.canonical, 0)
        if frequency > 4:
            penalty += float(frequency - 4) * 2.0
        if frequency / words > 0.06:
            penalty += 2.0
    return min(10.0, penalty)


def _placement_bonus(text: str, requirements: list[RequirementTerm]) -> float:
    """Award a small readability bonus for a term used in skills and a bullet."""
    lowered = text.casefold()
    skills_match = re.search(
        r"(?:technical\s+)?skills\s*\n(.*?)(?:\n\s*professional\s+experience|\n\s*experience)", lowered, re.S
    )
    skills = skills_match.group(1) if skills_match else ""
    bullets = "\n".join(line for line in lowered.splitlines() if line.lstrip().startswith(("-", "*", "•")))
    bonus_terms = 0
    for requirement in requirements:
        if _requirement_frequency(skills, requirement) and _requirement_frequency(bullets, requirement):
            bonus_terms += 1
    return min(5.0, float(bonus_terms))


__all__ = ["AtsScoreV2", "score_resume_v2"]
