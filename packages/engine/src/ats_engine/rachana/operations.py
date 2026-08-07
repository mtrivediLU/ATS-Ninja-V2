"""The RACHANA operation catalogue: SURFACE_VARIANT and the prose rewrites.

SURFACE_VARIANT (below) is a deterministic literal substitution. SUMMARY_REWRITE
and BULLET_REWRITE (further down) are the two operations that let a language
model author candidate-facing prose, under the structured, evidence-cited
contract in :mod:`ats_engine.rachana.prose`. They are ordinary operations: they
produce proposals the optimizer accepts through the same pareto policy, they
record the same reversible ledger entries, and they fail closed to the
candidate's own wording exactly as everything else here does.

--- SURFACE_VARIANT ---------------------------------------------------------

Literal substitution of the employer's exact spelling.

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

from collections.abc import Sequence
from dataclasses import dataclass

from ats_engine.caching.content_hash import ContentHashCache
from ats_engine.models import EvidenceLink, Profile, RequirementTerm
from ats_engine.parsing.vocab import VocabularyMatch, find_vocabulary_matches, vocabulary_entry
from ats_engine.providers.base import LLMProvider, generate_json
from ats_engine.rachana.facts import ImmutableFactSet, extract_metrics
from ats_engine.rachana.preservation import count_occurrences
from ats_engine.rachana.prose import (
    BULLET_REWRITE,
    REJECT_EVIDENCE_OUT_OF_SCOPE,
    REJECT_MALFORMED,
    REJECT_NO_PROVIDER,
    SUMMARY_REWRITE,
    EvidenceNode,
    ProseProposal,
    ProseRejection,
    build_evidence_nodes,
    bullet_rewrite_prompt,
    parse_proposal,
    repair_prompt,
    role_nodes,
    summary_rewrite_prompt,
    validate_proposal,
)


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


# --------------------------------------------------------------------------- #
# SUMMARY_REWRITE / BULLET_REWRITE
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ProseAttempt:
    """One provider attempt and what became of it.

    Recorded for every attempt, accepted or not, so a reviewer can see what the
    model proposed and why it was refused without re-running anything. The
    proposed text is retained verbatim on a *rejected* attempt for exactly that
    reason: an unsafe model attempt must be visible, not silently discarded.
    """

    index: int
    rejection: ProseRejection | None
    proposed_text: str = ""

    @property
    def accepted(self) -> bool:
        return self.rejection is None


@dataclass(frozen=True, slots=True)
class ProseOutcome:
    """The terminal result of one bounded prose request.

    Exactly one of ``proposal`` / ``rejection`` is set. ``rejection`` set means
    the caller falls back to the source text -- there is no third state, and no
    partially repaired rewrite.
    """

    proposal: ProseProposal | None
    rejection: ProseRejection | None
    attempts: tuple[ProseAttempt, ...]


# One structured proposal, then at most one repair request. Two, not a
# configurable number: an unbounded (or caller-tunable) retry loop against a
# model that keeps failing the same gate burns latency to produce the same
# deterministic fallback, and every extra attempt is another chance for a
# fabrication to slip past a validator that is only as good as its rules.
_MAX_ATTEMPTS = 2


def request_rewrite(
    provider: LLMProvider | None,
    *,
    prompt: str,
    operation: str,
    target_id: str,
    original_text: str,
    allowed: Sequence[EvidenceNode],
    profile: Profile,
    fact_set: ImmutableFactSet | None = None,
    allow_neutral_nodes: bool = True,
    cache: ContentHashCache | None = None,
) -> ProseOutcome:
    """Ask the provider for one rewrite, with a bounded repair and hard fallback.

    Provably terminating: the loop below is a ``range(_MAX_ATTEMPTS)`` with no
    recursion, no ``while``, and no path that extends it. ``generate_json`` is
    called with ``retries=0`` so its own JSON self-repair cannot silently add
    attempts on top -- malformed JSON is a rejection here, and the single repair
    request carries the validator's machine-readable reason rather than a
    generic "that was not JSON".

    Returns a rejection (never a guess) when the provider is absent, unreachable,
    or cannot produce an admissible proposal; the caller then keeps
    ``original_text`` exactly.
    """
    if provider is None:
        return ProseOutcome(
            proposal=None,
            rejection=ProseRejection(reason=REJECT_NO_PROVIDER, detail="no provider available for prose rewriting"),
            attempts=(),
        )

    attempts: list[ProseAttempt] = []
    current_prompt = prompt
    rejection = ProseRejection(reason=REJECT_MALFORMED, detail="provider produced no reply")
    for index in range(_MAX_ATTEMPTS):
        payload = generate_json(provider, current_prompt, retries=0, cache=cache)
        parsed = parse_proposal(payload, operation=operation, target_id=target_id)
        if isinstance(parsed, ProseRejection):
            rejection = parsed
            attempts.append(ProseAttempt(index=index, rejection=parsed))
        else:
            verdict = validate_proposal(
                parsed,
                original_text=original_text,
                allowed=allowed,
                profile=profile,
                fact_set=fact_set,
                allow_neutral_nodes=allow_neutral_nodes,
            )
            attempts.append(ProseAttempt(index=index, rejection=verdict, proposed_text=parsed.proposed_text))
            if verdict is None:
                return ProseOutcome(proposal=parsed, rejection=None, attempts=tuple(attempts))
            rejection = verdict
        if index + 1 < _MAX_ATTEMPTS:
            current_prompt = repair_prompt(prompt, rejection)
    return ProseOutcome(proposal=None, rejection=rejection, attempts=tuple(attempts))


def propose_summary_rewrite(
    provider: LLMProvider | None,
    *,
    original_text: str,
    profile: Profile,
    requirements: Sequence[RequirementTerm],
    target_title: str,
    nodes: Sequence[EvidenceNode] | None = None,
    fact_set: ImmutableFactSet | None = None,
    cache: ContentHashCache | None = None,
) -> ProseOutcome:
    """Propose a re-expressed professional summary, fully cited or not at all.

    A summary legitimately spans a career, so the whole evidence graph is
    citable here -- but each individual claim is still confined to one employer
    (see ``prose.validate_proposal``), so the breadth is across sentences, never
    inside one statement.
    """
    graph = tuple(nodes) if nodes is not None else build_evidence_nodes(profile)
    prompt = summary_rewrite_prompt(
        original_text=original_text,
        nodes=graph,
        requirements=requirements,
        target_title=target_title,
    )
    return request_rewrite(
        provider,
        prompt=prompt,
        operation=SUMMARY_REWRITE,
        target_id="resume:summary",
        original_text=original_text,
        allowed=graph,
        profile=profile,
        fact_set=fact_set,
        cache=cache,
    )


def propose_bullet_rewrite(
    provider: LLMProvider | None,
    *,
    role_index: int,
    bullet_index: int,
    original_text: str,
    profile: Profile,
    requirements: Sequence[RequirementTerm],
    nodes: Sequence[EvidenceNode] | None = None,
    fact_set: ImmutableFactSet | None = None,
    cache: ContentHashCache | None = None,
) -> ProseOutcome:
    """Propose a re-worded bullet supported by evidence from its own role only.

    This is where the same-bullet restriction is relaxed to same-role, and it is
    relaxed by *widening the citable bundle*, not by loosening a gate: the bundle
    is ``prose.role_nodes(...)``, so cross-employer blending stays structurally
    impossible rather than merely discouraged. Employer-neutral nodes are
    excluded as well -- a listed skill says the candidate has it somewhere, and
    a bullet citing it would be asserting they used it *at this employer*.
    """
    graph = tuple(nodes) if nodes is not None else build_evidence_nodes(profile)
    bundle = role_nodes(graph, role_index)
    if not bundle:
        return ProseOutcome(
            proposal=None,
            rejection=ProseRejection(
                reason=REJECT_EVIDENCE_OUT_OF_SCOPE,
                detail=f"role {role_index} has no citable bullet evidence",
            ),
            attempts=(),
        )
    role = profile.experiences[role_index] if 0 <= role_index < len(profile.experiences) else None
    target_id = f"experience:{role_index}:bullet:{bullet_index}"
    prompt = bullet_rewrite_prompt(
        target_id=target_id,
        original_text=original_text,
        nodes=bundle,
        requirements=requirements,
        employer=role.company if role is not None else "",
        title=role.title if role is not None else "",
    )
    return request_rewrite(
        provider,
        prompt=prompt,
        operation=BULLET_REWRITE,
        target_id=target_id,
        original_text=original_text,
        allowed=bundle,
        profile=profile,
        fact_set=fact_set,
        allow_neutral_nodes=False,
        cache=cache,
    )


__all__ = [
    "ProseAttempt",
    "ProseOutcome",
    "SurfaceVariantMatch",
    "SurfaceVariantRejection",
    "SurfaceVariantResult",
    "find_surface_variant",
    "propose_bullet_rewrite",
    "propose_summary_rewrite",
    "request_rewrite",
    "substitute_surface_variant",
]
