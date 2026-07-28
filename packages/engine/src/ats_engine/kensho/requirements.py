"""Deterministic, JD-only requirement extraction for Tailoring Engine v2.

This parser intentionally does not accept a candidate profile.  A job
description describes the target role; evidence resolution later decides
whether the candidate can truthfully claim each extracted requirement.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
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
    # Without these, a heading such as "Required Technical Skills:" is treated
    # as an unknown heading, which resets the active section to "other" -- and
    # extract_requirements never mines "other".  Every skill listed underneath
    # is then silently discarded, which is how an entire GenAI requirement
    # block (LLMs, ChatGPT, Claude, Copilot, data cleaning, narrative
    # generation) vanished from a real posting.
    "required technical skills",
    "required skills",
    "technical skills",
    "technical requirements",
    "skills and qualifications",
    "required experience",
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
_SECTION_RESPONSIBILITY_HEADINGS = (
    "responsibilities",
    "key responsibilities",
    "role responsibilities",
    "what you will do",
    "what you'll do",
    "your day to day",
    "day to day",
    "duties",
    "key duties",
    "key accountabilities",
    "more specifically",
    # A common subheading under "What you will do".  Without the complete
    # phrase this line is treated as an unknown heading and resets the active
    # responsibility section, which drops ordinary bullets such as
    # "Perform root-cause analysis ..." that do not themselves contain an
    # action cue.
    "more specifically, you will",
)
_SUBSTANTIVE_RESPONSIBILITY_HEADINGS = (
    *_SECTION_RESPONSIBILITY_HEADINGS,
    # These headings establish that role content has begun for the JD hygiene
    # boundary, but their prose is not necessarily a list of scored duties.
    "the role",
    "role overview",
    "role summary",
    "position overview",
    "position summary",
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

# JD closing sections are candidate-application logistics, not role
# requirements.  We intentionally honour them as a terminal boundary only
# after a substantive role section has begun: a compensation line in a
# metadata preamble must not hide later legitimate responsibilities or
# requirements.
_QUALIFICATION_HEADINGS = (
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
    "preferred qualifications",
    "preferred qualification",
    "preferred",
    "nice to have",
    "nice-to-have",
    "assets",
    "an asset",
    "bonus qualifications",
)
_STOP_SECTION_MARKERS = (
    "application",
    "apply",
    "how to apply",
    "application process",
    "application instructions",
    "human resources",
    "hr contact",
    "recruitment",
    "recruiting",
    "salary",
    "compensation",
    "pay range",
    "benefits",
    "duration",
    "contract length",
    "term of employment",
    "closing date",
    "equal opportunity",
    "equal employment",
    "employment equity",
    "eeo",
    "references",
    "posted",
    "categories",
)
_STOP_SENTENCE_MARKERS = (
    "send a cover letter",
    "send resume",
    "send a resume",
    "applications will be accepted",
    "eligible to work",
    "only successful candidates",
    "only successful applicants",
    "base salary",
    "salary",
    "duration:",
    "references marked confidential",
    "equal opportunity",
    "equal employment",
    "accommodation",
    "posted",
    "categories:",
)
# A short leading "Label:" prefix on an otherwise substantive line.  Bounded to
# eight words so an ordinary sentence containing a colon is never mistaken for
# a formatting label, and it must be followed by real content.
_INLINE_LABEL = re.compile(r"^([A-Za-z][A-Za-z0-9 &/()+.-]{1,60}?):[ \t]+(?=\S)")

# Subjects of "The <subject> is ..." that refer to the person being hired
# rather than to the hiring organization.
# Inline announcements of the role being filled.  The captured group is the job
# TITLE, which entity extraction recovers and which must never be mined as a
# skill: a posting that says "seeking a forward-thinking Analytical BI & AI to
# lead" is naming the vacancy, not a competency the reader lacks.
INLINE_TITLE_PATTERNS = (
    re.compile(
        r"\b(?:seeking|hiring|recruiting|looking\s+for)\s+(?:an?|the)\s+"
        r"(?:[a-z]+(?:-[a-z]+)?\s+)??"
        r"(?P<title>[A-Z][A-Za-z0-9&/+.\- ]{2,60}?)\s+"
        r"(?=to\s+\w|who\b|that\b|with\b|for\b|in\s+our\b)",
    ),
    re.compile(r"\bjoin\s+us\s+as\s+(?:an?|the)\s+(?P<title>[A-Z][A-Za-z0-9&/+.\- ]{2,60}?)\s*(?=[.,]|$)"),
)

_ROLE_SUBJECT_MARKERS = (
    "candidate",
    "applicant",
    "incumbent",
    "role",
    "position",
    "successful hire",
    "person",
)

# Named standards and framework versions: "Section 508", "WCAG 2.1",
# "ISO 27001", "PL-300".  These are unambiguous, checkable requirements, and a
# candidate either meets them or does not -- so they are admitted without the
# repeat-occurrence evidence an ordinary mined token needs.
_STANDARD_RE = re.compile(
    r"\b(?:"
    r"(?P<worded>(?:Section|Chapter|Part|Level|Title)\s+\d+(?:\.\d+)*)"
    r"|(?P<acronym>[A-Z]{2,10}\s+\d+(?:\.\d+)*)"
    r"|(?P<hyphen>[A-Z]{2,6}-\d{2,4})"
    r")\b"
)

_EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![\w-])")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", flags=re.IGNORECASE)
# Require three numeric groups so a date range such as ``2022 - 2024`` is not
# mistaken for a phone contact line and removed from an otherwise valid JD.
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.-])?(?:\(?\d{2,4}\)?[\s.-]?)\d{3,4}[\s.-]\d{3,4}(?!\w)")
_ORG_ROLE_WORDS = frozenset(
    {
        "careers",
        "career",
        "portal",
        "platform",
        "department",
        "division",
        "team",
        "office",
        "program",
        "programs",
        "recruiting",
        "recruitment",
        "hiring",
        "hr",
        "talent",
        "people",
        "position",
        "role",
        "employer",
        "organization",
        "organisation",
    }
)
_TECHNICAL_NAME_WORDS = frozenset(
    {
        "access",
        "analysis",
        "analytics",
        "api",
        "application",
        "agency",
        "association",
        "authority",
        "automation",
        "bank",
        "business",
        "college",
        "cloud",
        "company",
        "consulting",
        "control",
        "data",
        "database",
        "developer",
        "development",
        "director",
        "engineering",
        "engineer",
        "governance",
        "group",
        "hospital",
        "industries",
        "institute",
        "integration",
        "management",
        "manager",
        "medical",
        "model",
        "modelling",
        "modeling",
        "power",
        "platform",
        "query",
        "reporting",
        "security",
        "service",
        "services",
        "software",
        "source",
        "system",
        "systems",
        "trust",
        "university",
        "technical",
        "technology",
        "web",
    }
)


@dataclass(frozen=True, slots=True)
class JDHygiene:
    """One deterministic, source-preserving view of a job description.

    ``scoring_lines`` are the only lines eligible to form requirements or
    legacy technical keywords. ``target_lines`` retain non-contact source
    metadata for title/company resolution. ``context_lines`` retain safe
    organization/boilerplate context without letting it enter scoring.
    """

    target_lines: tuple[str, ...]
    scoring_lines: tuple[str, ...]
    context_lines: tuple[str, ...]
    application_domains: tuple[str, ...]
    organization_names: tuple[str, ...]


def sanitize_jd_for_parsing(jd_text: str) -> JDHygiene:
    """Create the deterministic JD view shared by heuristic and LLM paths.

    Application instructions, HR/EEO, salary, duration, and similar closing
    sections frequently contain branded portal names or generic process words.
    Once substantive role content has started, they are a hard extraction
    boundary.
    Contact-bearing lines are omitted everywhere, but their email domains are
    retained as a narrow company-resolution signal.
    """
    target_lines: list[str] = []
    scoring_lines: list[str] = []
    context_lines: list[str] = []
    domains: list[str] = []
    role_content_seen = False
    stopped = False

    for raw_line in (jd_text or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        domains.extend(match.group(1).casefold().strip(".") for match in _EMAIL_RE.finditer(line))
        if _is_qualification_heading(line) or _is_responsibility_heading(line):
            role_content_seen = True
        if role_content_seen and _is_stop_section(line):
            stopped = True
        if _is_contact_line(line):
            continue
        if stopped:
            if _is_context_line(line):
                context_lines.append(line)
            continue
        target_lines.append(line)
        if _is_context_line(line):
            context_lines.append(line)
            continue
        scoring_lines.append(line)

    organization_names = _organization_names_from_lines(target_lines)
    return JDHygiene(
        target_lines=tuple(_dedupe_text(target_lines)),
        scoring_lines=tuple(_dedupe_text(scoring_lines)),
        context_lines=tuple(_dedupe_text(context_lines)),
        application_domains=tuple(_dedupe_text(domains)),
        organization_names=tuple(organization_names),
    )


def filter_hygienic_jd_values(
    values: Iterable[object],
    hygiene: JDHygiene,
    *,
    company: str = "",
    require_scoring_source: bool = True,
) -> list[str]:
    """Return LLM/heuristic values that survive the same JD hygiene boundary.

    ``require_scoring_source`` prevents model-provided terms from reintroducing
    application, organization, or fabricated text after deterministic parsing
    removed it. Title/company callers can set it to ``False`` because their
    evidence belongs to ``target_lines`` rather than scoring sections.
    """
    output: list[str] = []
    source_text = "\n".join(hygiene.scoring_lines)
    for value in values:
        text = _strip_bullet(str(value or "")).strip()
        if not text or _is_contact_line(text) or _is_stop_section(text):
            continue
        if is_person_name(text) or is_org_role_reference(text, hygiene, company=company):
            continue
        if require_scoring_source and not _text_is_in_source(text, source_text):
            continue
        if text.casefold() not in {item.casefold() for item in output}:
            output.append(text)
    return output


def _is_contact_line(line: str) -> bool:
    return bool(_EMAIL_RE.search(line) or _URL_RE.search(line) or _PHONE_RE.search(line))


def _heading_text(line: str) -> str:
    return _strip_bullet(line).casefold().strip(" :.-–—")


def _is_qualification_heading(line: str) -> bool:
    heading = _heading_text(line)
    return len(heading) <= 90 and any(
        heading == marker or heading.startswith(f"{marker}:") for marker in _QUALIFICATION_HEADINGS
    )


def _is_responsibility_heading(line: str) -> bool:
    heading = _heading_text(line)
    return len(heading) <= 90 and any(
        heading == marker or heading.startswith(f"{marker}:") for marker in _SUBSTANTIVE_RESPONSIBILITY_HEADINGS
    )


def _is_stop_section(line: str) -> bool:
    heading = _heading_text(line)
    if not heading:
        return False
    # Salary/EEO wording often appears as a sentence rather than a clean
    # heading, while generic application/HR terms must be heading-shaped to
    # avoid treating a legitimate responsibility as a terminal boundary.
    if any(marker in heading for marker in _STOP_SENTENCE_MARKERS):
        return True
    return len(heading) <= 90 and any(
        heading == marker or heading.startswith(f"{marker}:") for marker in _STOP_SECTION_MARKERS
    )


def _is_context_line(line: str) -> bool:
    heading = _heading_text(line)
    if heading.startswith("about ") or heading in {"about", "about us", "about the company", "about the role"}:
        return True
    subject_match = re.match(
        r"^the\s+(?P<subject>[A-Za-z0-9 &'.,-]{1,70}?)\s+(?:is|are|has|serves|builds|supports)\b",
        line,
        flags=re.IGNORECASE,
    )
    if subject_match is not None and not _subject_describes_the_role(subject_match.group("subject")):
        return True
    lowered = line.casefold()
    return any(marker in lowered for marker in ("careers portal", "career portal", "our platform", "our products"))


def _subject_describes_the_role(subject: str) -> bool:
    """True when ``The <subject> is ...`` describes the role, not the employer.

    The employer-context pattern above is case-insensitive, so without this
    guard it matches "The ideal candidate is a data storytelling expert and an
    early adopter of AI productivity tools" and discards the whole sentence as
    company boilerplate -- taking its requirements with it.
    """

    normalized = re.sub(r"\s+", " ", subject or "").strip().casefold()
    return any(marker in normalized for marker in _ROLE_SUBJECT_MARKERS)


def _organization_names_from_lines(lines: Iterable[str]) -> list[str]:
    names: list[str] = []
    for line in lines:
        explicit = re.match(r"^(?:company|organization|organisation|employer)\s*[:\-]\s*(.+)$", line, re.I)
        about = re.match(r"^about\s+(.+)$", line, re.I)
        seeking = re.search(
            r"\bthe\s+([A-Z][A-Za-z0-9 &'.,-]{1,70}?)\s+is\s+seeking\b",
            line,
            flags=re.IGNORECASE,
        )
        candidate = ""
        if explicit is not None:
            candidate = explicit.group(1)
        elif about is not None and about.group(1).casefold().strip() not in {"us", "the role", "the company"}:
            candidate = about.group(1)
        elif seeking is not None:
            candidate = seeking.group(1)
        cleaned = _clean_organization_name(candidate)
        if cleaned and cleaned.casefold() not in {item.casefold() for item in names}:
            names.append(cleaned)
    return names


def _clean_organization_name(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip(" -|.,:;")
    cleaned = re.sub(r"\s+(?:is|are|has|serves|builds|supports|seeking|hiring)\b.*$", "", cleaned)
    if _is_contact_line(cleaned):
        return ""
    return cleaned[:70]


def is_person_name(value: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", value)
    if len(words) not in {2, 3}:
        return False
    lowered = {word.casefold() for word in words}
    if lowered & _TECHNICAL_NAME_WORDS:
        return False
    return all(word[:1].isupper() and word[1:].islower() for word in words)


def is_org_role_reference(value: str, hygiene: JDHygiene, *, company: str = "") -> bool:
    normalized = normalize_term(value)
    words = normalized.split()
    if not words:
        return True
    if normalized in _ORG_ROLE_WORDS or (words and words[-1] in _ORG_ROLE_WORDS):
        return True
    organizations = [*hygiene.organization_names, company]
    for organization in organizations:
        org_normalized = normalize_term(organization)
        if not org_normalized:
            continue
        if normalized == org_normalized:
            return True
        if normalized.startswith(f"{org_normalized} ") and words[-1] in _ORG_ROLE_WORDS:
            return True
    return False


def _text_is_in_source(value: str, source_text: str) -> bool:
    needle = normalize_term(value)
    haystack = normalize_term(source_text)
    return bool(needle and (needle == haystack or f" {needle} " in f" {haystack} "))


def _dedupe_text(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


@dataclass(frozen=True, slots=True)
class _SectionLine:
    index: int
    text: str
    section: str
    # Character offset where an inline ``Label:`` prefix ends, or 0 when the
    # line has none.  Free-text mining starts here so that a formatting label
    # such as ``BI Frameworks:`` or ``AI Tooling Platforms:`` can never itself
    # become a requirement, while curated vocabulary is still read from the
    # whole line so a label that genuinely names a skill (``Advanced SQL:``)
    # still contributes that skill.
    label_end: int = 0

    @property
    def content(self) -> str:
        return self.text[self.label_end :]


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

    hygiene = sanitize_jd_for_parsing(jd_text)
    section_lines = _segment_sections(hygiene.scoring_lines)
    product_counts = _capitalized_product_counts(section_lines)
    candidates: list[_Candidate] = []
    for section_line in section_lines:
        if section_line.section not in {"required", "preferred", "responsibility"}:
            continue
        candidates.extend(_vocabulary_candidates(section_line))
        candidates.extend(_mined_candidates(section_line, product_counts, hygiene))
    return _to_requirements(candidates)


def _segment_sections(lines: Iterable[str]) -> list[_SectionLine]:
    active_section = "other"
    result: list[_SectionLine] = []
    for index, raw_line in enumerate(lines):
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
        stripped = _strip_bullet(line)
        result.append(
            _SectionLine(
                index=index,
                text=stripped,
                section=section,
                label_end=_inline_label_end(stripped),
            )
        )
    return result


def _inline_label_end(line: str) -> int:
    """Offset just past an inline ``Label:`` prefix, or 0 when there is none.

    Job descriptions routinely format a requirement as ``<Label>: <content>``
    (``BI Frameworks: 4+ years of advanced experience with Looker``). The label
    is presentation, not a skill, and mining it produced requirements such as
    ``BI Frameworks`` and ``AI Tooling Platforms`` -- which the product then
    displayed to the candidate as gaps they lacked.
    """

    match = _INLINE_LABEL.match(line)
    return match.end(1) + 1 if match else 0


def _heading_section(line: str) -> tuple[str | None, str]:
    cleaned = _strip_bullet(line).strip()
    lowered = cleaned.casefold().rstrip(":")
    # A preferred heading contains "qualification", so it must be recognized
    # before the broader required-heading set.
    for section, headings in (
        ("preferred", _PREFERRED_HEADINGS),
        ("required", _REQUIRED_HEADINGS),
        ("responsibility", _SECTION_RESPONSIBILITY_HEADINGS),
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


def _mined_candidates(
    section_line: _SectionLine,
    product_counts: Counter[str],
    hygiene: JDHygiene,
) -> list[_Candidate]:
    # Free-text mining reads only the content side of a "Label: content" line.
    # The label is formatting, and mining it is what turned "BI Frameworks" and
    # "AI Tooling Platforms" into requirements the user was told he lacked.
    content = section_line.content
    offset = section_line.label_end
    values: list[tuple[str, int]] = []
    values.extend((item, start + offset) for item, start in _parenthetical_items(content))
    values.extend((item, start + offset) for item, start in _cue_phrase_items(content))
    values.extend((token, match.start() + offset) for token, match in _capitalized_product_tokens_with_matches(content))

    # Standards are admitted from the whole line: a label such as
    # "Accessibility: Section 508" still names a real, checkable standard.
    standards = _standard_items(section_line.text)

    candidates: list[_Candidate] = []
    seen: set[str] = set()
    for raw_value, start in standards:
        normalized = normalize_term(raw_value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(
            _Candidate(
                canonical=normalized,
                surface=raw_value.strip(),
                aliases=(normalized,),
                kind="standard",
                section=section_line.section,
                weight={"required": 3.0, "responsibility": 2.0, "preferred": 1.0}[section_line.section],
                ngram=_ngram_length(normalized),
                category="security_governance",
                jd_evidence_line=section_line.text,
                line_index=section_line.index,
                start=start,
            )
        )

    title_spans = inline_title_spans(section_line.text)
    for raw_value, start in values:
        # A mined token lying inside an inline title announcement is the name of
        # the vacancy, not a requirement.
        if any(begin <= start < end for begin, end in title_spans):
            continue
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
        if not _is_admissible_mined_value(cleaned, section_line.text, product_counts, hygiene):
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


def inline_title_spans(line: str) -> list[tuple[int, int]]:
    """Character spans of any inline job-title announcement in *line*."""
    spans: list[tuple[int, int]] = []
    for pattern in INLINE_TITLE_PATTERNS:
        for match in pattern.finditer(line):
            spans.append((match.start("title"), match.end("title")))
    return spans


def _standard_items(line: str) -> list[tuple[str, int]]:
    """Named standards and versioned frameworks stated anywhere in *line*."""
    return [(match.group(0).strip(), match.start()) for match in _STANDARD_RE.finditer(line)]


def _parenthetical_items(line: str) -> list[tuple[str, int]]:
    """Expand a parenthetical enumeration into its individual members.

    ``Python (BeautifulSoup, Scrapy, Selenium, or Playwright)`` names four
    distinct tools, and a candidate who knows Scrapy but not Playwright matches
    the posting differently from one who knows neither. The leading
    conjunction of the final member is stripped so ``or Playwright`` becomes
    ``Playwright``.
    """

    items: list[tuple[str, int]] = []
    for match in re.finditer(r"\(([^()]{2,180})\)", line):
        content = match.group(1)
        offset = match.start(1)
        for item_match in re.finditer(r"[^,;/]+", content):
            raw = item_match.group(0)
            conjunction = re.match(r"\s*(?:or|and)\s+", raw, flags=re.IGNORECASE)
            start = item_match.start() + (conjunction.end() if conjunction else 0)
            item = raw[conjunction.end() :].strip() if conjunction else raw.strip()
            if item:
                items.append((item, offset + start))
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


def _is_admissible_mined_value(
    value: str,
    line: str,
    product_counts: Counter[str],
    hygiene: JDHygiene,
) -> bool:
    normalized = normalize_term(value)
    words = normalized.split()
    if (
        not words
        or any(word in _UNLISTED_PRODUCT_BLOCKLIST for word in words)
        or is_person_name(value)
        or is_org_role_reference(value, hygiene)
    ):
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
    ordered = _drop_standard_prefixes(ordered)
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


def _drop_standard_prefixes(candidates: list[_Candidate]) -> list[_Candidate]:
    """Remove a bare acronym that a named standard already covers.

    ``Familiarity with Section 508 and WCAG 2.1`` yields both ``wcag`` (from
    the vocabulary) and ``wcag 2 1`` (from the standards miner). They are one
    requirement, and reporting the version-less form as a second gap would
    double-count it.
    """

    standards = {candidate.canonical for candidate in candidates if candidate.kind == "standard"}
    redundant = {
        candidate.canonical
        for candidate in candidates
        if candidate.kind != "standard"
        and any(standard.startswith(f"{candidate.canonical} ") for standard in standards)
    }
    return [candidate for candidate in candidates if candidate.canonical not in redundant]


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


__all__ = [
    "JDHygiene",
    "extract_requirements",
    "filter_hygienic_jd_values",
    "is_org_role_reference",
    "is_person_name",
    "sanitize_jd_for_parsing",
]
