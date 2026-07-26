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
_EXPERIENCE_TARGET = re.compile(r"experience:(\d+):bullet:(\d+)")
_BULLET = re.compile(r"^\s*(?:[-*•])\s+(?P<text>.+)$")
_HEADLINE = re.compile(r"^\s*(?:professional\s+)?headline\s*:\s*(?P<text>.+?)\s*$", re.IGNORECASE)

# These are deliberately the headings emitted by the deterministic resume
# renderers, with a small set of common resume aliases for persisted documents
# and callers that use their own presentation layer.  A tailored score is not
# allowed to treat every trailing line as candidate-facing resume content.
_SECTION_ALIASES = {
    "professional summary": "summary",
    "summary": "summary",
    "executive summary": "summary",
    "technical skills": "skills",
    "skills": "skills",
    "core skills": "skills",
    "professional experience": "experience",
    "work experience": "experience",
    "experience": "experience",
    "employment history": "experience",
    "education": "education",
    "certifications": "certifications",
    "certificates": "certifications",
}


@dataclass(frozen=True, slots=True)
class _StructuredResume:
    """The resume regions in which a tailored phrase may earn ATS credit."""

    headline: str
    sections: dict[str, str]
    experience_bullets: dict[tuple[int, int], str]


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
    placement_actions = tuple(placements)
    measured = _without_jd_echo(resume_text, requirements) if tailored else resume_text
    source = source_resume_text or ""
    structured = _parse_structured_resume(measured) if tailored else None

    matched: list[str] = []
    missing: list[str] = []
    frequencies: dict[str, int] = {}
    matched_canonicals: set[str] = set()
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

        frequency = (
            _structured_requirement_frequency(structured, requirement)
            if structured is not None
            else _requirement_frequency(measured, requirement)
        )
        frequencies[requirement.canonical] = frequency
        evidence_supported = link is not None and link.tier in _CREDIT_TIERS
        source_present = _requirement_frequency(source, requirement) > 0
        actions_for_requirement = _actions_for_requirement(requirement, placement_actions)
        placement_supported = _has_resolved_placement(requirement, actions_for_requirement, structured)
        # Candidate source evidence can be represented by a certificate even
        # when the exact phrase is absent from the source text.  It is usable in
        # an optimized document only through an explicit provenance action.
        #
        # Do not let that action act as a blanket permission for any occurrence
        # in the rendered text: its phrase must be re-resolved in its declared
        # structured target (summary, skills, headline, or exact experience
        # bullet).  This closes the otherwise easy "append a keyword at EOF"
        # score inflation path.
        provenance_ok = not tailored or (
            placement_supported if actions_for_requirement else source_present and frequency > 0
        )
        if frequency > 0 and evidence_supported and provenance_ok:
            matched.append(requirement.surface or requirement.canonical)
            matched_canonicals.add(requirement.canonical)
            credited_weight += weight
            if is_required:
                required_matched += 1
            else:
                preferred_matched += 1
        else:
            missing.append(requirement.surface or requirement.canonical)

    base = round(100.0 * credited_weight / total_weight, 2) if total_weight else 0.0
    penalty = _density_penalty(measured, requirements, frequencies)
    bonus = (
        _structured_placement_bonus(structured, requirements, matched_canonicals)
        if structured is not None
        else _placement_bonus(measured, requirements, matched_canonicals)
    )
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


def _parse_structured_resume(text: str) -> _StructuredResume:
    """Split a rendered resume into scoreable regions.

    Only the first instance of a known section heading is scoreable.  A pasted
    second ``Technical Skills`` block at the end of a document is therefore
    not mistaken for a valid optimizer placement.  Unknown trailing text is
    kept out of every region rather than inheriting the prior section.
    """
    headline_lines: list[str] = []
    section_lines: dict[str, list[str]] = {}
    current_section: str | None = None
    saw_section = False

    for line in (text or "").splitlines():
        section = _section_for_heading(line)
        if section is not None:
            saw_section = True
            if section in section_lines:
                # A duplicate heading belongs to an unstructured append, not
                # to the original structured document.
                current_section = None
            else:
                section_lines[section] = []
                current_section = section
            continue
        if _looks_like_unknown_heading(line):
            current_section = None
            continue
        if current_section is not None:
            section_lines[current_section].append(line)
        elif not saw_section:
            headline = _HEADLINE.match(line)
            if headline is not None:
                headline_lines.append(headline.group("text"))

    sections = {name: "\n".join(lines) for name, lines in section_lines.items()}
    return _StructuredResume(
        headline="\n".join(headline_lines),
        sections=sections,
        experience_bullets=_experience_bullets(section_lines.get("experience", [])),
    )


def _section_for_heading(line: str) -> str | None:
    """Return a canonical section name when ``line`` is a standalone heading."""
    stripped = line.strip()
    if not stripped or stripped.startswith(("-", "*", "•")) or "|" in stripped:
        return None
    return _SECTION_ALIASES.get(normalize_term(stripped.rstrip(":")))


def _looks_like_unknown_heading(line: str) -> bool:
    """Recognize an appended heading without treating normal skill rows as one."""
    stripped = line.strip()
    if not stripped or stripped.startswith(("-", "*", "•")) or "|" in stripped:
        return False
    # Job-description sections such as "Required Qualifications:" are the
    # common append attack.  Skill rows retain their value after the colon and
    # are intentionally not classified as headings.
    return stripped.endswith(":")


def _experience_bullets(lines: list[str]) -> dict[tuple[int, int], str]:
    """Index deterministic renderer bullets by their placement-action target."""
    indexed: dict[tuple[int, int], str] = {}
    experience_index = -1
    bullet_index = 0
    for line in lines:
        if line.lstrip().casefold().startswith("company:"):
            experience_index += 1
            bullet_index = 0
            continue
        match = _BULLET.match(line)
        if match is None:
            continue
        if experience_index < 0:
            # This supports a conventional plain-text experience section while
            # retaining exact indexing for the deterministic renderer.
            experience_index = 0
        indexed[(experience_index, bullet_index)] = match.group("text")
        bullet_index += 1
    return indexed


def _structured_requirement_frequency(structured: _StructuredResume, requirement: RequirementTerm) -> int:
    # Evaluate aliases across the complete structured projection once.  The
    # requirement matcher intentionally picks one spelling variant rather than
    # summing aliases; applying it region-by-region would otherwise count a
    # canonical phrase in one section and a synonym in another as independent
    # occurrences.
    regions = (structured.headline, *structured.sections.values())
    return _requirement_frequency("\n".join(regions), requirement)


def _actions_for_requirement(
    requirement: RequirementTerm,
    actions: tuple[PlacementAction, ...],
) -> tuple[PlacementAction, ...]:
    canonical = normalize_term(requirement.canonical)
    return tuple(action for action in actions if normalize_term(action.link.requirement.canonical) == canonical)


def _has_resolved_placement(
    requirement: RequirementTerm,
    actions: tuple[PlacementAction, ...],
    structured: _StructuredResume | None,
) -> bool:
    if structured is None:
        return False
    for action in actions:
        target_text = _placement_target_text(structured, action.target)
        if target_text and _requirement_frequency(target_text, requirement) > 0:
            return True
    return False


def _placement_target_text(structured: _StructuredResume, target: str) -> str:
    """Return only the declared structured target for one placement action."""
    if target == "headline":
        return structured.headline
    if target in {"summary", "skills"}:
        return structured.sections.get(target, "")
    match = _EXPERIENCE_TARGET.fullmatch(target)
    if match is None:
        return ""
    experience_index, bullet_index = (int(value) for value in match.groups())
    return structured.experience_bullets.get((experience_index, bullet_index), "")


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


def _placement_bonus(
    text: str,
    requirements: list[RequirementTerm],
    matched_canonicals: set[str],
) -> float:
    """Award a small readability bonus for a term used in skills and a bullet."""
    lowered = text.casefold()
    skills_match = re.search(
        r"(?:technical\s+)?skills\s*\n(.*?)(?:\n\s*professional\s+experience|\n\s*experience)", lowered, re.S
    )
    skills = skills_match.group(1) if skills_match else ""
    bullets = "\n".join(line for line in lowered.splitlines() if line.lstrip().startswith(("-", "*", "•")))
    bonus_terms = 0
    for requirement in requirements:
        if requirement.canonical not in matched_canonicals:
            continue
        if _requirement_frequency(skills, requirement) and _requirement_frequency(bullets, requirement):
            bonus_terms += 1
    return min(5.0, float(bonus_terms))


def _structured_placement_bonus(
    structured: _StructuredResume,
    requirements: list[RequirementTerm],
    matched_canonicals: set[str],
) -> float:
    """Award the readability bonus only for validated resume regions."""
    skills = structured.sections.get("skills", "")
    bullets = "\n".join(structured.experience_bullets.values())
    bonus_terms = 0
    for requirement in requirements:
        if requirement.canonical not in matched_canonicals:
            continue
        if _requirement_frequency(skills, requirement) and _requirement_frequency(bullets, requirement):
            bonus_terms += 1
    return min(5.0, float(bonus_terms))


__all__ = ["AtsScoreV2", "score_resume_v2"]
