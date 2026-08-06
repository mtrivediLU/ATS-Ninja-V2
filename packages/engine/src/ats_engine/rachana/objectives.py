"""Multi-objective scoring for tailoring candidates.

PRAMANA is alias-aware and saturating by design: ``React`` and ``ReactJS``
already score identically to it, and a term the JD names nine times never
demands nine resume mentions. That is correct for *PRAMANA's own* purpose
(estimating genuine role fit) but it means PRAMANA's scalar score cannot see
-- let alone reward -- a change that only improves how a literal-string
external ATS scanner reads the document. A scalar acceptance gate built only
on PRAMANA's score therefore vetoes every such change on merit-neutral
grounds, not because the change is unsafe.

This module gives those effects their own, separately measurable objectives
so an acceptance policy can act on them without conflating them with PRAMANA
itself. Nothing here replaces PRAMANA; ``pramana_coverage`` below is a
reuse of PRAMANA's own weighted keyword component, not a second formula.
"""

from __future__ import annotations

from dataclasses import dataclass

from ats_engine.generation.diagnostics import _word_count
from ats_engine.models import RequirementTerm
from ats_engine.pramana.contract import PramanaScore, RequirementCredit
from ats_engine.rachana.preservation import count_occurrences
from ats_engine.validation.fidelity import contains_fact


@dataclass(frozen=True, slots=True)
class ScoreVector:
    """The objectives a placement candidate is judged on, beyond fact safety.

    ``pramana_coverage``: PRAMANA's own weighted keyword-credit ratio
        (``keyword_score / 100``), i.e. how much of the JD's weighted demand
        this text earns credit for. Excludes PRAMANA's title-alignment bonus
        and stuffing penalty, which are about the *scalar score*, not demand
        coverage.
    ``jd_surface_adoption``: of the requirements PRAMANA is *already*
        crediting, what fraction are expressed using the employer's literal
        stated surface form (see ``surface_adoption_ratio`` below).
    ``density``: relevant JD-term canonicals visibly expressed per 100 words
        (see ``relevant_terms_per_100_words`` below).
    ``placement_reinforcement``: how many already-credited requirements are
        reinforced by appearing in *both* skills and an experience bullet --
        a recruiter-skim readability signal, reused directly from PRAMANA's
        own ``placement_bonus`` (``pramana/scoring.py::_placement_bonus``)
        rather than recomputed here. PRAMANA excludes it from
        ``keyword_score`` (and therefore from ``pramana_coverage`` above) by
        design, since it is not demand coverage; a scalar acceptance rule
        that only looks at PRAMANA's total score can still see it, but the
        pareto policy's other three objectives structurally cannot. Without
        this as its own objective, pareto has no way to accept a safe,
        genuinely useful dual-placement action that legacy accepted on this
        basis alone. Deliberately not normalized to 0..1, matching
        ``placement_bonus``'s own native 0..4 scale (and ``word_count``'s
        precedent for an unnormalized field on this vector).
    ``word_count``: the text's own word count, so acceptance can refuse a
        change that grows the document to buy either metric.
    """

    pramana_coverage: float
    jd_surface_adoption: float
    density: float
    placement_reinforcement: float
    word_count: int


def relevant_terms_per_100_words(text: str, requirements: list[RequirementTerm]) -> float:
    """Distinct requirement canonicals visibly expressed, per 100 words.

    This is the definition ``RunDiagnostics.relevant_terms_per_100_words``
    has always used (moved here unchanged from the optimizer's internal
    helper, per Phase 0): count each requirement canonical at most once,
    regardless of how many times it repeats, and normalize by length so a
    longer document is not penalized for having more words. It is a
    stuffing-resistant proxy for "does this read as relevant," not a
    frequency count and not an acceptance input by itself.
    """
    words = _word_count(text)
    if words == 0:
        return 0.0
    canonicals = {requirement.canonical for requirement in requirements if requirement.canonical}
    visible = sum(contains_fact(text, canonical) for canonical in canonicals)
    return visible / (words / 100)


def surface_adoption_ratio(text: str, per_requirement: list[RequirementCredit]) -> float:
    """Of the requirements this text already earns PRAMANA credit for, what
    fraction use the employer's own literal surface spelling.

    PRAMANA's ``credit > 0`` is the admission gate: adoption is measured only
    over requirements the resume *already* genuinely supports, because a
    literal-surface match on a requirement with no real evidence would be
    fabrication, not adoption, and PRAMANA's provenance gate already prevents
    that credit from existing in the first place. Vacuously 1.0 when nothing
    is credited yet -- there is nothing to have failed to adopt -- matching
    the convention ``PramanaScore.required_coverage`` already uses when its
    denominator is zero.

    Deliberately an unweighted fraction of requirements, not weighted by
    ``requirement.weight``: this answers "how many of the things I'm already
    getting credit for would a keyword scanner also find," a set-membership
    question, not a demand-weighted one. ``pramana_coverage`` above is where
    weight already lives.
    """
    supported = [credit for credit in per_requirement if credit.credit > 0]
    if not supported:
        return 1.0
    adopted = sum(1 for credit in supported if _uses_exact_surface(text, credit.requirement))
    return adopted / len(supported)


def _uses_exact_surface(text: str, requirement: RequirementTerm) -> bool:
    surface = (requirement.surface or "").strip()
    if not surface:
        return False
    return count_occurrences(text, surface) > 0


def score_vector(text: str, requirements: list[RequirementTerm], pramana: PramanaScore) -> ScoreVector:
    """Build the full objective vector for *text* from an already-scored PRAMANA pass.

    Takes the ``PramanaScore`` as an argument rather than computing it, so a
    caller that also needs the legacy ``AtsScoreV2`` projection (via
    ``project_ats_v2``) scores the text with PRAMANA exactly once.
    """
    return ScoreVector(
        pramana_coverage=pramana.keyword_score / 100.0,
        jd_surface_adoption=surface_adoption_ratio(text, pramana.per_requirement),
        density=relevant_terms_per_100_words(text, requirements),
        placement_reinforcement=pramana.placement_bonus,
        word_count=_word_count(text),
    )


__all__ = ["ScoreVector", "relevant_terms_per_100_words", "score_vector", "surface_adoption_ratio"]
