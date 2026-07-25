from __future__ import annotations

from collections.abc import Iterable

from ats_engine.kit.contract import JobPriorityItem
from ats_engine.models import EvidenceItem

"""Deterministic "what matters most for this job" themes.

The results-first Application Kit page needs a small set of natural-language
bullets describing what the employer is asking for, distinct from what the
candidate has (see the strengths/gaps split elsewhere). This module distills
the job description's own evidence matrix into 4-6 short themes, ranked so
required-qualification categories surface before preferred-only ones.

Deterministic and JD-only: it reads only ``EvidenceItem.category`` /
``.keyword`` / ``.required_or_preferred`` (never ``real_evidence``, which is
candidate-specific), so the output never depends on candidate identity, wording,
or evidence — the same JD always produces the same priorities regardless of who
the resume belongs to.
"""

MIN_PRIORITIES = 4
MAX_PRIORITIES = 6

# Human-readable labels for the evidence matrix's coarse requirement categories
# (see ``ats_engine.evidence.matrix.classify_requirement_category``). A category
# with no evidence-backed presence in this JD simply never produces a theme.
_CATEGORY_LABELS: dict[str, str] = {
    "platform": "Platform and automation experience",
    "web development": "Web development",
    "integration": "APIs and system integration",
    "cloud": "Cloud and DevOps",
    "database": "Databases and data",
    "framework": "Framework experience",
    "programming language": "Programming languages",
    "source control": "Source control practices",
    "business analysis": "Business analysis and stakeholder work",
    "operations and support": "Operations and production support",
    "documentation": "Documentation",
    "communication": "Communication and collaboration",
    "work conditions": "Work arrangement",
}


def build_job_priorities(evidence: list[EvidenceItem]) -> list[JobPriorityItem]:
    """Return up to :data:`MAX_PRIORITIES` deterministic job-priority themes.

    Groups the evidence matrix (already required-first, stable JD order) by its
    coarse requirement category; a category with at least one required keyword
    ranks ahead of an all-preferred category, ties broken by first discovery
    order. A keyword outside every coarse category becomes its own single-
    keyword theme rather than being folded into a vague catch-all. Never
    fabricates a theme to reach the minimum: a JD with fewer distinct groups
    simply returns fewer.
    """
    groups: dict[str, list[EvidenceItem]] = {}
    order: list[str] = []
    for item in evidence:
        key = item.category if item.category != "other" else f"__keyword__{item.keyword.casefold().strip()}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    def _rank(key: str) -> tuple[int, int]:
        has_required = any(entry.required_or_preferred == "required" for entry in groups[key])
        return (0 if has_required else 1, order.index(key))

    priorities: list[JobPriorityItem] = []
    for key in sorted(order, key=_rank):
        if len(priorities) >= MAX_PRIORITIES:
            break
        priority = _priority_for_group(key, groups[key])
        if priority is not None:
            priorities.append(priority)
    return priorities


def _priority_for_group(key: str, items: list[EvidenceItem]) -> JobPriorityItem | None:
    is_required = any(entry.required_or_preferred == "required" for entry in items)
    qualifier = "a required qualification" if is_required else "a preferred qualification"

    if key.startswith("__keyword__"):
        keyword = items[0].keyword.strip()
        if not keyword:
            return None
        theme = keyword[:1].upper() + keyword[1:]
        return JobPriorityItem(theme=theme, detail=f"This role lists {keyword} as {qualifier}.")

    label = _CATEGORY_LABELS.get(key)
    if label is None:
        return None
    terms = _unique_terms(entry.keyword for entry in items)
    if not terms:
        return None
    return JobPriorityItem(theme=label, detail=f"This role calls for {_join_terms(terms)} experience.")


def _unique_terms(terms: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        key = term.casefold().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(term.strip())
    return unique


def _join_terms(terms: list[str], limit: int = 3) -> str:
    trimmed = terms[:limit]
    if len(trimmed) == 1:
        return trimmed[0]
    if len(trimmed) == 2:
        return f"{trimmed[0]} and {trimmed[1]}"
    return f"{', '.join(trimmed[:-1])}, and {trimmed[-1]}"


__all__ = ["MAX_PRIORITIES", "MIN_PRIORITIES", "build_job_priorities"]
