"""Deterministic, provenance-scoped placement planning for Tailoring Engine v2."""

from __future__ import annotations

import re

from ats_engine.generation.diagnostics import ProposalRecord, ProposalStatus, _word_count
from ats_engine.models import EvidenceLink, JDProfile, PlacementAction, Profile
from ats_engine.rachana.operations import SurfaceVariantMatch, find_surface_variant

_PLACEABLE_TIERS = frozenset({"A", "B", "C", "cert", "variant"})


def plan_placements(
    links: list[EvidenceLink],
    profile: Profile,
    jd_profile: JDProfile,
) -> list[PlacementAction]:
    """Return bounded actions for requirements with candidate-source evidence.

    Missing and adjacency-only requirements intentionally produce no action: an
    adjacent tool can help a gap narrative but can never authorize the bare JD
    term in a candidate-facing resume.
    """
    del jd_profile  # The typed link already carries the JD surface and weight.
    supported = [link for link in links if link.tier in _PLACEABLE_TIERS]
    supported.sort(key=lambda link: (-link.requirement.weight, link.requirement.canonical))
    actions: list[PlacementAction] = []

    # Four explicit links plus a certificate reference can account for a fifth
    # targeted phrase, which keeps the rendered summary within its hard budget.
    summary_links = supported[:4]
    for link in summary_links:
        actions.append(_action(link, "summary", "mention_summary"))

    # The skills section may gain only source-backed entries and is bounded at
    # six new terms across the kit. Existing source taxonomy is preserved by
    # the optimizer when it applies these actions.
    for link in supported[:6]:
        actions.append(_action(link, "skills", "append_skill"))

    # Keep the headline readable instead of adding a third placement for a
    # Power BI certificate phrase already surfaced in summary and skills.
    headline_links = [
        link
        for link in supported
        if _headline_eligible(link) and link.tier != "cert" and not link.requirement.canonical.startswith("power bi")
    ][:3]
    if len(headline_links) < 2:
        headline_links.extend(link for link in supported if _headline_eligible(link) and link not in headline_links)
        headline_links = headline_links[:3]
    for link in headline_links:
        actions.append(_action(link, "headline", "headline_mention"))

    # A bullet is eligible only where the resolver found direct experience
    # evidence. The optimizer deliberately uses this action only for safe
    # spelling variants; it never paraphrases a candidate fact to make room.
    bullet_counts: dict[str, int] = {}
    for link in supported:
        if link.tier != "A" or not link.resume_location.startswith("experience:"):
            continue
        count = bullet_counts.get(link.resume_location, 0)
        if count >= 2:
            continue
        bullet_counts[link.resume_location] = count + 1
        actions.append(_action(link, link.resume_location, "weave_bullet"))

    # SURFACE_VARIANT: the candidate's own authored text (summary, skills, or
    # a bullet) already states this exact requirement in a vocabulary-
    # registered spelling other than the employer's -- substitute the
    # employer's literal surface in place. One evidence link resolves to one
    # source location, so this naturally proposes at most one substitution
    # per requirement without an artificial cap.
    for link in supported:
        variant = find_surface_variant(link)
        if variant is not None:
            actions.append(_surface_variant_action(link, variant))
    return actions


def plan_placements_with_inventory(
    links: list[EvidenceLink],
    profile: Profile,
    jd_profile: JDProfile,
) -> tuple[list[PlacementAction], tuple[ProposalRecord, ...]]:
    """Return planner actions with a one-to-one, initially unevaluated inventory.

    ``plan_placements`` remains the public compatibility entry point.  The
    inventory is deliberately generated from exactly the same returned action
    list, which makes omission and duplicate-record bugs observable.
    """
    actions = plan_placements(links, profile, jd_profile)
    return actions, proposal_inventory(actions)


def proposal_inventory(actions: list[PlacementAction]) -> tuple[ProposalRecord, ...]:
    """Build initial diagnostics records for an already-planned action list."""
    records: list[ProposalRecord] = []
    seen_ids: set[str] = set()
    for action in actions:
        record = _proposal_record(action)
        if record.id in seen_ids:
            raise AssertionError(f"planner emitted a duplicate proposal id: {record.id}")
        seen_ids.add(record.id)
        records.append(record)
    return tuple(records)


def _action(link: EvidenceLink, target: str, operation: str) -> PlacementAction:
    term = link.surface_to_use or link.requirement.surface or link.requirement.canonical
    provenance = link.supporting_locations or link.supporting_spans
    return PlacementAction(
        term=term,
        link=link,
        target=target,
        operation=operation,
        rendered_text=term,
        grounded_by=" | ".join(provenance) if provenance else (link.resume_location or link.resume_span),
    )


def _surface_variant_action(link: EvidenceLink, variant: SurfaceVariantMatch) -> PlacementAction:
    provenance = link.supporting_locations or link.supporting_spans
    return PlacementAction(
        term=variant.target_surface,
        link=link,
        target=link.resume_location,
        operation="surface_variant",
        rendered_text=variant.target_surface,
        grounded_by=" | ".join(provenance) if provenance else (link.resume_location or link.resume_span),
    )


def _headline_eligible(link: EvidenceLink) -> bool:
    requirement = link.requirement
    if requirement.ngram >= 2:
        return True
    return requirement.kind in {"tool", "framework", "language", "platform"}


def _proposal_record(action: PlacementAction) -> ProposalRecord:
    link = action.link
    canonical = link.requirement.canonical
    locations = link.supporting_locations or ((link.resume_location,) if link.resume_location else ())
    if not locations and link.supporting_spans:
        locations = link.supporting_spans
    stable_id = ":".join(
        (
            action.operation,
            action.target,
            canonical,
            re.sub(r"\s+", "-", action.term.strip().casefold()),
        )
    )
    return ProposalRecord(
        id=stable_id,
        operation=action.operation,
        target=action.target,
        requirement_canonicals=(canonical,),
        requirement_weight=link.requirement.weight,
        evidence_tier=link.tier,
        evidence_locations=tuple(locations),
        surface_to_use=action.term,
        word_delta=_word_count(action.rendered_text) - _word_count(_replaced_text(action)),
        status=ProposalStatus.NOT_EVALUATED,
        gate_code=None,
        gate_detail="",
        score_before=None,
        score_after=None,
        score_delta=None,
        # The optimizer writes the actual batch and iteration as it evaluates
        # this proposal. -1 means the planner emitted it but no batch reached it.
        batch_index=-1,
        iteration=0,
    )


def _replaced_text(action: PlacementAction) -> str:
    """Return source text replaced by an in-place operation, if any.

    ``surface_variant`` replaces only the candidate's own matched spelling
    (a word or short phrase), never the whole evidence span it was found in
    -- re-deriving it here keeps this in one place with the operation itself
    rather than duplicating the match.
    """
    if action.operation == "surface_variant":
        variant = find_surface_variant(action.link)
        return variant.original if variant is not None else ""
    if action.operation == "weave_bullet":
        return action.link.resume_span
    return ""


__all__ = ["plan_placements", "plan_placements_with_inventory", "proposal_inventory"]
