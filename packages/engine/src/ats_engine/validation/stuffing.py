"""Scoped anti-stuffing validation for Tailoring Engine v2.

Tailoring may surface a source-supported JD requirement, but it must not turn a
resume into a keyword list.  These checks are deterministic, operate on the
structured resume sections before rendering, and are deliberately *upper
bounds*: they never force an unsupported term into a summary or bullet.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeAlias

from ats_engine.models import RequirementTerm

MAX_TERM_OCCURRENCES = 4
MAX_KEYWORD_DENSITY = 0.06
MAX_SUMMARY_REQUIREMENT_TERMS = 5
MAX_BULLET_REQUIREMENT_TERMS = 2
MAX_ADDED_SKILL_REQUIREMENTS = 6
MAX_REPEATED_BIGRAM_OCCURRENCES = 4

RequirementInput: TypeAlias = str | RequirementTerm
SkillGroups: TypeAlias = Sequence[tuple[str, Sequence[str]]]

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-/]*", flags=re.IGNORECASE)
_CONTENT_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "the",
        "to",
        "via",
        "with",
    }
)
_SHORT_CONTENT_WORDS = frozenset({"ai", "bi", "it", "ml", "ui", "ux"})


@dataclass(frozen=True, slots=True)
class StuffingReport:
    """Result of a structured resume anti-stuffing check."""

    errors: tuple[str, ...]
    term_counts: tuple[tuple[str, int], ...]
    keyword_density: float

    @property
    def is_valid(self) -> bool:
        """Whether the resume stays within every scoped placement budget."""
        return not self.errors


@dataclass(frozen=True, slots=True)
class _RequirementSpec:
    canonical: str
    variants: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RequirementMatch:
    canonical: str
    start: int
    end: int
    words: int


def analyze_resume_stuffing(
    *,
    summary: str,
    bullets: Sequence[str],
    skill_groups: SkillGroups = (),
    requirements: Sequence[RequirementInput] = (),
    source_skill_groups: SkillGroups = (),
    source_resume_text: str = "",
) -> StuffingReport:
    """Analyze explicit summary, bullet, and skill-section placement budgets.

    ``requirements`` can be V2 :class:`RequirementTerm` values or simple
    strings, which makes the validator useful during migration.  When original
    ``source_skill_groups`` are provided, existing candidate-authored skill
    repetitions establish the baseline; only additional targeted placements are
    restricted.  This avoids penalizing a resume simply for preserving its own
    source taxonomy.
    """
    specs = _requirement_specs(requirements)
    cleaned_summary = summary or ""
    cleaned_bullets = [bullet or "" for bullet in bullets]
    skill_text = _skill_text(skill_groups)
    full_text = "\n".join([cleaned_summary, *cleaned_bullets, skill_text])

    all_matches = _find_requirement_matches(full_text, specs)
    term_counts = _count_matches(all_matches)
    source_matches = _find_requirement_matches(source_resume_text, specs)
    source_term_counts = _count_matches(source_matches)
    total_words = len(_words(full_text))
    # Different grounded skills may naturally appear once each. Density is an
    # anti-repetition signal, so only occurrences after a requirement's first
    # mention contribute to the stuffing numerator.
    matched_words = _excess_match_words(all_matches)
    density = matched_words / total_words if total_words else 0.0
    source_words = len(_words(source_resume_text))
    source_density = _excess_match_words(source_matches) / source_words if source_words else 0.0
    errors: list[str] = []

    for canonical, count in sorted(term_counts.items()):
        # Source-authored repetition is not an optimizer defect and cannot be
        # repaired by deleting candidate evidence.  The ceiling therefore
        # applies to *new* repetition above the source baseline.
        allowed = max(MAX_TERM_OCCURRENCES, source_term_counts.get(canonical, 0))
        if count > allowed:
            errors.append(f"stuffing: requirement '{canonical}' appears {count} times (limit {MAX_TERM_OCCURRENCES})")
    if total_words and density > MAX_KEYWORD_DENSITY and density > source_density:
        errors.append(f"stuffing: requirement density is {density:.1%} (limit {MAX_KEYWORD_DENSITY:.0%})")

    summary_matches = _find_requirement_matches(cleaned_summary, specs)
    if len(summary_matches) > MAX_SUMMARY_REQUIREMENT_TERMS:
        errors.append(
            f"stuffing: summary uses {len(summary_matches)} targeted requirement placements "
            f"(limit {MAX_SUMMARY_REQUIREMENT_TERMS})"
        )

    for index, bullet in enumerate(cleaned_bullets):
        # Verbatim candidate bullets can legitimately mention several source
        # skills. The per-bullet budget applies to tailoring additions, never
        # to evidence the candidate already supplied.
        if source_resume_text and _contains_source_text(source_resume_text, bullet):
            continue
        bullet_matches = _find_requirement_matches(bullet, specs)
        if len(bullet_matches) > MAX_BULLET_REQUIREMENT_TERMS:
            errors.append(
                f"stuffing: bullet {index + 1} uses {len(bullet_matches)} targeted requirement placements "
                f"(limit {MAX_BULLET_REQUIREMENT_TERMS})"
            )

    errors.extend(_skill_budget_errors(skill_groups, source_skill_groups, specs))
    errors.extend(_repeated_bigram_errors(full_text, source_resume_text))

    return StuffingReport(
        errors=tuple(_dedupe(errors)),
        term_counts=tuple(sorted(term_counts.items())),
        keyword_density=density,
    )


def validate_resume_stuffing(
    rendered_resume_text: str = "",
    actions: Sequence[object] | None = None,
    *,
    summary: str = "",
    bullets: Sequence[str] = (),
    skill_groups: SkillGroups = (),
    requirements: Sequence[RequirementInput] = (),
    source_skill_groups: SkillGroups = (),
    source_resume_text: str = "",
) -> list[str]:
    """List-form entry point used by optimizer acceptance gates.

    The simple ``validate_resume_stuffing(rendered_text, actions)`` form is
    intentionally supported for final-render gates.  ``actions`` may contain
    V2 ``PlacementAction`` values (or any object exposing ``term`` or
    ``link.requirement``); their terms become the targeting vocabulary.  The
    structured keyword arguments let the optimizer additionally enforce the
    summary, per-bullet, and skills-section budgets before rendering.
    """
    action_requirements = _requirements_from_actions(actions or ())
    combined_requirements = [*requirements, *action_requirements]
    has_structured_sections = bool(summary or bullets or skill_groups)
    if rendered_resume_text and not has_structured_sections:
        return list(_analyze_rendered_text(rendered_resume_text, combined_requirements, source_resume_text).errors)
    return list(
        analyze_resume_stuffing(
            summary=summary,
            bullets=bullets,
            skill_groups=skill_groups,
            requirements=combined_requirements,
            source_skill_groups=source_skill_groups,
            source_resume_text=source_resume_text,
        ).errors
    )


def requirement_occurrences(text: str, requirements: Sequence[RequirementInput]) -> dict[str, int]:
    """Return non-overlapping canonical requirement counts for ``text``.

    Longest phrases win when requirements overlap (for example ``Power BI
    Service`` over ``Power BI``), so an ordinary phrase is never counted twice
    merely because one requirement is a prefix of another.
    """
    return _count_matches(_find_requirement_matches(text, _requirement_specs(requirements)))


def _requirement_specs(requirements: Sequence[RequirementInput]) -> tuple[_RequirementSpec, ...]:
    by_canonical: dict[str, list[str]] = {}
    for requirement in requirements:
        if isinstance(requirement, RequirementTerm):
            canonical = _normalize_phrase(requirement.canonical or requirement.surface)
            variants = [requirement.canonical, requirement.surface, *requirement.aliases]
        else:
            canonical = _normalize_phrase(requirement)
            variants = [requirement]
        if not _admissible_phrase(canonical):
            continue
        normalized_variants = [_normalize_phrase(variant) for variant in variants]
        bucket = by_canonical.setdefault(canonical, [])
        for variant in normalized_variants:
            if _admissible_phrase(variant) and variant not in bucket:
                bucket.append(variant)

    return tuple(
        _RequirementSpec(
            canonical=canonical,
            variants=tuple(sorted(variants, key=lambda value: (-len(value.split()), value))),
        )
        for canonical, variants in sorted(by_canonical.items())
    )


def _find_requirement_matches(text: str, specs: Sequence[_RequirementSpec]) -> list[_RequirementMatch]:
    normalized_text = _normalize_phrase(text)
    if not normalized_text or not specs:
        return []

    candidates: list[_RequirementMatch] = []
    for spec in specs:
        for variant in spec.variants:
            pattern = rf"(?<!\S){re.escape(variant)}(?!\S)"
            for match in re.finditer(pattern, normalized_text):
                candidates.append(
                    _RequirementMatch(
                        canonical=spec.canonical,
                        start=match.start(),
                        end=match.end(),
                        words=len(variant.split()),
                    )
                )

    selected: list[_RequirementMatch] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (item.start, -(item.end - item.start), item.canonical),
    ):
        if any(candidate.start < item.end and item.start < candidate.end for item in selected):
            continue
        selected.append(candidate)
    return selected


def _count_matches(matches: Sequence[_RequirementMatch]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in matches:
        counts[match.canonical] = counts.get(match.canonical, 0) + 1
    return counts


def _excess_match_words(matches: Sequence[_RequirementMatch]) -> int:
    occurrences: dict[str, int] = {}
    words = 0
    for match in matches:
        occurrences[match.canonical] = occurrences.get(match.canonical, 0) + 1
        # One source/bullet mention plus one skill or summary placement is a
        # deliberate v2 layout pattern, not stuffing. Further repetition is.
        if occurrences[match.canonical] > 2:
            words += match.words
    return words


def _skill_budget_errors(
    skill_groups: SkillGroups,
    source_skill_groups: SkillGroups,
    specs: Sequence[_RequirementSpec],
) -> list[str]:
    candidate_counts = _count_matches(_find_requirement_matches(_skill_text(skill_groups), specs))
    source_counts = _count_matches(_find_requirement_matches(_skill_text(source_skill_groups), specs))
    errors: list[str] = []
    added_placements = 0

    for canonical, count in sorted(candidate_counts.items()):
        baseline = source_counts.get(canonical, 0)
        allowed = max(1, baseline)
        if count > allowed:
            errors.append(
                f"stuffing: skills repeat requirement '{canonical}' {count} times "
                f"(source baseline {baseline}, limit {allowed})"
            )
        added_placements += max(0, count - baseline)

    if added_placements > MAX_ADDED_SKILL_REQUIREMENTS:
        errors.append(
            f"stuffing: skills add {added_placements} targeted requirement placements "
            f"(limit {MAX_ADDED_SKILL_REQUIREMENTS})"
        )
    return errors


def _analyze_rendered_text(
    text: str,
    requirements: Sequence[RequirementInput],
    source_resume_text: str = "",
) -> StuffingReport:
    """Run non-structural repetition checks when only rendered text is available."""
    specs = _requirement_specs(requirements)
    matches = _find_requirement_matches(text, specs)
    term_counts = _count_matches(matches)
    source_matches = _find_requirement_matches(source_resume_text, specs)
    source_counts = _count_matches(source_matches)
    total_words = len(_words(text))
    density = _excess_match_words(matches) / total_words if total_words else 0.0
    source_words = len(_words(source_resume_text))
    source_density = _excess_match_words(source_matches) / source_words if source_words else 0.0
    errors: list[str] = []
    for canonical, count in sorted(term_counts.items()):
        if count > max(MAX_TERM_OCCURRENCES, source_counts.get(canonical, 0)):
            errors.append(f"stuffing: requirement '{canonical}' appears {count} times (limit {MAX_TERM_OCCURRENCES})")
    if total_words and density > MAX_KEYWORD_DENSITY and density > source_density:
        errors.append(f"stuffing: requirement density is {density:.1%} (limit {MAX_KEYWORD_DENSITY:.0%})")
    errors.extend(_repeated_bigram_errors(text, source_resume_text))
    return StuffingReport(
        errors=tuple(_dedupe(errors)),
        term_counts=tuple(sorted(term_counts.items())),
        keyword_density=density,
    )


def _requirements_from_actions(actions: Sequence[object]) -> list[RequirementInput]:
    """Read requirement terms without coupling the validator to planner modules."""
    requirements: list[RequirementInput] = []
    for action in actions:
        term = getattr(action, "term", "")
        if isinstance(term, str) and term.strip():
            requirements.append(term)
            continue
        link = getattr(action, "link", None)
        requirement = getattr(link, "requirement", None)
        if isinstance(requirement, RequirementTerm):
            requirements.append(requirement)
    return requirements


def _repeated_bigram_errors(text: str, source_text: str = "") -> list[str]:
    counts = _bigram_counts(text)
    source_counts = _bigram_counts(source_text)
    return [
        f"stuffing: repeated content bigram '{bigram}' appears {count} times (limit {MAX_REPEATED_BIGRAM_OCCURRENCES})"
        for bigram, count in sorted(counts.items())
        # A v2 placement may legitimately repeat a branded bigram in its
        # summary and skills representation. Permit up to two such new
        # locations above source repetition; anything beyond that remains a
        # deterministic stuffing signal.
        if count > max(MAX_REPEATED_BIGRAM_OCCURRENCES, source_counts.get(bigram, 0) + 2)
    ]


def _bigram_counts(text: str) -> dict[str, int]:
    words = _words(text)
    counts: dict[str, int] = {}
    for left, right in zip(words, words[1:], strict=False):
        if not _content_word(left) or not _content_word(right):
            continue
        bigram = f"{left} {right}"
        counts[bigram] = counts.get(bigram, 0) + 1
    return counts


def _contains_source_text(source_text: str, candidate: str) -> bool:
    source = _normalize_phrase(source_text)
    needle = _normalize_phrase(candidate)
    return bool(needle and (needle == source or f" {needle} " in f" {source} "))


def _skill_text(skill_groups: SkillGroups) -> str:
    return "\n".join(item for _heading, items in skill_groups for item in items if item)


def _normalize_phrase(text: str) -> str:
    value = (text or "").casefold().replace("–", "-").replace("—", "-")
    # Keep meaningful internal dots (``node.js`` / ``v2.0``), while making a
    # sentence-ending period a true phrase boundary.
    value = re.sub(r"(?<=[a-z0-9])\.(?=\s|$)", " ", value)
    value = re.sub(r"[^a-z0-9+#.]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _admissible_phrase(value: str) -> bool:
    if not value:
        return False
    words = value.split()
    return len(words) > 1 or len(value) > 2


def _words(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").casefold())


def _content_word(word: str) -> bool:
    return word not in _CONTENT_STOP_WORDS and (len(word) > 2 or word in _SHORT_CONTENT_WORDS)


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


__all__ = [
    "MAX_ADDED_SKILL_REQUIREMENTS",
    "MAX_BULLET_REQUIREMENT_TERMS",
    "MAX_KEYWORD_DENSITY",
    "MAX_REPEATED_BIGRAM_OCCURRENCES",
    "MAX_SUMMARY_REQUIREMENT_TERMS",
    "MAX_TERM_OCCURRENCES",
    "StuffingReport",
    "analyze_resume_stuffing",
    "requirement_occurrences",
    "validate_resume_stuffing",
]
