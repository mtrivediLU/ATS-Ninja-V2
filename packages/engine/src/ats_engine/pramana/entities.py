"""PRAMANA entity extraction: who is hiring, and for what.

Company and title resolution for a job description. Moved out of
``parsing/job_description.py`` (which still owns the broader JD-profile
assembly: required/preferred/responsibility sections, work mode, location,
domain, ATS platform, and the LLM-merge orchestration) so this package owns
its whole charter -- the Demand Model in ``requirements.py``, entity identity
here.

A wrong company is not cosmetic: it is written into the cover letter, the
outreach draft, and the filename the candidate sends to a recruiter.
"""

from __future__ import annotations

import re
from collections import Counter

from ats_engine.parsing.vocab import normalize_term, vocabulary_entry
from ats_engine.pramana.requirements import INLINE_TITLE_PATTERNS, JDHygiene, is_person_name


def _safe_llm_title(value: object, hygiene: JDHygiene) -> str:
    candidate = _clean_title(str(value or ""))
    if not _is_valid_title_candidate(candidate) or not _target_source_contains(candidate, hygiene):
        return ""
    return candidate


def _safe_llm_company(value: object, title: str, hygiene: JDHygiene) -> str:
    candidate = _trim_company(str(value or ""))
    if not _is_valid_company_candidate(candidate, title) or not _target_source_contains(candidate, hygiene):
        return ""
    return candidate


def _target_source_contains(value: str, hygiene: JDHygiene) -> bool:
    needle = normalize_term(value)
    haystack = normalize_term("\n".join(hygiene.target_lines))
    return bool(needle and (needle == haystack or f" {needle} " in f" {haystack} "))


_TITLE_ROLE_WORDS = frozenset(
    {
        "administrator",
        "analyst",
        "architect",
        "consultant",
        "coordinator",
        "developer",
        "director",
        "engineer",
        "lead",
        "manager",
        "officer",
        "scientist",
        "specialist",
        "supervisor",
    }
)
_TITLE_LOWERCASE_VERBS = (
    "analyze",
    "analyse",
    "build",
    "collaborate",
    "create",
    "deliver",
    "design",
    "develop",
    "drive",
    "ensure",
    "lead",
    "maintain",
    "manage",
    "oversee",
    "report",
    "support",
    "work",
)
_CONTACT_ROLE_TITLES = frozenset(
    {
        "hiring manager",
        "human resources",
        "recruiter",
        "talent acquisition",
    }
)


def _extract_title(text: str, lines: list[str]) -> str:
    patterns = [
        (r"(?:job title|position|role)\s*[:\-]\s*([^\n|]+)", True),
        (r"hiring\s+(?:a|an)\s+([A-Z][A-Za-z0-9 /&+#.,-]{3,70})", False),
    ]
    for pattern, explicit_label in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            candidate = _clean_title(match.group(1))
            if _is_valid_title_candidate(candidate, explicit_label=explicit_label):
                return candidate

    # A long metadata block can push the true title well down a posting. Rank
    # all standalone role-shaped headings rather than returning the first one:
    # publication/blog headings such as "Economic Development - Part-Time IT
    # Specialist" otherwise outrank the actual "IT Specialist - Economic
    # Development" role heading immediately below them.
    standalone: list[tuple[tuple[int, int, int], int, str]] = []
    for index, line in enumerate(lines[:40]):
        if ":" in line:
            continue
        candidate = _clean_title(line)
        if _is_valid_title_candidate(candidate) and not line.endswith("."):
            standalone.append((_title_candidate_rank(candidate), index, candidate))
    if standalone:
        return min(standalone)[2]
    # Government and enterprise postings often use a standalone
    # ``Role – Department`` heading immediately before the first section.
    for index, line in enumerate(lines[:40]):
        if not re.search(r"\s[-–—]\s", line) or ":" in line or len(line) > 100:
            continue
        following = " ".join(lines[index + 1 : index + 4]).casefold()
        candidate = _clean_title(line)
        if _is_valid_title_candidate(candidate) and any(
            marker in following for marker in ("responsibil", "qualification", "requirements", "what you will")
        ):
            return candidate

    # Last resort: an inline announcement such as "seeking a forward-thinking
    # Analytical BI & AI to lead our modern reporting initiatives". For some
    # postings this sentence is the only statement of the role, and without it
    # the extractor emitted the placeholder "Target Role".
    #
    # It runs last deliberately. A standalone heading is the more complete
    # statement when one exists -- a posting that heads "IT Specialist -
    # Economic Development" and then says "is seeking an IT Specialist to
    # support Economic Development programs" means the fuller heading, and
    # preferring the sentence would silently truncate the title.
    for announcement in INLINE_TITLE_PATTERNS:
        for match in announcement.finditer(text):
            candidate = _clean_title(match.group("title"))
            if _is_valid_title_candidate(candidate, announced=True):
                return candidate
    return ""


def _title_candidate_rank(candidate: str) -> tuple[int, int, int]:
    """Prefer headings whose role identity leads the phrase."""
    words = normalize_term(candidate).split()
    role_index = min(
        (index for index, word in enumerate(words) if word in _TITLE_ROLE_WORDS),
        default=len(words),
    )
    part_time_penalty = int("part time" in normalize_term(candidate))
    return role_index, part_time_penalty, len(words)


def _extract_company(
    text: str,
    lines: list[str],
    title: str,
    hygiene: JDHygiene,
    source_text: str = "",
) -> str:
    """Resolve the hiring organization, strongest source first.

    ``source_text`` is the unfiltered posting. It is needed because JD hygiene
    strips the equal-opportunity paragraph as boilerplate -- correctly, for
    scoring -- but that paragraph is frequently the only place the employer is
    named outright.
    """

    # 1. Explicit source label always wins.  ``Client Name:`` is included
    # because staffing and consultancy postings name the end client that way,
    # and ignoring it left the extractor to guess -- it picked "APIs and JSON"
    # out of a requirements bullet on a posting whose first line literally read
    # "Client Name: CrowdPlat".
    for line in lines:
        match = re.match(
            r"^(?:company|organization|organisation|employer|client\s*name|client|hiring\s+company)"
            r"\s*[:\-]\s*(.+)$",
            line,
            re.I,
        )
        if match is not None:
            candidate = _trim_company(_strip_company_qualifier(match.group(1)))
            if _is_valid_company_candidate(candidate, title, explicit_label=True):
                return candidate

    # 2. An About heading is a strong, direct organization signal.  "About the
    # role" is intentionally not a company name; look at the nearby source
    # sentence for its "The Org ..." form instead.
    about_candidate = _company_from_about_heading(lines, title)
    if about_candidate:
        return about_candidate

    # 2b. The equal-opportunity paragraph names the employer in nearly every
    # posting that has one, and it is the only place many postings state it
    # outright: "At LatentView Analytics, we value a diverse workforce".
    equal_opportunity_candidate = _company_from_equal_opportunity_clause(source_text or text, title)
    if equal_opportunity_candidate:
        return equal_opportunity_candidate

    # 3. An application domain is weaker but deterministic and useful for a
    # minimal posting that provides no company label.  Preserve source casing
    # when the same domain label appears elsewhere in the posting.
    domain_candidate = _company_from_application_domain(hygiene, lines, title)
    if domain_candidate:
        return domain_candidate

    # 4. "The Org is seeking ..." is a target-company statement, not a
    # candidate-history claim. Keep the bounded capture exact and reject role
    # phrases such as "The hiring manager is seeking".
    for match in re.finditer(
        r"\bthe\s+([A-Z][A-Za-z0-9 &'.,-]{1,70}?)\s+is\s+seeking\b",
        text,
        flags=re.IGNORECASE,
    ):
        candidate = _trim_company(match.group(1))
        if _is_valid_company_candidate(candidate, title):
            return candidate

    # 5. Last resort: a repeated proper name in source text.
    title_words = {word.lower() for word in re.findall(r"[A-Za-z]+", title)}
    repeated = _extract_repeated_proper_noun(text, title_words)
    if repeated:
        candidate = _trim_company(repeated)
        if _is_valid_company_candidate(candidate, title):
            return candidate
    return ""


def _strip_company_qualifier(value: str) -> str:
    """Drop a trailing bracketed qualifier from a labelled company name.

    ``Client Name: CrowdPlat (Internal Role)`` names CrowdPlat; the bracket is
    an engagement note, not part of the organization's name.
    """

    return re.sub(r"\s*[(\[][^)\]]{0,60}[)\]]\s*$", "", value or "").strip()


_EQUAL_OPPORTUNITY_COMPANY = (
    # "At LatentView Analytics, we value ..." / "At Acme Inc. we are an equal ..."
    re.compile(
        r"\bAt\s+(?P<company>[A-Z][A-Za-z0-9&'.\- ]{2,70}?)\s*,?\s+"
        r"(?:we|our)\b"
    ),
    # "Acme Corporation is an equal opportunity employer"
    re.compile(
        r"\b(?P<company>[A-Z][A-Za-z0-9&'.\- ]{2,70}?)\s+is\s+an\s+equal\s+"
        r"(?:opportunity|employment)\b"
    ),
)


def _company_from_equal_opportunity_clause(text: str, title: str) -> str:
    for pattern in _EQUAL_OPPORTUNITY_COMPANY:
        for match in pattern.finditer(text):
            candidate = _trim_company(match.group("company"))
            if _is_valid_company_candidate(candidate, title):
                return candidate
    return ""


def _company_from_about_heading(lines: list[str], title: str) -> str:
    for index, line in enumerate(lines):
        match = re.match(r"^about\s+(.+)$", line, re.I)
        if match is None:
            continue
        label = match.group(1).strip()
        if label.casefold() not in {"us", "the role", "the company"}:
            candidate = _trim_company(label)
            if _is_valid_company_candidate(candidate, title):
                return candidate
        for nearby in lines[index + 1 : index + 5]:
            sentence = re.search(
                r"\bthe\s+([A-Z][A-Za-z0-9 &'.,-]{1,70}?)\s+(?:is|are|has|serves|builds|supports)\b",
                nearby,
            )
            if sentence is None:
                continue
            candidate = _trim_company(sentence.group(1))
            if _is_valid_company_candidate(candidate, title):
                return candidate
    return ""


def _company_from_application_domain(hygiene: JDHygiene, lines: list[str], title: str) -> str:
    generic = {"apply", "app", "careers", "jobs", "mail", "recruiting", "talent", "www"}
    all_text = " ".join(lines)
    for domain in hygiene.application_domains:
        labels = [label for label in domain.split(".") if label and label not in generic]
        if not labels:
            continue
        root = labels[0]
        # A short application domain commonly uses the source-backed
        # organization's initials (coo.org -> Chiefs of Ontario). Resolve that
        # alias before returning the bare domain token so the source priority
        # remains domain-first without degrading the display name to "COO".
        for organization in hygiene.organization_names:
            acronym = "".join(word[0] for word in re.findall(r"[A-Za-z0-9]+", organization) if word)
            if normalize_term(acronym) == normalize_term(root):
                candidate = _trim_company(organization)
                if _is_valid_company_candidate(candidate, title):
                    return candidate
        for token in re.findall(r"[A-Za-z][A-Za-z0-9-]*", all_text):
            if normalize_term(token) == normalize_term(root):
                candidate = _trim_company(token)
                if _is_valid_company_candidate(candidate, title):
                    return candidate
        candidate = _trim_company(root.title())
        if _is_valid_company_candidate(candidate, title):
            return candidate
    return ""


def _is_valid_title_candidate(
    value: str,
    *,
    explicit_label: bool = False,
    announced: bool = False,
) -> bool:
    """Whether *value* may be used as the job title.

    ``announced`` marks a title the posting states outright ("seeking a
    forward-thinking Analytical BI & AI to lead"). Such a title is accepted
    without a recognizable role noun, because the sentence has already
    identified it as the vacancy -- requiring "engineer"/"analyst"/"manager"
    would reject real, if awkward, titles and fall back to a placeholder.
    """

    cleaned = _clean_title(value)
    words = re.findall(r"[A-Za-z]+", cleaned.casefold())
    if not cleaned or len(cleaned) > 80 or _looks_like_contact_value(cleaned):
        return False
    if normalize_term(cleaned) in _CONTACT_ROLE_TITLES and not explicit_label:
        return False
    if not words:
        return False
    if not announced and not (set(words) & _TITLE_ROLE_WORDS):
        return False
    if is_person_name(cleaned) or _title_has_unfinished_capture(cleaned):
        return False
    return True


def _is_valid_company_candidate(value: str, title: str, *, explicit_label: bool = False) -> bool:
    cleaned = _trim_company(value)
    if not cleaned or _looks_like_contact_value(cleaned) or _is_generic_company_candidate(cleaned):
        return False
    if (is_person_name(cleaned) and not explicit_label) or _title_has_unfinished_capture(cleaned):
        return False
    if normalize_term(cleaned) == normalize_term(title):
        return False
    company_key = normalize_term(cleaned)
    title_key = normalize_term(title)
    if title_key and company_key.startswith(f"{title_key} "):
        return False
    words = normalize_term(cleaned).split()
    if _company_is_role_sentence(words):
        return False
    return not (
        words
        and words[-1]
        in {
            "and",
            "at",
            "careers",
            "department",
            "for",
            "from",
            "manager",
            "of",
            "portal",
            "recruiter",
            "specialist",
            "team",
            "to",
            "with",
        }
    )


def _company_is_role_sentence(words: list[str]) -> bool:
    """Reject a role noun followed by a lowercase verb phrase."""
    for index, word in enumerate(words[:-1]):
        if word not in _TITLE_ROLE_WORDS:
            continue
        following = words[index + 1]
        if any(following.startswith(verb) for verb in _TITLE_LOWERCASE_VERBS):
            return True
    return False


def _is_generic_company_candidate(value: str) -> bool:
    """Whether an extracted employer phrase is only a boilerplate noun.

    The observed failures were not exotic: a real posting yielded the employer
    ``APIs and JSON`` (a fragment of a requirements bullet) and another yielded
    ``Generative AI``. Nobody is employed by a work mode, an employment type, a
    city, or a list of technologies, so each of those shapes is rejected
    outright rather than left to a downstream heuristic.
    """

    normalized = _ARTICLE_PREFIX.sub("", value).casefold().strip(" .,:;-")
    if normalized in {"company", "organization", "organisation", "employer"}:
        return True
    if normalized in _WORK_MODES or normalized in _EMPLOYMENT_TYPES:
        return True
    if _looks_like_bare_location(value):
        return True
    return _is_all_technology_terms(value)


# Nobody is employed by "Remote" or by "Contract".
_WORK_MODES = frozenset({"remote", "hybrid", "on-site", "onsite", "on site", "in-office", "in office"})
_EMPLOYMENT_TYPES = frozenset(
    {
        "full-time",
        "full time",
        "part-time",
        "part time",
        "contract",
        "contractor",
        "temporary",
        "permanent",
        "internship",
        "intern",
        "freelance",
        "casual",
        "seasonal",
    }
)

# "Toronto, ON" / "Sudbury, Ontario" / "Remote, Canada".
_BARE_LOCATION = re.compile(r"^[A-Z][A-Za-z.\- ]{1,40},\s*(?:[A-Z]{2}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)$")


def _looks_like_bare_location(value: str) -> bool:
    cleaned = _trim_company(value)
    if _BARE_LOCATION.match(cleaned) is None:
        return False
    # A real employer may legitimately contain a comma ("Acme, Inc."), so keep
    # anything whose tail is a corporate suffix.
    tail = cleaned.rsplit(",", 1)[-1].strip().casefold().rstrip(".")
    return tail not in _CORPORATE_SUFFIXES


_CORPORATE_SUFFIXES = frozenset(
    {"inc", "llc", "ltd", "limited", "corp", "corporation", "co", "plc", "gmbh", "sa", "nv", "ag", "pty", "llp"}
)


def _is_all_technology_terms(value: str) -> bool:
    """True when every significant word is a known technology term.

    ``APIs and JSON`` and ``Python and SQL`` are requirement fragments that a
    proper-noun heuristic mistakes for organizations.
    """

    cleaned = _trim_company(value)
    parts = [part for part in re.split(r"\s+(?:and|or|&|/)\s+|,\s*|/", cleaned) if part.strip()]
    if not parts:
        return False
    significant = [part.strip() for part in parts if normalize_term(part) not in {"", "the", "a", "an"}]
    if not significant:
        return False
    return all(vocabulary_entry(normalize_term(part)) is not None for part in significant)


_HEADING_WORDS = {
    "equity",
    "diversity",
    "inclusion",
    "requirements",
    "qualifications",
    "responsibilities",
    "education",
    "experience",
    "certifications",
    "language",
    "hybrid",
    "work",
    "model",
}


_ARTICLE_PREFIX = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)


def _extract_repeated_proper_noun(text: str, title_words: set[str] | None = None) -> str:
    """Find a company name generically: a multi-word Capitalized Phrase that
    repeats several times through the body of the posting.

    A real employer name is mentioned repeatedly ("The Acme Trust Corp has...",
    "Acme Trust Corp's role...", "...at the Acme Trust Corp"); a one-off
    section heading is not. This catches postings that never label the
    company with an explicit "Company:" field or "About <Name>" heading.
    Matching is line-scoped (space/tab only, no newline) so it never merges
    words across unrelated adjacent metadata lines; a leading article is
    stripped before counting so "The Acme Trust Corp" and "Acme Trust Corp"
    count as the same candidate instead of splitting votes with the shorter,
    more frequent but less specific "The Acme".
    """
    exclude = title_words or set()
    counts: Counter[str] = Counter()
    for match in re.finditer(r"\b(?:[A-Z][a-zA-Z.]+(?:[ \t]+(?:of|the|and))?[ \t]+){1,3}[A-Z][a-zA-Z.]+\b", text):
        phrase = re.sub(r"\s+", " ", match.group(0)).strip()
        core = _ARTICLE_PREFIX.sub("", phrase)
        words = core.split()
        if len(words) < 2 or len(phrase) > 50:
            continue
        lowered_words = {word.lower() for word in words}
        if lowered_words & _HEADING_WORDS or lowered_words <= exclude:
            continue
        counts[core] += 1
    if not counts:
        return ""
    candidate, count = counts.most_common(1)[0]
    return candidate if count >= 2 else ""


def _clean_title(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").split("|", 1)[0].strip(" -|:;")
    verbs = "|".join(_TITLE_LOWERCASE_VERBS)
    # Do not let a label capture a body clause: ``Role: IT Specialist to
    # support ...`` is a role plus a lowercase action, not a very long title.
    cleaned = re.split(rf"\s+(?:to\s+)?(?:{verbs})(?:s|ed|ing)?\b", cleaned, maxsplit=1)[0]
    cleaned = re.split(r"\s+(?:will|who|that)\s+", cleaned, maxsplit=1)[0]
    cleaned = re.sub(r"\s*(?:,|;|/)?\s*\b(?:and|or)\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|,:;")
    return cleaned[:80]


def _trim_company(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").split("|", 1)[0].strip(" -|.,:;")
    cleaned = re.split(
        r"\s+(?:is|are|has|serves|builds|supports|seeking|hiring|to\s+(?:apply|support|lead))\b",
        cleaned,
        maxsplit=1,
    )[0]
    cleaned = re.sub(r"\s*(?:,|;|/)?\s*\b(?:and|or)\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|.,:;")
    return cleaned[:70]


def _looks_like_contact_value(value: str) -> bool:
    return bool(
        "@" in value
        or re.search(r"https?://|www\.", value, flags=re.IGNORECASE)
        or re.search(
            r"(?<!\w)(?:\+?\d{1,3}[\s.-])?(?:\(?\d{2,4}\)?[\s.-]?)\d{3,4}[\s.-]\d{3,4}(?!\w)",
            value,
        )
    )


def _title_has_unfinished_capture(value: str) -> bool:
    lowered = value.casefold().strip()
    if lowered.endswith((" and", " or", " to")):
        return True
    return bool(
        re.search(
            r"\b(?:to\s+)?(?:support|lead|manage|build|develop|maintain|work|report|ensure)\b",
            value,
        )
    )
