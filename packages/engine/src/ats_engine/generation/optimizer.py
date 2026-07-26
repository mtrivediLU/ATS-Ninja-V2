"""Monotone deterministic optimization for Tailoring Engine v2."""

from __future__ import annotations

import re
from collections.abc import Iterable
from copy import deepcopy

from ats_engine.generation.integration_planner import plan_placements
from ats_engine.generation.resume import generate_resume_text
from ats_engine.kit.contract import OptimizationRejection, OptimizationTrace
from ats_engine.models import (
    EvidenceLink,
    JDProfile,
    PlacementAction,
    PlanDecision,
    Profile,
    RequirementTerm,
    ResumePlan,
)
from ats_engine.parsing.vocab import normalize_term
from ats_engine.scoring.ats_v2 import AtsScoreV2, score_resume_v2
from ats_engine.validation.fidelity import BulletPair, validate_resume_fidelity
from ats_engine.validation.stuffing import validate_resume_stuffing

_BATCH_SIZE = 8
_MAX_ITERATIONS = 4


def optimize(
    profile: Profile,
    jd_profile: JDProfile,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
    base_plan: ResumePlan,
) -> tuple[ResumePlan, OptimizationTrace]:
    """Apply source-backed placements only while every score step improves.

    The plan is rebuilt from source-backed content rather than incrementally
    rewriting candidate bullets. Failed actions are bisected to their safe
    subset, and the final fallback is the original-content plan whenever a
    regression cannot be avoided.
    """
    source = profile.raw_markdown
    source_plan = _source_content_plan(base_plan, profile, links)
    original = score_resume_v2(source, requirements, links, source_resume_text=source)
    trace = OptimizationTrace(
        iterations=0,
        score_path=[original.score],
        unreachable_terms=[link.requirement.canonical for link in links if link.tier == "missing"],
    )
    if not requirements or not links:
        return source_plan, trace

    actions = plan_placements(links, profile, jd_profile)
    actions = _dedupe_actions(actions)
    accepted: list[PlacementAction] = []
    current_plan = source_plan
    current_score = _score_plan(current_plan, source, requirements, links, accepted)

    # An incomplete legacy parse should never cause an optimizer regression.
    # Keep the base plan in that rare case; orchestration applies the final hard
    # score check after rendering and can withhold the tailored projection.
    if current_score.score + 0.001 < original.score:
        trace.rejected_actions.append(
            OptimizationRejection(action="source_content_plan", reason="source projection scored below raw resume")
        )
        return base_plan, trace

    for offset in range(0, len(actions), _BATCH_SIZE):
        if trace.iterations >= _MAX_ITERATIONS:
            break
        batch = actions[offset : offset + _BATCH_SIZE]
        trace.iterations += 1
        candidate_plan, candidate_actions, rejected = _accept_safe_actions(
            current_plan,
            accepted,
            batch,
            profile,
            requirements,
            links,
            source,
        )
        trace.rejected_actions.extend(rejected)
        candidate_score = _score_plan(candidate_plan, source, requirements, links, candidate_actions)
        if candidate_score.score > current_score.score:
            current_plan = candidate_plan
            accepted = candidate_actions
            current_score = candidate_score
            trace.score_path.append(current_score.score)
            trace.accepted_actions.extend(
                _action_label(action) for action in candidate_actions[len(accepted) - len(batch) :]
            )
        else:
            for action in batch:
                trace.rejected_actions.append(
                    OptimizationRejection(action=_action_label(action), reason="score did not strictly improve")
                )
        if len(trace.score_path) >= 2 and trace.score_path[-1] - trace.score_path[-2] < 0.5:
            break

    # The accepted-action expression above intentionally records exactly the
    # action list present in the final plan below, avoiding an untrusted
    # re-parse of rendered prose as a provenance source.
    current_plan.placement_actions = list(accepted)
    current_plan.plan_decisions = _v2_plan_decisions(
        base_plan.plan_decisions,
        current_plan,
        profile,
        accepted,
    )
    final_score = _score_plan(current_plan, source, requirements, links, accepted)
    if final_score.score + 0.001 < original.score:
        trace.rejected_actions.append(
            OptimizationRejection(action="final_plan", reason="would regress below original source score")
        )
        return source_plan, trace
    # The trace's action labels are recalculated from the final provenance set
    # to avoid duplicates introduced by batched bisection.
    trace.accepted_actions = [_action_label(action) for action in accepted]
    if not trace.score_path or trace.score_path[-1] != final_score.score:
        trace.score_path.append(final_score.score)
    return current_plan, trace


def _source_content_plan(
    base_plan: ResumePlan,
    profile: Profile,
    links: list[EvidenceLink],
) -> ResumePlan:
    plan = deepcopy(base_plan)
    plan.experience = deepcopy(profile.experiences)
    plan.education = deepcopy(profile.education)
    plan.certifications = deepcopy(profile.certifications)
    # Do not retain the legacy fallback summary here: it can infer a career
    # duration from date ranges (for example "2+ years") that the candidate
    # never stated. A source summary wins; otherwise a verified role title is
    # the only safe deterministic seed before v2 placements are applied.
    plan.summary = _with_targeting(profile.source_summary or _source_role_summary(profile), plan.jd_profile)
    plan.headline = plan.role_identity
    # Keep the planner's instrumented change ledger. V2 placement decisions
    # are added below, but removing the established summary/bullet records
    # would make a delivered kit impossible to review or revise through the
    # existing change-action contract.
    plan.placement_actions = []
    if profile.source_skill_groups:
        plan.skill_groups = deepcopy(profile.source_skill_groups)
    else:
        values = _dedupe_text([*profile.tier_a.values(), *profile.tier_b.values(), *profile.tier_c.values()])
        plan.skill_groups = [("Technical Skills", values)] if values else []
    plan.skill_groups = _annotate_tier_c_skills(plan.skill_groups, links)
    return plan


def _accept_safe_actions(
    plan: ResumePlan,
    accepted: list[PlacementAction],
    pending: list[PlacementAction],
    profile: Profile,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
    source: str,
) -> tuple[ResumePlan, list[PlacementAction], list[OptimizationRejection]]:
    """Bisect a failed batch down to individually safe actions."""
    candidate_actions = [*accepted, *pending]
    candidate = _apply_actions(plan, candidate_actions, profile)
    errors = _gate_errors(candidate, profile, requirements, candidate_actions, source)
    if not errors:
        return candidate, candidate_actions, []
    if len(pending) == 1:
        action = pending[0]
        return (
            plan,
            accepted,
            [OptimizationRejection(action=_action_label(action), reason="; ".join(errors[:2]))],
        )
    midpoint = len(pending) // 2
    left_plan, left_actions, left_rejected = _accept_safe_actions(
        plan, accepted, pending[:midpoint], profile, requirements, links, source
    )
    right_plan, right_actions, right_rejected = _accept_safe_actions(
        left_plan, left_actions, pending[midpoint:], profile, requirements, links, source
    )
    return right_plan, right_actions, [*left_rejected, *right_rejected]


def _apply_actions(base: ResumePlan, actions: list[PlacementAction], profile: Profile) -> ResumePlan:
    plan = deepcopy(base)
    summary_links = [action.link for action in actions if action.target == "summary"]
    _apply_summary(plan, summary_links, profile.source_summary or _source_role_summary(profile))
    _apply_skills(plan, [action for action in actions if action.target == "skills"], profile)
    _apply_headline(plan, [action for action in actions if action.target == "headline"])
    # Bullet actions are source-order annotations only. A direct source bullet
    # already carries the phrase; forcing a paraphrase creates fact-loss risk.
    plan.placement_actions = list(actions)
    return plan


def _apply_summary(plan: ResumePlan, links: list[EvidenceLink], source_summary: str) -> None:
    # A cert name can itself match a parent requirement (for example Power BI
    # in the PL-300 certificate). Four explicit actions plus that certification
    # reference stay within the five-term summary budget while still letting
    # the scorer surface the high-value certificate implications.
    links = links[:4]
    direct = _dedupe_text(
        [link.surface_to_use or link.requirement.surface for link in links if link.tier in {"A", "B", "variant"}]
    )[:5]
    certified = _dedupe_text(
        [link.surface_to_use or link.requirement.surface for link in links if link.tier == "cert"]
    )[:5]
    # ``_source_content_plan`` retains the candidate summary, including every
    # source metric.  V2 targeting prose is additive around that evidence; it
    # never replaces the candidate's own factual introduction.
    parts: list[str] = [source_summary.strip()] if source_summary.strip() else []
    if direct:
        parts.append(f"{plan.role_identity} with demonstrated experience in {_join(direct)}.")
    if certified:
        certificate = _certificate_reference(links)
        parts.append(f"{certificate} supports knowledge of {_join(certified)}.")
    plan.summary = _with_targeting(" ".join(parts), plan.jd_profile)


def _apply_skills(plan: ResumePlan, actions: list[PlacementAction], profile: Profile) -> None:
    # ``plan`` starts as the source-content projection, which may include a
    # conservative ``(Working Knowledge)`` annotation for a resolver-confirmed
    # Tier-C skill.  Start from that projection instead of resetting it to the
    # raw groups so later accepted actions never erase the qualification label.
    groups = deepcopy(plan.skill_groups) if plan.skill_groups else deepcopy(profile.source_skill_groups)
    if not groups:
        groups = [("Technical Skills", [])]
    append_count = 0
    for action in actions:
        if append_count >= 6:
            break
        link = action.link
        if link.tier not in {"A", "B", "C", "cert", "variant"}:
            continue
        surface = action.term
        existing = _find_equivalent_skill(groups, link)
        if existing is not None:
            group_index, item_index = existing
            prior_item = groups[group_index][1][item_index]
            groups[group_index][1][item_index] = (
                f"{surface} (Working Knowledge)"
                if link.tier == "C" and "working knowledge" in prior_item.casefold()
                else surface
            )
            continue
        target_index = _matching_skill_group(groups, link.requirement.category)
        groups[target_index][1].append(surface)
        append_count += 1
    plan.skill_groups = [(heading, _dedupe_text(items)) for heading, items in groups if items]


def _apply_headline(plan: ResumePlan, actions: list[PlacementAction]) -> None:
    terms = _dedupe_text(action.term for action in actions)[:3]
    plan.headline = f"{plan.role_identity} | {_join(terms)}" if terms else plan.role_identity


def _certificate_reference(links: list[EvidenceLink]) -> str:
    """Name the conservative source certificate without repeating tool names."""
    for link in links:
        if link.tier != "cert":
            continue
        code = re.search(r"\b[A-Z]{2,8}-\d{2,6}\b", link.resume_span)
        if code is not None:
            return f"Microsoft {code.group(0)} certification"
        if link.resume_span:
            return link.resume_span
    return "a listed certification"


def _source_role_summary(profile: Profile) -> str:
    return f"{profile.role_identities[0]}." if profile.role_identities else ""


def _with_targeting(summary: str, jd_profile: JDProfile) -> str:
    """Add the safe JD-owned target-role clause exactly once.

    A target role is job-description context, never candidate history.  It is
    therefore safe to retain even when every candidate-facing placement is
    rejected by the provenance/fidelity gates.  Keeping it in the source plan
    also preserves the established target-title quality signal for sparse or
    gap-heavy applications.
    """
    title = jd_profile.title.strip()
    if not title or title == "Target Role":
        return summary.strip()
    clean_title = title.replace("–", "-").replace("—", "-")
    clause = f"Targeting {clean_title} opportunities."
    normalized_summary = re.sub(r"\s+", " ", summary).casefold()
    if clause.casefold() in normalized_summary:
        return summary.strip()
    return " ".join(part for part in (summary.strip(), clause) if part)


def _v2_plan_decisions(
    prior: list[PlanDecision],
    plan: ResumePlan,
    profile: Profile,
    actions: list[PlacementAction],
) -> list[PlanDecision]:
    """Refresh reviewable decisions after source-preserving v2 optimization."""
    decisions = [decision for decision in prior if decision.kind not in {"summary", "targeting_clause"}]
    source_summary = profile.source_summary
    decisions.insert(
        0,
        PlanDecision(
            kind="summary",
            location_id="resume::summary",
            original_text=source_summary,
            tailored_text=plan.summary,
            operation="added" if not source_summary else "rewritten",
            reason="Added only resolver-backed terms while preserving candidate-authored summary evidence.",
            matched_keywords=[action.term for action in actions if action.target == "summary"],
        ),
    )
    by_location = {decision.location_id for decision in decisions}
    for action in actions:
        if not action.target.startswith("experience:"):
            continue
        location = _plan_bullet_location(action.target)
        if location is None:
            continue
        exp_index, bullet_index, location_id = location
        if location_id in by_location:
            continue
        if exp_index >= len(profile.experiences) or bullet_index >= len(profile.experiences[exp_index].bullets):
            continue
        if exp_index >= len(plan.experience) or bullet_index >= len(plan.experience[exp_index].bullets):
            continue
        decisions.append(
            PlanDecision(
                kind="bullet",
                location_id=location_id,
                original_text=profile.experiences[exp_index].bullets[bullet_index],
                tailored_text=plan.experience[exp_index].bullets[bullet_index],
                operation="rewritten",
                reason="Retained the source bullet after verifying a resolver-backed placement opportunity.",
                matched_keywords=[action.term],
            )
        )
        by_location.add(location_id)
    return decisions


def _plan_bullet_location(target: str) -> tuple[int, int, str] | None:
    match = re.fullmatch(r"experience:(\d+):bullet:(\d+)", target)
    if match is None:
        return None
    exp_index, bullet_index = (int(value) for value in match.groups())
    return exp_index, bullet_index, f"resume::exp{exp_index}::bullet{bullet_index}"


def _find_equivalent_skill(groups: list[tuple[str, list[str]]], link: EvidenceLink) -> tuple[int, int] | None:
    accepted = {normalize_term(value) for value in (link.requirement.canonical, *link.requirement.aliases)}
    for group_index, (_heading, items) in enumerate(groups):
        for item_index, item in enumerate(items):
            source_item = re.sub(r"\s*\(working knowledge\)\s*$", "", item, flags=re.IGNORECASE)
            if normalize_term(source_item) in accepted:
                return group_index, item_index
    return None


def _annotate_tier_c_skills(
    groups: list[tuple[str, list[str]]],
    links: list[EvidenceLink],
) -> list[tuple[str, list[str]]]:
    """Label only resolver-confirmed listed-only skills without duplicating them.

    A Tier-C link means the term appears in the candidate's skills taxonomy but
    has no stronger experience or summary evidence.  Retaining it under its
    original heading is fact-preserving; adding the parenthetical makes the
    conservative classification visible without inventing a capability or
    placing the same requirement a second time in the skills section.
    """
    locations = {
        link.resume_location for link in links if link.tier == "C" and link.resume_location.startswith("skills:")
    }
    if not locations:
        return groups

    annotated: list[tuple[str, list[str]]] = []
    for group_index, (heading, items) in enumerate(groups):
        rendered_items: list[str] = []
        for item_index, item in enumerate(items):
            location = f"skills:{group_index}:{item_index}"
            if location in locations and "working knowledge" not in item.casefold():
                rendered_items.append(f"{item} (Working Knowledge)")
            else:
                rendered_items.append(item)
        annotated.append((heading, rendered_items))
    return annotated


def _matching_skill_group(groups: list[tuple[str, list[str]]], category: str) -> int:
    category_tokens = set(category.replace("_", " ").split())
    for index, (heading, _items) in enumerate(groups):
        if category_tokens & set(normalize_term(heading).split()):
            return index
    return 0


def _gate_errors(
    plan: ResumePlan,
    profile: Profile,
    requirements: list[RequirementTerm],
    actions: list[PlacementAction],
    source: str,
) -> list[str]:
    rendered = generate_resume_text(plan)
    bullet_pairs = [
        BulletPair(original=bullet, candidate=bullet, location=f"experience:{exp_index}:bullet:{bullet_index}")
        for exp_index, experience in enumerate(profile.experiences)
        for bullet_index, bullet in enumerate(experience.bullets)
    ]
    errors = validate_resume_fidelity(source, rendered, profile=profile, bullet_pairs=bullet_pairs)
    errors.extend(
        validate_resume_stuffing(
            actions=actions,
            summary=plan.summary,
            bullets=[bullet for experience in plan.experience for bullet in experience.bullets],
            skill_groups=plan.skill_groups,
            requirements=requirements,
            source_skill_groups=profile.source_skill_groups,
            source_resume_text=source,
        )
    )
    return errors


def _score_plan(
    plan: ResumePlan,
    source: str,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
    actions: list[PlacementAction],
) -> AtsScoreV2:
    return score_resume_v2(
        generate_resume_text(plan),
        requirements,
        links,
        source_resume_text=source,
        tailored=True,
        placements=actions,
    )


def _dedupe_actions(actions: list[PlacementAction]) -> list[PlacementAction]:
    seen: set[tuple[str, str, str]] = set()
    result: list[PlacementAction] = []
    for action in actions:
        key = (normalize_term(action.term), action.target, action.operation)
        if key not in seen:
            seen.add(key)
            result.append(action)
    return result


def _dedupe_text(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        key = normalize_term(text)
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _join(values: list[str]) -> str:
    if len(values) <= 1:
        return values[0] if values else ""
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _action_label(action: PlacementAction) -> str:
    return f"{action.operation}:{action.target}:{action.term}"


__all__ = ["optimize"]
