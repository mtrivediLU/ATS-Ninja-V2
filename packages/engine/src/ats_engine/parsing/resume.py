from __future__ import annotations

import re
from typing import Any

from ats_engine.caching.content_hash import default_cache, make_key
from ats_engine.models import Certification, ContactInfo, Education, Experience, Profile
from ats_engine.parsing.line_refs import number_lines, render_numbered_lines, resolve_line_numbers
from ats_engine.providers.base import LLMProvider, generate_json

# Cache namespace for parsed profiles. Bump when parsing behavior changes so
# stale cached profiles are not served after a logic update.
PROFILE_CACHE_VERSION = "profile-v2-completeness-floor"


# The resume below has already been split into numbered lines. The model is
# asked to point at line numbers for bullets instead of retyping them: that is
# both faster (no need to decode the bullet text a second time) and strictly
# more grounded (the resolved text is a guaranteed verbatim slice of the source,
# not the model's reproduction of it).
RESUME_EXTRACTION_PROMPT = """You are a precise resume-parsing engine. The resume below has been split into numbered lines. Extract ONLY what is literally present. Never invent employers, titles, dates, schools, certifications, or skills that are not written in the text.

For company/title/location/dates/degree/institution, write the short value yourself. For experience and education BULLET POINTS, do NOT retype them: instead return the LIST OF LINE NUMBERS (integers) that make up that entry's bullet points, in the order they appear. This is mandatory.

Return ONLY a single JSON object with exactly this shape, no markdown fences, no commentary:
{{
  "contact": {{"name": "", "email": "", "phone": "", "linkedin": "", "website": "", "location": ""}},
  "experiences": [
    {{"company": "", "title": "", "location": "", "dates": "", "bullet_lines": [12, 13, 14]}}
  ],
  "education": [
    {{"institution": "", "degree": "", "location": "", "dates": "", "bullet_lines": [30, 31]}}
  ],
  "certifications": [
    {{"name": "", "date": "", "link": ""}}
  ],
  "skills_listed": ["..."],
  "summary_text": ""
}}

Rules:
- experiences must stay in the order they appear in the resume.
- bullet_lines must be the exact line numbers shown below that belong to that entry's bullet points. Use [] if there are none.
- skills_listed must contain every individual tool, language, platform, framework, or technology named anywhere in the resume (skills section AND bullet lines), each as a short token like "Python" or "Power BI", no duplicates.
- summary_text is the resume's existing summary/objective/profile paragraph if one exists, else "".
- If a field is not present, use "" or []. Do not guess or fill in plausible-sounding values.

Numbered resume lines:
---
{numbered_lines}
---

JSON:
"""


def build_profile(resume_text: str, provider: LLMProvider | None = None) -> Profile:
    """Build the candidate's Profile strictly from their uploaded resume text.

    This is the single source of truth for the pipeline: every fact used
    downstream (skills tiers, experience bullets, education, certifications) is
    derived from what the candidate actually submitted, not from any hardcoded
    personal data.

    The parsed profile is cached under the resume content hash, so the same
    resume never pays for LLM extraction twice, including across restarts.
    """
    text = (resume_text or "").strip()
    if not text:
        return extract_profile("")

    extractor = provider.identity if provider is not None else "heuristic"
    cache = default_cache()
    key = make_key(f"{PROFILE_CACHE_VERSION}|{extractor}", text)
    cached = cache.get(key)
    if isinstance(cached, Profile):
        return cached

    profile = extract_profile(text, provider=provider)
    if profile.experiences or profile.tier_a:
        cache.set(key, profile)
    return profile


def empty_profile() -> Profile:
    """Return a blank, non-hardcoded Profile for placeholder call sites."""
    return _empty_profile()


def extract_profile(resume_text: str, provider: LLMProvider | None = None) -> Profile:
    """Build a Profile strictly from the candidate's own uploaded resume text.

    Tries the LLM first for higher-quality structuring; falls back to a
    deterministic heuristic parser when no provider is available or the LLM
    output cannot be trusted. Every extracted experience/bullet is checked
    against the source text so nothing invented survives into the profile.
    """
    text = (resume_text or "").strip()
    if not text:
        return _empty_profile()

    heuristic_data = _heuristic_extract(text)
    data: Any = None
    if provider is not None:
        lines = number_lines(text)
        prompt = RESUME_EXTRACTION_PROMPT.format(numbered_lines=render_numbered_lines(lines)[:12000])
        data = generate_json(provider, prompt)
        if isinstance(data, dict):
            data = _resolve_bullet_lines(data, lines)

    if not _looks_usable(data) or _is_materially_less_complete(data, heuristic_data):
        data = heuristic_data

    return _build_profile(data, text)


def _resolve_bullet_lines(data: dict[str, Any], lines: list[str]) -> dict[str, Any]:
    """Turn each entry's ``bullet_lines`` (line numbers) into resolved ``bullets`` text.

    If a model ignores the instruction and returns ``bullets`` text directly
    anyway, that is accepted as-is rather than discarded.
    """
    for key in ("experiences", "education"):
        for entry in data.get(key) or []:
            if not isinstance(entry, dict):
                continue
            if entry.get("bullets"):
                continue
            entry["bullets"] = resolve_line_numbers(entry.pop("bullet_lines", None), lines)
    return data


def _empty_profile() -> Profile:
    return Profile(
        contact=ContactInfo(),
        retired_emails=[],
        role_identities=[],
        tier_a={},
        tier_b={},
        tier_c={},
        adjacency={},
        experiences=[],
        education=[],
        certifications=[],
        supported_metrics=[],
    )


def _looks_usable(data: Any) -> bool:
    return isinstance(data, dict) and bool(data.get("experiences") or data.get("skills_listed"))


def _is_materially_less_complete(candidate: Any, baseline: dict[str, Any]) -> bool:
    """Reject LLM parses that drop sections the deterministic parser found.

    A local model can occasionally return a syntactically valid but nearly empty
    JSON object. The heuristic parse is conservative, so treat it as a
    completeness floor: never let an LLM parse ship a gutted profile.
    """
    if not isinstance(candidate, dict):
        return True

    for key in ("experiences", "education", "certifications"):
        if len(candidate.get(key) or []) < len(baseline.get(key) or []):
            return True

    candidate_bullets = sum(
        len(entry.get("bullets") or []) for entry in candidate.get("experiences") or [] if isinstance(entry, dict)
    )
    baseline_bullets = sum(
        len(entry.get("bullets") or []) for entry in baseline.get("experiences") or [] if isinstance(entry, dict)
    )
    if candidate_bullets < baseline_bullets:
        return True

    candidate_skills = {
        str(skill).lower().strip() for skill in candidate.get("skills_listed") or [] if str(skill).strip()
    }
    baseline_skills = {
        str(skill).lower().strip() for skill in baseline.get("skills_listed") or [] if str(skill).strip()
    }
    if len(candidate_skills) < max(1, int(len(baseline_skills) * 0.8)):
        return True

    return False


def _build_profile(data: dict[str, Any], source_text: str) -> Profile:
    contact_data = data.get("contact") or {}
    contact = ContactInfo(
        name=str(contact_data.get("name", "")).strip(),
        email=str(contact_data.get("email", "")).strip(),
        phone=str(contact_data.get("phone", "")).strip(),
        linkedin=str(contact_data.get("linkedin", "")).strip(),
        website=str(contact_data.get("website", "")).strip(),
        location=str(contact_data.get("location", "")).strip(),
    )

    experiences = _clean_experiences(data.get("experiences") or [], source_text)
    education = _clean_education(data.get("education") or [])
    certifications = _clean_certifications(data.get("certifications") or [])
    skills_listed = _dedupe_terms([str(s) for s in (data.get("skills_listed") or []) if str(s).strip()])
    summary_text = str(data.get("summary_text", "") or "")

    tier_a, tier_b, tier_c = _tier_skills(skills_listed, experiences, summary_text)
    supported_metrics = _extract_supported_metrics(experiences)
    role_identities = _dedupe_terms([exp.title for exp in experiences if exp.title])

    return Profile(
        contact=contact,
        retired_emails=[],
        role_identities=role_identities,
        tier_a=tier_a,
        tier_b=tier_b,
        tier_c=tier_c,
        adjacency={},
        experiences=experiences,
        education=education,
        certifications=certifications,
        supported_metrics=supported_metrics,
        raw_markdown=source_text,
    )


def _clean_experiences(raw_entries: list[Any], source_text: str) -> list[Experience]:
    normalized_source = _normalize(source_text)
    experiences: list[Experience] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        company = str(entry.get("company", "")).strip()
        title = str(entry.get("title", "")).strip()
        if not company and not title:
            continue
        # Guard against fabricated employers: the company name (or a meaningful
        # chunk of it) must actually appear in the source resume.
        if company and not _fuzzy_contains(normalized_source, company):
            continue
        bullets = [
            _clean_bullet(bullet)
            for bullet in (entry.get("bullets") or [])
            if _clean_bullet(bullet) and _fuzzy_contains(normalized_source, _clean_bullet(bullet), threshold=0.5)
        ]
        experiences.append(
            Experience(
                company=company or title,
                title=title,
                location=str(entry.get("location", "")).strip(),
                dates=str(entry.get("dates", "")).strip(),
                bullets=bullets,
            )
        )
    return experiences


def _clean_education(raw_entries: list[Any]) -> list[Education]:
    education: list[Education] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        institution = str(entry.get("institution", "")).strip()
        degree = str(entry.get("degree", "")).strip()
        if not institution and not degree:
            continue
        bullets = [_clean_bullet(b) for b in (entry.get("bullets") or []) if _clean_bullet(b)]
        education.append(
            Education(
                institution=institution or degree,
                location=str(entry.get("location", "")).strip(),
                degree=degree,
                dates=str(entry.get("dates", "")).strip(),
                bullets=bullets,
            )
        )
    return education


def _clean_certifications(raw_entries: list[Any]) -> list[Certification]:
    certifications: list[Certification] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        certifications.append(
            Certification(
                name=name,
                date=str(entry.get("date", "")).strip(),
                link=str(entry.get("link", "")).strip(),
            )
        )
    return certifications


def _tier_skills(
    skills_listed: list[str],
    experiences: list[Experience],
    summary_text: str,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    bullet_text = " \n ".join(bullet for exp in experiences for bullet in exp.bullets).lower()
    summary_lower = (summary_text or "").lower()

    tier_a: dict[str, str] = {}
    tier_b: dict[str, str] = {}
    tier_c: dict[str, str] = {}
    for skill in skills_listed:
        normalized = skill.lower().strip()
        if not normalized:
            continue
        if term_in_text(normalized, bullet_text):
            tier_a[normalized] = skill
        elif term_in_text(normalized, summary_lower):
            tier_b[normalized] = skill
        else:
            tier_c[normalized] = skill
    return tier_a, tier_b, tier_c


METRIC_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?%"
    r"|\b\d+\+?\s*(?:years?|engineers?|clients?|users?|customers?|platforms?|projects?|hours?)\b"
    r"|\b\d+\s*(?:to|-)\s*\d+\s*(?:hours?|minutes?|days?)\b"
    r"|\$\d[\d,.]*[kKmMbB]?",
    flags=re.IGNORECASE,
)


def find_metrics(text: str) -> list[str]:
    """Return every metric-like token (percentages, counts, time reductions, dollars) in text."""
    return [match.group(0).strip() for match in METRIC_PATTERN.finditer(text or "")]


def _extract_supported_metrics(experiences: list[Experience]) -> list[str]:
    metrics: list[str] = []
    for experience in experiences:
        for bullet in experience.bullets:
            metrics.extend(find_metrics(bullet))
    return _dedupe_terms(metrics)


def _clean_bullet(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[\-*•]\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def term_in_text(term: str, text: str) -> bool:
    if not term or not text:
        return False
    return bool(re.search(rf"(?<![\w+#.-]){re.escape(term)}(?![\w+#.-])", text))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def _fuzzy_contains(normalized_haystack: str, needle: str, threshold: float = 0.6) -> bool:
    """Loose substring check so minor LLM whitespace/punctuation drift doesn't reject real content."""
    normalized_needle = _normalize(needle)
    if not normalized_needle:
        return False
    if normalized_needle in normalized_haystack:
        return True
    tokens = [tok for tok in re.findall(r"[a-z0-9%]+", normalized_needle) if len(tok) > 2]
    if not tokens:
        return normalized_needle in normalized_haystack
    hits = sum(1 for tok in tokens if tok in normalized_haystack)
    return (hits / len(tokens)) >= threshold


def _dedupe_terms(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            out.append(item.strip())
            seen.add(key)
    return out


# --------------------------------------------------------------------------
# Deterministic fallback parser (used when no provider is reachable, or the LLM
# output fails the usability/completeness checks above).
# --------------------------------------------------------------------------

_SECTION_KEYWORDS = {
    "summary": {"summary", "professional summary", "profile", "objective", "about", "about me"},
    "skills": {"skills", "technical skills", "core competencies", "core skills", "technologies", "skill highlights"},
    "experience": {
        "experience",
        "professional experience",
        "work experience",
        "employment history",
        "work history",
        "relevant experience",
    },
    "education": {"education", "academic background"},
    "certifications": {
        "certifications",
        "certificates",
        "licenses",
        "licenses and certifications",
        "licenses & certifications",
    },
}

_DATE_RANGE = re.compile(
    r"((?:\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+)?\d{4})"
    r"\s*(?:-|to|–|—)\s*"
    r"(Present|Current|(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+)?\d{4})",
    flags=re.IGNORECASE,
)

_LOCATION_TAIL = re.compile(r"([A-Z][A-Za-z.'\s]+,\s*[A-Z]{2,}(?:,\s*[A-Za-z]+)?)\s*$")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_URL = re.compile(r"(https?://[^\s|]+|www\.[^\s|]+)", flags=re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}")
_LINKEDIN = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?", flags=re.IGNORECASE)


def _heuristic_extract(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines()]
    sections = _split_into_sections(lines)

    return {
        "contact": _heuristic_contact(text),
        "experiences": _heuristic_entries(sections.get("experience", []), kind="experience"),
        "education": _heuristic_entries(sections.get("education", []), kind="education"),
        "certifications": _heuristic_certifications(sections.get("certifications", [])),
        "skills_listed": _heuristic_skills(sections.get("skills", [])),
        "summary_text": " ".join(line for line in sections.get("summary", []) if line).strip(),
    }


def _split_into_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {key: [] for key in _SECTION_KEYWORDS}
    current = "summary"
    for line in lines:
        if not line:
            continue
        heading = _detect_heading(line)
        if heading:
            current = heading
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _detect_heading(line: str) -> str | None:
    if len(line) > 40:
        return None
    normalized = re.sub(r"\s+", " ", line.strip().strip(":")).lower()
    for section, keywords in _SECTION_KEYWORDS.items():
        if normalized in keywords:
            return section
    return None


def _heuristic_entries(lines: list[str], *, kind: str) -> list[dict[str, Any]]:
    """Group section lines into entries.

    Layout assumption (the dominant resume convention): each entry's header
    lines (company/institution, optionally title) appear immediately BEFORE the
    line carrying its date range, and bullets follow. The header buffer
    therefore always belongs to the entry whose date line closes it, never to
    the previous entry. Non-bullet lines that start lowercase while an entry has
    open bullets are treated as PDF wrap continuations of the last bullet.
    """
    primary = "company" if kind == "experience" else "institution"
    secondary = "title" if kind == "experience" else "degree"
    entries: list[dict[str, Any]] = []
    header_buffer: list[str] = []
    current: dict[str, Any] | None = None

    def new_entry() -> dict[str, Any]:
        return {primary: "", secondary: "", "location": "", "dates": "", "bullets": []}

    def finalize(entry: dict[str, Any] | None) -> None:
        if entry and (entry[primary] or entry[secondary] or entry["bullets"]):
            entries.append(entry)

    def apply_header(entry: dict[str, Any], header_lines: list[str]) -> None:
        if not header_lines:
            return
        head = header_lines[0]
        suffix = ""
        paren_match = re.search(r"\s*\(([^)]*)\)\s*$", head)
        if paren_match:
            suffix = f" ({paren_match.group(1)})"
            head = head[: paren_match.start()].rstrip()
        location_match = _LOCATION_TAIL.search(head)
        if location_match and location_match.start() > 0:
            entry["location"] = entry["location"] or (location_match.group(1).strip() + suffix)
            head = head[: location_match.start()].strip(" |-,")
        entry[primary] = head
        if len(header_lines) > 1 and not entry[secondary]:
            entry[secondary] = header_lines[1]

    for line in lines:
        if not line:
            continue

        date_match = _DATE_RANGE.search(line)
        if date_match:
            finalize(current)
            current = new_entry()
            current["dates"] = date_match.group(0)
            remainder = (line[: date_match.start()] + " " + line[date_match.end() :]).strip(" |-,")
            location_match = _LOCATION_TAIL.search(remainder)
            if location_match:
                current["location"] = location_match.group(1).strip()
                remainder = remainder[: location_match.start()].strip(" |-,")
            if remainder:
                current[secondary] = remainder
            apply_header(current, header_buffer)
            header_buffer = []
            continue

        if _is_bullet(line):
            if current is None:
                current = new_entry()
                apply_header(current, header_buffer)
                header_buffer = []
            current["bullets"].append(line)
            continue

        if current is not None and current["bullets"] and line[0].islower():
            current["bullets"][-1] = f"{current['bullets'][-1]} {line}"
        else:
            header_buffer.append(line)

    finalize(current)
    if not entries and header_buffer:
        # No date lines and no bullets found; treat the block as one entry.
        entry = new_entry()
        apply_header(entry, header_buffer)
        finalize(entry)
    return entries


def _heuristic_certifications(lines: list[str]) -> list[dict[str, str]]:
    certifications: list[dict[str, str]] = []
    for line in lines:
        if not line:
            continue
        year_match = _YEAR.search(line)
        url_match = _URL.search(line)
        name = line
        if year_match:
            name = (name[: year_match.start()] + name[year_match.end() :]).strip(" |-")
        if url_match:
            name = name.replace(url_match.group(0), "").strip(" |-")
        name = re.sub(r"credential id:.*$", "", name, flags=re.IGNORECASE).strip(" |-:")
        if not name:
            continue
        certifications.append(
            {
                "name": name,
                "date": year_match.group(0) if year_match else "",
                "link": url_match.group(0) if url_match else "",
            }
        )
    return certifications


def _heuristic_skills(lines: list[str]) -> list[str]:
    skills: list[str] = []
    for line in lines:
        content = line.split(":", 1)[-1] if ":" in line and len(line.split(":", 1)[0]) <= 40 else line
        parts = re.split(r"[,;|]|\s{2,}|•|\*", content)
        skills.extend(part.strip() for part in parts if part.strip() and len(part.strip()) <= 40)
    return _dedupe_terms(skills)


def _heuristic_contact(text: str) -> dict[str, str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    email_match = _EMAIL.search(text)
    phone_match = _PHONE.search(text)
    linkedin_match = _LINKEDIN.search(text)
    name = ""
    for line in lines[:5]:
        if "@" in line or "linkedin" in line.lower() or any(char.isdigit() for char in line):
            continue
        words = line.split()
        if 2 <= len(words) <= 4:
            name = line
            break
    return {
        "name": name,
        "email": email_match.group(0) if email_match else "",
        "phone": phone_match.group(0) if phone_match else "",
        "linkedin": linkedin_match.group(0) if linkedin_match else "",
        "website": "",
        "location": "",
    }


def _is_bullet(line: str) -> bool:
    return bool(re.match(r"^\s*[\-*•]\s+", line))
