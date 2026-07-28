"""PRAMANA -- the evidence-grounded, fractional, saturating ATS score.

For each requirement, credit is a *fractional*, *saturating* function of how
often it is stated relative to how often the job description itself asks for
it (``target``) -- not a boolean present-or-absent flag. A JD that says "AI"
nine times does not require nine resume mentions to earn full credit for it;
three does. A term stuffed far beyond that is penalized, not rewarded.

The scorer does not discover requirements, infer evidence, or reward
arbitrary text copied from a job description; those responsibilities belong
to the requirement extractor (``pramana/requirements.py``) and the evidence
resolver. It merely combines their typed inputs with a rendered resume.

The provenance gate below is the single most load-bearing piece of this
module. For a tailored resume, a phrase absent from the candidate's own
source text earns credit only if an accepted placement action resolves inside
its declared structured target (headline, summary, skills, or an exact
experience bullet) -- never merely "found somewhere in the rendered text".
Implementing the target/supply/presence formula without this gate would
silently reopen the "paste the JD at the bottom of the resume" scoring
exploit this module exists to prevent.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from ats_engine.models import EvidenceLink, PlacementAction, RequirementTerm
from ats_engine.parsing.vocab import normalize_term
from ats_engine.pramana.contract import PramanaScore, RequirementCredit

# Forward-compatible, matching this codebase's existing convention (ats_v2's
# own _CREDIT_TIERS already included the never-produced "variant"): "bridged"
# and "declared" are not yet assigned by evidence/resolver.py anywhere (they
# are RACHANA §3.5/§3.9 features, not yet built), but the literal spec set is
# implemented as specified rather than narrowed to only what exists today.
_GROUNDED_TIERS = frozenset({"A", "B", "C", "cert", "variant", "bridged", "declared"})

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

# A JD title this generic carries no real alignment signal to credit.
_GENERIC_TITLES = frozenset({"", "target role"})
# Words too short or too common to count as a meaningful title-overlap signal.
_TITLE_STOPWORDS = frozenset({"the", "and", "for", "with", "our", "your"})


@dataclass(frozen=True, slots=True)
class _StructuredResume:
    """The resume regions in which a tailored phrase may earn ATS credit."""

    headline: str
    sections: dict[str, str]
    experience_bullets: dict[tuple[int, int], str]


def score_resume(
    resume_text: str,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
    *,
    source_resume_text: str = "",
    tailored: bool = False,
    placements: Iterable[PlacementAction] = (),
    jd_title: str = "",
    parse_confidence: float = 1.0,
) -> PramanaScore:
    """Score a resume only for JD requirements with source-backed evidence.

    ``jd_title`` and ``parse_confidence`` are optional: a caller without JD
    metadata gets no title-alignment bonus and no confidence penalty, rather
    than a forced default that would otherwise punish or reward a score that
    has no such signal available.
    """
    if not requirements:
        return PramanaScore(
            score=0.0,
            keyword_score=0.0,
            title_alignment=0.0,
            placement_bonus=0.0,
            stuffing_penalty=0.0,
            confidence=_confidence_bucket(parse_confidence),
            required_coverage=1.0,
            preferred_coverage=1.0,
            explanation=["No hygienic requirements were available to score against."],
        )

    links_by_canonical = {link.requirement.canonical: link for link in links}
    placement_actions = tuple(placements)
    measured = _without_jd_echo(resume_text, requirements) if tailored else (resume_text or "")
    source = source_resume_text or ""
    # Structured parsing runs unconditionally -- not only when tailored -- so
    # title_alignment and the placement bonus can credit a base/original
    # resume's own headline and skills section too, not only a tailored one.
    # Per-requirement CREDIT still uses the original tailored-vs-original
    # frequency method unchanged below.
    structured = _parse_structured_resume(measured)

    per_requirement: list[RequirementCredit] = []
    credited_weight = 0.0
    total_weight = 0.0
    required_matched = required_total = preferred_matched = preferred_total = 0
    unreachable_gaps: list[str] = []
    declared_gaps: list[str] = []
    matched_canonicals: set[str] = set()

    for requirement in requirements:
        link = links_by_canonical.get(requirement.canonical)
        tier = link.tier if link is not None else "missing"
        weight = max(0.0, requirement.weight)
        total_weight += weight
        is_required = requirement.section in {"required", "responsibility"} or requirement.weight >= 2.0
        if is_required:
            required_total += 1
        else:
            preferred_total += 1

        frequency = (
            _structured_requirement_frequency(structured, requirement)
            if tailored
            else _requirement_frequency(measured, requirement)
        )
        actions_for_requirement = _actions_for_requirement(requirement, placement_actions)
        placement_supported = _has_resolved_placement(requirement, actions_for_requirement, structured)
        source_present = _requirement_frequency(source, requirement) > 0
        # Candidate source evidence can be represented by a certificate even
        # when the exact phrase is absent from the source text. It is usable
        # in an optimized document only through an explicit provenance action.
        #
        # Do not let that action act as a blanket permission for any
        # occurrence in the rendered text: its phrase must be re-resolved in
        # its declared structured target (summary, skills, headline, or exact
        # experience bullet). This closes the otherwise easy "append a
        # keyword at EOF" score inflation path -- the reason ``presence``
        # below is gated to zero rather than computed from raw frequency.
        provenance_ok = not tailored or (
            placement_supported if actions_for_requirement else source_present and frequency > 0
        )

        target = min(3, max(1, requirement.jd_occurrences))
        presence = min(frequency / target, 1.0) if provenance_ok else 0.0
        grounded = tier in _GROUNDED_TIERS
        credit = presence if grounded else 0.0

        per_requirement.append(
            RequirementCredit(requirement=requirement, target=target, supply=frequency, tier=tier, credit=credit)
        )
        credited_weight += weight * credit
        if credit > 0:
            matched_canonicals.add(requirement.canonical)
            if is_required:
                required_matched += 1
            else:
                preferred_matched += 1
        if tier == "missing":
            unreachable_gaps.append(requirement.surface or requirement.canonical)
        elif tier == "declared":
            declared_gaps.append(requirement.surface or requirement.canonical)

    keyword_score = round(100.0 * credited_weight / total_weight, 2) if total_weight else 0.0
    title_alignment = _title_alignment_bonus(jd_title, structured)
    placement_bonus = _placement_bonus(structured, requirements, matched_canonicals)
    stuffing_penalty = _stuffing_penalty(measured, per_requirement)
    confidence_penalty = round((1.0 - max(0.0, min(1.0, parse_confidence))) * 5.0, 2)

    score = round(
        max(
            0.0,
            min(100.0, keyword_score + title_alignment + placement_bonus - stuffing_penalty - confidence_penalty),
        ),
        2,
    )
    required_coverage = round(required_matched / required_total, 4) if required_total else 1.0
    preferred_coverage = round(preferred_matched / preferred_total, 4) if preferred_total else 1.0

    explanation = _build_explanation(
        keyword_score=keyword_score,
        title_alignment=title_alignment,
        placement_bonus=placement_bonus,
        stuffing_penalty=stuffing_penalty,
        confidence_penalty=confidence_penalty,
        required_matched=required_matched,
        required_total=required_total,
        preferred_matched=preferred_matched,
        preferred_total=preferred_total,
    )

    return PramanaScore(
        score=score,
        keyword_score=keyword_score,
        title_alignment=title_alignment,
        placement_bonus=placement_bonus,
        stuffing_penalty=stuffing_penalty,
        confidence=_confidence_bucket(parse_confidence),
        required_coverage=required_coverage,
        preferred_coverage=preferred_coverage,
        per_requirement=per_requirement,
        unreachable_gaps=unreachable_gaps,
        declared_gaps=declared_gaps,
        explanation=explanation,
    )


def _confidence_bucket(parse_confidence: float) -> str:
    if parse_confidence >= 0.8:
        return "high"
    if parse_confidence >= 0.5:
        return "medium"
    return "low"


def _build_explanation(
    *,
    keyword_score: float,
    title_alignment: float,
    placement_bonus: float,
    stuffing_penalty: float,
    confidence_penalty: float,
    required_matched: int,
    required_total: int,
    preferred_matched: int,
    preferred_total: int,
) -> list[str]:
    lines = [
        f"Keyword match: {keyword_score:.1f}/100 "
        f"({required_matched}/{required_total} required, {preferred_matched}/{preferred_total} preferred/other)."
    ]
    if title_alignment > 0:
        lines.append(f"Headline or summary aligns with the target role (+{title_alignment:.1f}).")
    if placement_bonus > 0:
        lines.append(
            f"{int(placement_bonus)} requirement(s) reinforced in both skills and an experience bullet "
            f"(+{placement_bonus:.1f})."
        )
    if stuffing_penalty > 0:
        lines.append(f"Keyword stuffing detected in one or more terms (-{stuffing_penalty:.1f}).")
    if confidence_penalty > 0:
        lines.append(f"Low job-description parse confidence reduced the score (-{confidence_penalty:.1f}).")
    return lines


def _title_alignment_bonus(jd_title: str, structured: _StructuredResume) -> float:
    """0..8: does the candidate's own headline/summary carry the JD's title?

    A deterministic proxy for "semantically matching the JD title" -- this
    engine is deterministic-first and has no embedding model to consult. Full
    (normalized) title match earns the full bonus; partial overlap on the
    title's significant words earns a proportional partial bonus; no overlap
    earns nothing.
    """
    normalized_title = normalize_term(jd_title or "")
    if normalized_title in _GENERIC_TITLES:
        return 0.0
    haystack = normalize_term(f"{structured.headline} {structured.sections.get('summary', '')}")
    if not haystack:
        return 0.0
    if normalized_title in haystack:
        return 8.0
    title_words = {word for word in normalized_title.split() if len(word) > 3 and word not in _TITLE_STOPWORDS}
    if not title_words:
        return 0.0
    overlap = title_words & set(haystack.split())
    if not overlap:
        return 0.0
    fraction = len(overlap) / len(title_words)
    return round(2.0 + fraction * 4.0, 2)


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
    for form in _forms(requirement):
        normalized = normalize_term(form)
        if not normalized:
            continue
        pattern = rf"(?<![\w+#.]){re.escape(normalized)}(?![\w+#.])"
        count = len(re.findall(pattern, normalized_text))
        if count:
            # Aliases are alternate spellings, never independent keywords.
            return count
    return 0


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


def _stuffing_penalty(text: str, credits: list[RequirementCredit]) -> float:
    """0..-10, expressed here as a positive magnitude the caller subtracts.

    Applies to every hygienic requirement, grounded or not: stuffing an
    *unsupported* term (repeating an unsubstantiated "Kubernetes" a dozen
    times) is if anything more suspicious than stuffing a grounded one, not
    exempt from it. Per requirement: supply beyond 4x its own target is
    penalized proportionally; a requirement whose own occurrences alone
    exceed 6% of the document's total words adds a further flat penalty.
    Capped at 10.0 total, matching the spec's declared range.
    """
    words = max(1, len(_WORD.findall(text or "")))
    penalty = 0.0
    for credit in credits:
        allowed = 4 * credit.target
        if credit.supply > allowed:
            penalty += float(credit.supply - allowed) * 2.0
        if credit.supply / words > 0.06:
            penalty += 2.0
    return min(10.0, penalty)


def _placement_bonus(
    structured: _StructuredResume,
    requirements: list[RequirementTerm],
    matched_canonicals: set[str],
) -> float:
    """0..4: award a small readability bonus for a term used in skills and a bullet."""
    skills = structured.sections.get("skills", "")
    bullets = "\n".join(structured.experience_bullets.values())
    bonus_terms = 0
    for requirement in requirements:
        if requirement.canonical not in matched_canonicals:
            continue
        if _requirement_frequency(skills, requirement) and _requirement_frequency(bullets, requirement):
            bonus_terms += 1
    return min(4.0, float(bonus_terms))


__all__ = ["PramanaScore", "RequirementCredit", "score_resume"]
