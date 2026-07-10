from __future__ import annotations

import re

from ats_engine.models import Profile

"""Truth-grounding claim validator — the core anti-fabrication gate.

Every check compares generated output against what the candidate's own uploaded
resume (``profile.raw_markdown`` and parsed structure) actually says. Content
the candidate wrote themselves is supported by definition; only claims with no
trace in the source are flagged. The job description is a *targeting* source,
never candidate evidence, so metrics/employers/emails must come from the resume.
"""

PRODUCTION_WORDS = {"production", "owned", "built", "shipped", "launched", "deployed"}
NON_EMPLOYER_HEADINGS = {
    "selected experience",
    "professional experience",
    "work experience",
    "experience",
    "projects",
    "employment history",
}

# High-risk factual tokens that must be traceable to the uploaded resume:
# percentages, money, counted nouns (users/customers/etc), and team sizes.
HIGH_RISK_METRIC_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*%"
    r"|\$\s*\d[\d,.]*\s*(?:[kKmMbB]\b|million|billion|thousand)?"
    r"|\b\d[\d,]*\+?\s+(?:users?|customers?|clients?|engineers?|people|employees|platforms?|stores?|sites?|countries|launches)\b"
    r"|\bteam\s+of\s+\d+\b"
    r"|\b(?:millions?|billions?|thousands?|hundreds?)\s+of\s+\w+",
    flags=re.IGNORECASE,
)


def validate_claims(text: str, profile: Profile) -> list[str]:
    """Validate generated output against the candidate's own resume evidence."""
    errors: list[str] = []
    comparable = _latex_unescape(text)
    lowered = comparable.lower()
    evidence = _normalize(profile.raw_markdown)
    bullet_evidence = _normalize(
        " ".join(bullet for experience in profile.experiences for bullet in experience.bullets)
    )

    for email in profile.retired_emails:
        if email.lower() in lowered:
            errors.append(f"retired email used: {email}")

    errors.extend(_validate_emails(comparable, profile, evidence))
    errors.extend(_validate_high_risk_metrics(comparable, evidence))

    experience_text = _section_between(comparable, "Professional Experience", "Education")
    experience_lowered = _normalize(experience_text)
    for term, display in profile.tier_c.items():
        if len(term) < 3:
            continue
        if _term_in(term, experience_lowered) and not _term_in(term, bullet_evidence):
            errors.append(f"Tier C term in experience bullets: {display}")

    for term in list(profile.tier_b) + list(profile.tier_c):
        if len(term) < 3 or _term_in(term, bullet_evidence):
            continue
        if _term_in(term, experience_lowered) and _near_production_claim(experience_lowered, term):
            errors.append(f"unsupported production ownership claim for {term}")

    if "\\resumeSubheading" in text or "Professional Experience" in text:
        errors.extend(_validate_official_titles(comparable, profile))
        errors.extend(_validate_known_companies(text, profile))
    return _dedupe(errors)


def _validate_high_risk_metrics(text: str, evidence: str) -> list[str]:
    """Flag any percentage, dollar amount, count, or team size absent from the resume."""
    errors: list[str] = []
    for match in HIGH_RISK_METRIC_PATTERN.finditer(text):
        metric = _normalize(match.group(0))
        if metric and metric not in evidence:
            errors.append(f"unsupported metric: {match.group(0).strip()}")
    return errors


def _validate_emails(text: str, profile: Profile, evidence: str) -> list[str]:
    allowed = {profile.contact.email.lower()} if profile.contact.email else set()
    errors: list[str] = []
    for email in re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text):
        normalized = email.lower()
        if normalized in allowed or normalized in evidence:
            continue
        errors.append(f"email not present in resume: {email}")
    return errors


def _near_production_claim(text: str, term: str) -> bool:
    pattern = rf"(?:{'|'.join(PRODUCTION_WORDS)}).{{0,60}}{re.escape(term)}|{re.escape(term)}.{{0,60}}(?:{'|'.join(PRODUCTION_WORDS)})"
    return bool(re.search(pattern, text))


def _validate_official_titles(text: str, profile: Profile) -> list[str]:
    errors: list[str] = []
    experience_text = _section_between(text, "Professional Experience", "Education") or text
    official_titles = {
        _normalize(experience.company): experience.title
        for experience in profile.experiences
        if experience.company and experience.title
    }
    for company, _location, title, dates in _iter_resume_subheadings(experience_text):
        normalized_company = _normalize(company)
        if _is_non_employer_heading(normalized_company):
            continue
        if not _looks_like_experience_row(company, title, dates):
            continue
        expected_title = official_titles.get(normalized_company)
        if expected_title and expected_title != title:
            errors.append(f"official title altered for {company}")
    return errors


def _validate_known_companies(text: str, profile: Profile) -> list[str]:
    errors: list[str] = []
    allowed = [_normalize(company) for company in profile.allowed_companies if company]
    experience_text = _section_between(text, "Professional Experience", "Education") or text
    for company, _location, title, dates in _iter_resume_subheadings(experience_text):
        normalized_company = _normalize(company)
        if _is_non_employer_heading(normalized_company):
            continue
        if not _looks_like_experience_row(company, title, dates):
            continue
        company = normalized_company
        if not company:
            continue
        if not any(company in known or known in company for known in allowed):
            errors.append(f"invented or unsupported employer: {company}")
    return errors


def _iter_resume_subheadings(text: str) -> list[tuple[str, str, str, str]]:
    """Return parsed company/location/title/date fields from resumeSubheading calls."""
    rows: list[tuple[str, str, str, str]] = []
    command = r"\resumeSubheading"
    index = 0
    while True:
        start = text.find(command, index)
        if start == -1:
            break
        args, end = _read_brace_args(text, start + len(command), expected=4)
        if len(args) == 4:
            rows.append((args[0], args[1], args[2], args[3]))
        index = end if end > start else start + len(command)
    return [tuple(_clean_latex_field(field) for field in row) for row in rows]  # type: ignore[misc]


def _read_brace_args(text: str, start: int, expected: int) -> tuple[list[str], int]:
    args: list[str] = []
    index = start
    while len(args) < expected and index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text) or text[index] != "{":
            break
        end = _matching_brace(text, index)
        if end == -1:
            break
        args.append(text[index + 1 : end])
        index = end + 1
    return args, index


def _matching_brace(text: str, start: int) -> int:
    depth = 0
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _clean_latex_field(value: str) -> str:
    cleaned = re.sub(r"\\href\{[^}]+\}\{([^}]+)\}", r"\1", value)
    return re.sub(r"\s+", " ", _latex_unescape(cleaned)).strip()


def _is_non_employer_heading(normalized_value: str) -> bool:
    return normalized_value in NON_EMPLOYER_HEADINGS


def _looks_like_experience_row(company: str, title: str, dates: str) -> bool:
    if not company.strip():
        return False
    if _is_non_employer_heading(_normalize(company)):
        return False
    return bool(title.strip() or dates.strip())


def _term_in(term: str, text: str) -> bool:
    return bool(re.search(rf"(?<![\w+#.-]){re.escape(term.lower())}(?![\w+#.-])", text))


def _section_between(text: str, start: str, end: str) -> str:
    pattern = rf"{re.escape(start)}(.*?){re.escape(end)}"
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else ""


def _normalize(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", (text or "").lower()).strip()
    return collapsed.replace(" %", "%").replace("$ ", "$")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out


def _latex_unescape(text: str) -> str:
    return text.replace(r"\&", "&").replace(r"\%", "%").replace(r"\$", "$").replace(r"\#", "#").replace(r"\_", "_")
