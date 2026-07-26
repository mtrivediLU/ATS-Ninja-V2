"""Deterministic, JD-only requirement extraction for Tailoring Engine v2.

This parser intentionally does not accept a candidate profile.  A job
description describes the target role; evidence resolution later decides
whether the candidate can truthfully claim each extracted requirement.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from ats_engine.models import RequirementTerm
from ats_engine.parsing.vocab import (
    VocabularyEntry,
    VocabularyMatch,
    find_vocabulary_matches,
    normalize_term,
    vocabulary_entry,
)

_REQUIRED_HEADINGS = (
    "required qualifications",
    "required qualification",
    "requirements",
    "qualifications",
    "what you need to succeed",
    "what we are looking for",
    "must have",
    "minimum qualifications",
    "in addition, you have",
    "in addition you have",
)
_PREFERRED_HEADINGS = (
    "preferred qualifications",
    "preferred qualification",
    "preferred",
    "nice to have",
    "nice-to-have",
    "assets",
    "an asset",
    "bonus qualifications",
)
_RESPONSIBILITY_HEADINGS = (
    "responsibilities",
    "what you will do",
    "what you'll do",
    "your day to day",
    "day to day",
    "duties",
    "key accountabilities",
    "more specifically",
    # A common subheading under "What you will do".  Without the complete
    # phrase this line is treated as an unknown heading and resets the active
    # responsibility section, which drops ordinary bullets such as
    # "Perform root-cause analysis ..." that do not themselves contain an
    # action cue.
    "more specifically, you will",
)
_BOILERPLATE_MARKERS = (
    "salary range",
    "compensation",
    "benefits",
    "pension",
    "vacation",
    "equity, diversity",
    "diversity and inclusion",
    "equal opportunity",
    "equal employment",
    "accommodation",
    "recruitment process",
    "only candidates selected",
    "how to apply",
    "apply now",
    "privacy policy",
    "background check",
)
_PREFERRED_CUES = (
    "preferred",
    "nice to have",
    "nice-to-have",
    "is an asset",
    "would be an asset",
    "considered an asset",
    "bonus",
    "familiarity with",
)
_REQUIRED_CUES = (
    "required",
    "must have",
    "must possess",
    "minimum qualification",
    "experience with",
    "proficiency in",
    "proficient in",
    "expertise in",
    "knowledge of",
    "ability to",
)
_RESPONSIBILITY_CUES = (
    "responsible for",
    "you will",
    "will be",
    "develop ",
    "design ",
    "build ",
    "maintain ",
    "support ",
    "manage ",
    "deliver ",
    "create ",
    "analyze ",
    "analyse ",
    "implement ",
)

# A phrase whose syntactic head is one of these is normally a job-description
# sentence fragment, not a technology requirement.  The list is structural
# rather than a growing patch list for each noisy posting.
_GENERIC_HEADS = {
    "ability",
    "candidate",
    "candidates",
    "concepts",
    "environment",
    "experience",
    "information",
    "knowledge",
    "opportunity",
    "portal",
    "process",
    "processes",
    "related",
    "requirement",
    "requirements",
    "role",
    "skill",
    "skills",
    "staff",
    "support",
    "system",
    "systems",
    "technical",
    "team",
    "teams",
    "work",
}
_GENERIC_TOKENS = _GENERIC_HEADS | {
    "and",
    "are",
    "business",
    "coo",
    "development",
    "economic",
    "fnbd",
    "for",
    "in",
    "of",
    "or",
    "the",
    "to",
    "with",
    "you",
}
_UNLISTED_PRODUCT_BLOCKLIST = {"coo", "fnbd", "hr", "it", "pm", "ceo", "cfo", "cto"}
_DOMAIN_HEADS = {
    "administration",
    "analysis",
    "analytics",
    "architecture",
    "automation",
    "controls",
    "design",
    "documentation",
    "engineering",
    "governance",
    "integration",
    "management",
    "modelling",
    "monitoring",
    "pipelines",
    "reporting",
    "security",
    "testing",
    "visualisation",
}


@dataclass(frozen=True, slots=True)
class _SectionLine:
    index: int
    text: str
    section: str


@dataclass(frozen=True, slots=True)
class _Candidate:
    canonical: str
    surface: str
    aliases: tuple[str, ...]
    kind: str
    section: str
    weight: float
    ngram: int
    category: str
    jd_evidence_line: str
    line_index: int
    start: int


def extract_requirements(jd_text: str) -> list[RequirementTerm]:
    """Extract typed requirements from *jd_text* without candidate input.

    The output is phrase-first and section-aware.  Generic one-word prose is
    structurally inadmissible; a unigram appears only when it is a curated
    vocabulary term or a repeated, product-shaped token in a requirement
    section.
    """

    section_lines = _segment_sections(jd_text)
    product_counts = _capitalized_product_counts(section_lines)
    candidates: list[_Candidate] = []
    for section_line in section_lines:
        if section_line.section not in {"required", "preferred", "responsibility"}:
            continue
        candidates.extend(_vocabulary_candidates(section_line))
        candidates.extend(_mined_candidates(section_line, product_counts))
    return _to_requirements(candidates)


def _segment_sections(jd_text: str) -> list[_SectionLine]:
    active_section = "other"
    result: list[_SectionLine] = []
    for index, raw_line in enumerate(jd_text.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        heading_section, inline_content = _heading_section(line)
        if heading_section is not None:
            active_section = heading_section
            if inline_content:
                result.append(_SectionLine(index=index, text=inline_content, section=active_section))
            continue
        if _is_boilerplate(line):
            active_section = "boilerplate"
            continue
        if _is_new_unknown_heading(line):
            active_section = "other"
            continue
        inferred = _infer_line_section(line)
        section = inferred if inferred != "other" else active_section
        result.append(_SectionLine(index=index, text=_strip_bullet(line), section=section))
    return result


def _heading_section(line: str) -> tuple[str | None, str]:
    cleaned = _strip_bullet(line).strip()
    lowered = cleaned.casefold().rstrip(":")
    # A preferred heading contains "qualification", so it must be recognized
    # before the broader required-heading set.
    for section, headings in (
        ("preferred", _PREFERRED_HEADINGS),
        ("required", _REQUIRED_HEADINGS),
        ("responsibility", _RESPONSIBILITY_HEADINGS),
    ):
        for heading in headings:
            if lowered == heading:
                return section, ""
            prefix = f"{heading}:"
            if cleaned.casefold().startswith(prefix):
                return section, cleaned[len(prefix) :].strip()
    return None, ""


def _is_boilerplate(line: str) -> bool:
    lowered = line.casefold()
    return any(marker in lowered for marker in _BOILERPLATE_MARKERS)


def _is_new_unknown_heading(line: str) -> bool:
    cleaned = _strip_bullet(line).strip()
    if not cleaned.endswith(":") or len(cleaned) > 90:
        return False
    return len(re.findall(r"[A-Za-z0-9]+", cleaned)) <= 8


def _infer_line_section(line: str) -> str:
    lowered = line.casefold()
    if any(cue in lowered for cue in _PREFERRED_CUES):
        return "preferred"
    if any(cue in lowered for cue in _REQUIRED_CUES):
        return "required"
    if any(cue in lowered for cue in _RESPONSIBILITY_CUES):
        return "responsibility"
    return "other"


def _strip_bullet(line: str) -> str:
    return re.sub(r"^\s*(?:[-*•‣▪]|\d+[.)])\s*", "", line).strip()


def _vocabulary_candidates(section_line: _SectionLine) -> list[_Candidate]:
    matches = _longest_non_overlapping(find_vocabulary_matches(section_line.text))
    return [_candidate_from_entry(match, section_line) for match in matches]


def _longest_non_overlapping(matches: list[VocabularyMatch]) -> list[VocabularyMatch]:
    selected: list[VocabularyMatch] = []
    occupied: list[tuple[int, int]] = []
    # Choose the longer phrase before its nested aliases, then return sources
    # in reading order.  "Power BI Service" is not emitted three times as
    # Power BI / BI / Service.
    for match in sorted(matches, key=lambda item: (-(item.end - item.start), item.start, item.entry.canonical)):
        if any(match.start < end and start < match.end for start, end in occupied):
            continue
        selected.append(match)
        occupied.append((match.start, match.end))
    return sorted(selected, key=lambda item: (item.start, item.end, item.entry.canonical))


def _candidate_from_entry(match: VocabularyMatch, section_line: _SectionLine) -> _Candidate:
    entry = match.entry
    return _Candidate(
        canonical=entry.canonical,
        surface=match.surface.strip(),
        aliases=entry.aliases,
        kind=entry.kind,
        section=section_line.section,
        weight=_weight_for(entry, section_line.section),
        ngram=_ngram_length(entry.canonical),
        category=entry.category,
        jd_evidence_line=section_line.text,
        line_index=section_line.index,
        start=match.start,
    )


def _weight_for(entry: VocabularyEntry, section: str) -> float:
    if entry.kind == "soft":
        return 0.5
    return {"required": 3.0, "responsibility": 2.0, "preferred": 1.0}[section]


def _ngram_length(value: str) -> int:
    return max(1, len(re.findall(r"[A-Za-z0-9]+", value)))


def _capitalized_product_counts(lines: list[_SectionLine]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for section_line in lines:
        if section_line.section not in {"required", "preferred", "responsibility"}:
            continue
        for token in _capitalized_product_tokens(section_line.text):
            counts[normalize_term(token)] += 1
    return counts


def _mined_candidates(section_line: _SectionLine, product_counts: Counter[str]) -> list[_Candidate]:
    values: list[tuple[str, int]] = []
    values.extend(_parenthetical_items(section_line.text))
    values.extend(_cue_phrase_items(section_line.text))
    values.extend(
        (token, match.start()) for token, match in _capitalized_product_tokens_with_matches(section_line.text)
    )

    candidates: list[_Candidate] = []
    seen: set[str] = set()
    for raw_value, start in values:
        cleaned = _clean_mined_value(raw_value)
        normalized = normalize_term(cleaned)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        entry = vocabulary_entry(normalized)
        # Vocabulary values were already harvested with source spans.  Do not
        # create a second, lower-quality mined representation of the same term.
        if entry is not None or find_vocabulary_matches(cleaned):
            continue
        if not _is_admissible_mined_value(cleaned, section_line.text, product_counts):
            continue
        candidates.append(
            _Candidate(
                canonical=normalized,
                surface=cleaned,
                aliases=(normalized,),
                kind=_mined_kind(cleaned),
                section=section_line.section,
                weight={"required": 3.0, "responsibility": 2.0, "preferred": 1.0}[section_line.section],
                ngram=_ngram_length(normalized),
                category=_mined_category(normalized),
                jd_evidence_line=section_line.text,
                line_index=section_line.index,
                start=start,
            )
        )
    return candidates


def _parenthetical_items(line: str) -> list[tuple[str, int]]:
    items: list[tuple[str, int]] = []
    for match in re.finditer(r"\(([^()]{2,180})\)", line):
        content = match.group(1)
        offset = match.start(1)
        for item_match in re.finditer(r"[^,;/]+", content):
            item = item_match.group(0).strip()
            if item:
                items.append((item, offset + item_match.start()))
    return items


def _cue_phrase_items(line: str) -> list[tuple[str, int]]:
    items: list[tuple[str, int]] = []
    pattern = re.compile(
        r"\b(?:experience|proficiency|expertise|knowledge|familiarity|working knowledge)\s+"
        r"(?:with|in|of)\s+([^.;:]{2,160})",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(line):
        content = match.group(1)
        offset = match.start(1)
        # Split enumerations while retaining normal multi-word phrases.
        for item_match in re.finditer(r"[^,;]+", content):
            item = re.split(r"\s+(?:and|or)\s+", item_match.group(0), maxsplit=1, flags=re.IGNORECASE)[0].strip()
            if item:
                items.append((item, offset + item_match.start()))
    return items


def _capitalized_product_tokens_with_matches(line: str) -> list[tuple[str, re.Match[str]]]:
    pattern = re.compile(r"\b(?:[A-Z]{3,}|[A-Z][A-Za-z0-9]+(?:[- ][A-Z][A-Za-z0-9]+)+)\b")
    return [(match.group(0), match) for match in pattern.finditer(line)]


def _capitalized_product_tokens(line: str) -> list[str]:
    return [token for token, _match in _capitalized_product_tokens_with_matches(line)]


def _clean_mined_value(value: str) -> str:
    cleaned = re.sub(r"\b(?:and|or)\b.*$", "", value, flags=re.IGNORECASE).strip(" -–—,:;()")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _is_admissible_mined_value(value: str, line: str, product_counts: Counter[str]) -> bool:
    normalized = normalize_term(value)
    words = normalized.split()
    if not words or any(word in _UNLISTED_PRODUCT_BLOCKLIST for word in words):
        return False
    if len(words) == 1:
        compact = words[0]
        # An unlisted singleton must look like an actual product and repeat in
        # JD requirement text.  This prevents organization abbreviations and
        # ordinary prose from becoming career gaps.
        return (
            len(compact) >= 3
            and compact not in _GENERIC_TOKENS
            and product_counts[normalized] >= 2
            and (value.isupper() or "-" in value or any(character.isdigit() for character in value))
        )
    if len(words) > 4 or words[-1] in _GENERIC_HEADS:
        return False
    if all(word in _GENERIC_TOKENS for word in words):
        return False
    has_domain_head = any(word in _DOMAIN_HEADS for word in words)
    has_product_shape = any(character.isupper() for character in value[1:]) or "-" in value
    if not has_domain_head and not has_product_shape:
        return False
    # A noun phrase needs a requirement cue or punctuation that indicates it
    # came from a list.  This avoids lifting prose from marketing paragraphs.
    lowered_line = line.casefold()
    return any(cue in lowered_line for cue in _REQUIRED_CUES + _PREFERRED_CUES) or "," in line or ";" in line


def _mined_kind(value: str) -> str:
    return "tool" if value.isupper() or "-" in value or any(character.isdigit() for character in value) else "skill"


def _mined_category(normalized: str) -> str:
    words = set(normalized.split())
    if words & {"data", "pipeline", "pipelines", "etl", "warehouse"}:
        return "data_engineering"
    if words & {"security", "audit", "access", "governance"}:
        return "security_governance"
    if words & {"map", "mapping", "geospatial", "geocode", "geocoding"}:
        return "geospatial"
    if words & {"api", "integration", "integrations"}:
        return "integration"
    return "platform"


def _to_requirements(candidates: list[_Candidate]) -> list[RequirementTerm]:
    selected: dict[str, _Candidate] = {}
    for candidate in candidates:
        existing = selected.get(candidate.canonical)
        if existing is None or _candidate_precedes(candidate, existing):
            selected[candidate.canonical] = candidate

    ordered = sorted(
        selected.values(),
        key=lambda candidate: (-candidate.weight, candidate.line_index, candidate.start, candidate.canonical),
    )
    capped = _cap_soft_weight(ordered)
    return [
        RequirementTerm(
            canonical=candidate.canonical,
            surface=candidate.surface,
            aliases=candidate.aliases,
            kind=candidate.kind,
            section=candidate.section,
            weight=candidate.weight,
            ngram=candidate.ngram,
            category=candidate.category,
            jd_evidence_line=candidate.jd_evidence_line,
        )
        for candidate in capped
    ]


def _candidate_precedes(candidate: _Candidate, existing: _Candidate) -> bool:
    if candidate.weight != existing.weight:
        return candidate.weight > existing.weight
    section_rank = {"required": 3, "responsibility": 2, "preferred": 1}
    if section_rank[candidate.section] != section_rank[existing.section]:
        return section_rank[candidate.section] > section_rank[existing.section]
    return (candidate.line_index, candidate.start, candidate.surface.casefold()) < (
        existing.line_index,
        existing.start,
        existing.surface.casefold(),
    )


def _cap_soft_weight(candidates: list[_Candidate]) -> list[_Candidate]:
    hard = [candidate for candidate in candidates if candidate.kind != "soft"]
    soft = [candidate for candidate in candidates if candidate.kind == "soft"]
    if not hard:
        return []
    accepted_soft: list[_Candidate] = []
    hard_weight = sum(candidate.weight for candidate in hard)
    soft_weight = 0.0
    for candidate in soft:
        prospective = soft_weight + candidate.weight
        if prospective / (hard_weight + prospective) <= 0.15:
            accepted_soft.append(candidate)
            soft_weight = prospective
    return sorted(
        [*hard, *accepted_soft],
        key=lambda candidate: (-candidate.weight, candidate.line_index, candidate.start, candidate.canonical),
    )


__all__ = ["extract_requirements"]
