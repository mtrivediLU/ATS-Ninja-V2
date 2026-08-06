"""SURFACE_VARIANT: literal substitution of the employer's exact spelling.

PRAMANA is alias-aware by design (see ``rachana.objectives``), so a candidate
who wrote "ReactJS" already earns full credit against a JD asking for
"React". A literal-string ATS scanner is not alias-aware, and rewards only
the JD's own spelling. This module closes that specific, narrow gap: given
evidence that the candidate already has the skill, expressed in their own
authored text with a *different* vocabulary-registered spelling than the
employer used, substitute the employer's exact surface for the candidate's
one, in place, and nothing else.

This is deliberately not a rewrite, a paraphrase, or a claim of any kind. Two
properties make that true by construction rather than by review:

* **Vocabulary-backed identity only.** The candidate's spelling and the
  employer's spelling must already be registered aliases of the *same*
  vocabulary entry (``ats_engine.parsing.vocab``). There is no semantic or
  "adjacent skill" relation here -- that is a different, and much riskier,
  kind of change, and out of scope for this operation.
* **Fail closed.** Every function below returns a rejection object instead of
  a guess whenever the substitution cannot be *proven* safe against the
  actual text at hand: a substring hazard (``React`` inside ``React Native``),
  a checkable fact at risk (a metric changing shape), or the target text no
  longer containing what was matched when this candidate was planned.
"""

from __future__ import annotations

from dataclasses import dataclass

from ats_engine.models import EvidenceLink
from ats_engine.parsing.vocab import VocabularyMatch, find_vocabulary_matches, vocabulary_entry
from ats_engine.rachana.facts import extract_metrics
from ats_engine.rachana.preservation import count_occurrences


@dataclass(frozen=True, slots=True)
class SurfaceVariantMatch:
    """One candidate-authored occurrence eligible for exact-surface substitution."""

    canonical: str
    original: str
    target_surface: str


@dataclass(frozen=True, slots=True)
class SurfaceVariantResult:
    """A substitution that either changed the text or had nothing to do."""

    text: str
    changed: bool


@dataclass(frozen=True, slots=True)
class SurfaceVariantRejection:
    """A substitution that failed closed, with the reason a caller can map to a gate code."""

    reason: str  # "substring_hazard" | "fact_risk" | "text_drifted"
    detail: str


# The evidence tiers backed by the candidate's own authored text. "cert" and
# "adjacency" evidence never yields a literal span of the candidate's own
# phrasing to substitute -- a certificate name and an adjacent tool are both
# immutable or unrelated text respectively, not a spelling of this term.
_ELIGIBLE_TIERS = frozenset({"A", "B", "C"})


def find_surface_variant(link: EvidenceLink) -> SurfaceVariantMatch | None:
    """Return the substitution opportunity in *link*, if any.

    None is returned -- not proposed, not a rejection -- for every case where
    there is nothing to substitute: the evidence is not the candidate's own
    text, the requirement is not vocabulary-backed, the JD states no surface,
    the candidate's span already contains it, or resolving the candidate's
    own spelling from that span is not safe (see ``_safe_match``).
    """
    requirement = link.requirement
    if link.tier not in _ELIGIBLE_TIERS:
        return None
    entry = vocabulary_entry(requirement.canonical)
    if entry is None:
        return None
    target_surface = (requirement.surface or "").strip()
    if not target_surface:
        return None
    span = link.resume_span
    if not span or count_occurrences(span, target_surface) > 0:
        return None
    match = _safe_match(span, entry.canonical)
    if match is None:
        return None
    if match.surface.strip().casefold() == target_surface.casefold():
        return None
    return SurfaceVariantMatch(canonical=entry.canonical, original=match.surface, target_surface=target_surface)


def _safe_match(text: str, canonical: str) -> VocabularyMatch | None:
    """The one occurrence of *canonical* in *text*, or None if absent or hazardous.

    A match is hazardous when it overlaps a *different* canonical's match at
    the same position -- the ``React`` inside ``React Native`` case.
    ``find_vocabulary_matches`` already resolves overlaps by longest-match,
    but it reports every candidate span, including the ones it did not pick;
    checking for an overlapping different-canonical match here is what turns
    that reporting into a hazard guard instead of just a hint.
    """
    matches = find_vocabulary_matches(text)
    for candidate in matches:
        if candidate.entry.canonical != canonical:
            continue
        hazard = any(
            other.entry.canonical != canonical and other.start < candidate.end and candidate.start < other.end
            for other in matches
        )
        if hazard:
            return None
        return candidate
    return None


def substitute_surface_variant(
    text: str, variant: SurfaceVariantMatch
) -> SurfaceVariantResult | SurfaceVariantRejection:
    """Apply *variant* to *text*, or fail closed with the specific reason why not.

    Idempotent and reversible by construction:

    * If ``target_surface`` is already present and ``original`` is not, this
      is a no-op (``changed=False``) -- for example because this exact
      substitution already ran. Applying this function to its own output
      therefore always returns that output unchanged.
    * A successful result is reversible by swapping ``original`` and
      ``target_surface`` and calling this function again: the replaced span
      is exactly ``target_surface``, so the inverse call's match is exact.
    """
    if count_occurrences(text, variant.target_surface) > 0 and count_occurrences(text, variant.original) == 0:
        return SurfaceVariantResult(text=text, changed=False)

    matches = find_vocabulary_matches(text)
    same_canonical = [candidate for candidate in matches if candidate.entry.canonical == variant.canonical]
    match = next(
        (
            candidate
            for candidate in same_canonical
            if candidate.surface.strip().casefold() == variant.original.strip().casefold()
        ),
        None,
    )
    if match is None:
        found = f"; found {same_canonical[0].surface!r} instead" if same_canonical else ""
        return SurfaceVariantRejection(
            reason="text_drifted",
            detail=f"expected to find {variant.original!r} in the current text but it is no longer present{found}",
        )
    hazard = any(
        other.entry.canonical != variant.canonical and other.start < match.end and match.start < other.end
        for other in matches
    )
    if hazard:
        return SurfaceVariantRejection(
            reason="substring_hazard",
            detail=f"{variant.original!r} could not be safely isolated from an overlapping term in the current text",
        )

    substituted = text[: match.start] + variant.target_surface + text[match.end :]
    if extract_metrics(text) != extract_metrics(substituted):
        return SurfaceVariantRejection(
            reason="fact_risk",
            detail="substitution would change a checkable metric in the surrounding text",
        )
    return SurfaceVariantResult(text=substituted, changed=True)


__all__ = [
    "SurfaceVariantMatch",
    "SurfaceVariantRejection",
    "SurfaceVariantResult",
    "find_surface_variant",
    "substitute_surface_variant",
]
