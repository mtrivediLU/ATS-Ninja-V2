"""REORDER and SKILL_REORDER: put the relevant material first, on the record.

Both operations move existing content and nothing else. That is the whole
safety argument, and it is enforced rather than asserted in prose: every
function here returns a permutation of the indices it was given, and the
callers check exact multiset equality before and after applying one.

**Why this needed a ledger before it could exist again.**
``generation.planning._select_experience`` carries a comment explaining that
sorting bullets by keyword relevance was removed because it "silently
reordered candidate-facing content without any ledger record", and that
presence-based ATS scoring is order-insensitive, so source order was the
honest default. That reasoning is not overturned here -- it is satisfied. The
objection was to the *silence*, not to the ordering: every move below produces
a change record naming the original and new position, visible to the user and
reversible. Where a move cannot be recorded, it is not performed.

**Why order is worth changing at all**, given that PRAMANA is presence-based
and cannot see it: the reader can. A recruiter skims the first bullet of each
role, and a résumé parser that truncates or weights by position sees the top
of a section first. This is a presentation change with a presentation
rationale, which is also why it is *not* routed through the pareto objective
vector -- it moves none of those objectives by construction, and a rule that
demands one of them improve would reject every reorder on arithmetic grounds
rather than on merit. It is gated as a quality proposal instead, alongside the
headline and summary rewrites, which the optimizer already accepts at an equal
score because they are about presentation rather than keyword placement.
"""

from __future__ import annotations

from ats_engine.models import RequirementTerm
from ats_engine.validation.fidelity import contains_fact


def relevance_score(text: str, requirements: list[RequirementTerm]) -> float:
    """Total JD weight of the distinct requirements this text expresses.

    Weighted rather than counted so a role's must-have lands above three
    nice-to-haves, and distinct-counted so repeating one term cannot buy a
    position -- the same anti-stuffing stance the density metric takes.
    """
    seen: set[str] = set()
    total = 0.0
    for requirement in requirements:
        canonical = requirement.canonical
        if not canonical or canonical in seen:
            continue
        if contains_fact(text, canonical):
            seen.add(canonical)
            total += requirement.weight
    return total


def rank_by_relevance(items: list[str], requirements: list[RequirementTerm]) -> list[int]:
    """Return the source indices of *items*, most JD-relevant first.

    Stable: equal-scoring items keep their original relative order, so a
    reorder never churns content it has no reason to move. The return value is
    always a permutation of ``range(len(items))``, which is what makes the
    multiset guarantee checkable by the caller.
    """
    return sorted(range(len(items)), key=lambda index: (-relevance_score(items[index], requirements), index))


def reorder_preserving_blanks(bullets: list[str], requirements: list[RequirementTerm]) -> list[str]:
    """Rank the non-empty bullets by relevance, leaving emptied slots in place.

    An emptied slot is a bullet an accepted ``PRUNE`` removed (see
    ``rachana.pruning``); its position is load-bearing, because the change
    ledger restores a rejected removal by index. Moving only the live bullets
    among themselves keeps both mechanisms sound at once: removals stay
    restorable by position, and reordered bullets are located by content.
    """
    live = [index for index, bullet in enumerate(bullets) if bullet.strip()]
    ranked = rank_by_relevance([bullets[index] for index in live], requirements)
    reordered = list(bullets)
    for slot, pick in zip(live, ranked, strict=True):
        reordered[slot] = bullets[live[pick]]
    return reordered


def reorder_skill_items(items: list[str], requirements: list[RequirementTerm]) -> list[str]:
    """Rank one skill group's items by JD importance.

    Reorder only: never adds, removes, relabels, or rewrites an item. A
    ``(Working Knowledge)`` annotation travels with its item verbatim, because
    the item string is moved untouched -- the annotation marks tier-C evidence
    strength, and detaching or dropping it would silently promote a skill the
    candidate only listed into one they demonstrated.
    """
    return [items[index] for index in rank_by_relevance(items, requirements)]


def is_permutation(before: list[str], after: list[str]) -> bool:
    """Exact multiset equality -- the invariant every reorder must satisfy."""
    return sorted(before) == sorted(after)


__all__ = [
    "is_permutation",
    "rank_by_relevance",
    "relevance_score",
    "reorder_preserving_blanks",
    "reorder_skill_items",
]
