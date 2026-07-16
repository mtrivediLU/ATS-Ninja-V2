from __future__ import annotations

import re
from collections import Counter

from ats_engine.models import JDProfile, Profile
from ats_engine.parsing.line_refs import number_lines, render_numbered_lines, resolve_line_numbers
from ats_engine.parsing.resume import empty_profile
from ats_engine.providers.base import LLMProvider, generate_json

# The JD has already been split into numbered lines. Pointing at line numbers
# for the long list fields (instead of retyping each requirement sentence)
# avoids burning decode time re-generating text the model just read, and
# guarantees the resolved text is an exact source excerpt.
JD_EXTRACTION_PROMPT = """You are an expert technical recruiter. The job description below has been split into numbered lines. Extract structured fields using ONLY what is written in it.

For required_qualification_lines, preferred_qualification_lines, and responsibility_lines: do NOT retype the sentences. Return the LIST OF LINE NUMBERS (integers) that state each one, in order. This is mandatory.

Return ONLY a single JSON object with exactly this shape, no markdown fences, no commentary:
{{
  "title": "",
  "company": "",
  "location": "",
  "work_mode": "remote or hybrid or on-site or unknown",
  "required_qualification_lines": [5, 6, 7],
  "preferred_qualification_lines": [10],
  "responsibility_lines": [2, 3],
  "technical_keywords": ["..."],
  "domain": "",
  "ats_platform": "workday or greenhouse or lever or ashby or icims or bamboohr or unknown"
}}

Rules:
- required_qualification_lines: line numbers explicitly stated as required or must-have.
- preferred_qualification_lines: line numbers explicitly stated as preferred, nice to have, or bonus.
- responsibility_lines: line numbers describing what the role will actually do day to day.
- technical_keywords: every specific tool, language, platform, framework, or methodology named anywhere in the posting, deduped, most important first, written as short tokens (not full lines).
- domain: one or two words for the industry (e.g. "healthcare", "mining", "e-commerce"), or "" if unclear.
- Use [] for a line-number field with nothing to report. Do not invent line numbers that are not shown below.

Numbered job description lines:
---
{numbered_lines}
---

JSON:
"""

_LINE_LIST_FIELDS = {
    "required_qualification_lines": "required_qualifications",
    "preferred_qualification_lines": "preferred_qualifications",
    "responsibility_lines": "responsibilities",
}


COMMON_TECH_TERMS = [
    "python",
    "java",
    "javascript",
    "typescript",
    "sql",
    "postgresql",
    "dbt",
    "etl",
    "elt",
    "tableau",
    "power bi",
    "azure",
    "aws",
    "gcp",
    "docker",
    "kubernetes",
    "spring",
    "hibernate",
    "rest",
    "microservices",
    "react",
    "react native",
    "node.js",
    "mongodb",
    "fastapi",
    "graphql",
    "c#",
    ".net",
    "machine learning",
    "ml",
    "llm",
    "rag",
    "openai",
    "gemini",
    "salesforce",
    "hubspot",
    "snowflake",
    "looker",
    "spark",
    "airflow",
    "scikit-learn",
    "business intelligence",
    "data visualization",
    "data warehousing",
    "data warehouse",
    "data modeling",
    "data modelling",
    "data integration",
    "data quality",
    "semantic models",
    "dataflow",
    "dashboards",
    "dashboard",
    "amazon quicksight",
    "quicksight",
    "d3.js",
    "dax",
    "redshift",
]


def parse_jd(job_description: str, profile: Profile | None = None, provider: LLMProvider | None = None) -> JDProfile:
    """Parse a job description into structured planning fields.

    Runs the deterministic heuristic parser first (always available), then, if a
    provider is supplied, layers an LLM extraction on top and prefers its fields
    whenever they are non-empty. This keeps the pipeline fully functional with no
    LLM while giving materially better extraction when one is available.
    """
    profile = profile or empty_profile()
    heuristic = _parse_jd_heuristic(job_description, profile)
    if provider is None:
        return heuristic

    lines = number_lines(job_description or "")
    prompt = JD_EXTRACTION_PROMPT.format(numbered_lines=render_numbered_lines(lines)[:8000])
    llm_data = generate_json(provider, prompt)
    if not isinstance(llm_data, dict):
        return heuristic

    llm_data = _resolve_line_list_fields(llm_data, lines)
    return _merge_jd_profile(heuristic, llm_data)


def _resolve_line_list_fields(data: dict[str, object], lines: list[str]) -> dict[str, object]:
    """Turn each ``*_lines`` line-number field into resolved text under its plain field name.

    If a model ignores the instruction and returns the plain text field directly
    anyway, that is accepted as-is rather than discarded.
    """
    for line_field, text_field in _LINE_LIST_FIELDS.items():
        if data.get(text_field):
            continue
        data[text_field] = resolve_line_numbers(data.pop(line_field, None), lines)
    return data


def _parse_jd_heuristic(job_description: str, profile: Profile) -> JDProfile:
    text = job_description or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = _extract_title(text, lines)
    company = _extract_company(text, lines)
    required = _extract_section_items(
        lines,
        ["required", "requirements", "qualifications", "must have", "what we are looking for"],
        # "qualifications" alone would otherwise also match a "Preferred
        # qualifications:" heading, absorbing the preferred section's bullets
        # into the required list. A stop heading always ends the section, even
        # though it shares a word with a start heading.
        stop_headings=["preferred", "nice to have", "bonus"],
    )
    preferred = _extract_section_items(lines, ["preferred", "nice to have", "bonus"])
    responsibilities = _extract_section_items(
        lines, ["responsibilities", "what you will do", "duties", "role", "your day to day", "day to day"]
    )
    keywords = _extract_keywords(text, profile)
    work_mode = _extract_work_mode(text)
    location = _extract_location(text, lines)
    domain = _extract_domain(text)
    ats = _extract_ats_platform(text)

    if not required:
        required = _sentences_with_keywords(text, keywords[:6])
    if not responsibilities:
        responsibilities = _sentences_with_keywords(text, keywords[:5])[:5]

    return JDProfile(
        title=title or "Target Role",
        company=company or "Target Company",
        work_mode=work_mode,
        location=location,
        required_qualifications=required[:8],
        preferred_qualifications=preferred[:8],
        responsibilities=responsibilities[:5],
        technical_keywords=keywords[:18],
        domain=domain,
        ats_platform=ats,
    )


def _merge_jd_profile(heuristic: JDProfile, llm_data: dict[str, object]) -> JDProfile:
    def text_field(key: str, fallback: str) -> str:
        value = str(llm_data.get(key, "") or "").strip()
        return value or fallback

    def list_field(key: str, fallback: list[str]) -> list[str]:
        value = llm_data.get(key)
        if isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            if cleaned:
                return cleaned[:18]
        return fallback

    def merged_list(key: str, authoritative: list[str], *, limit: int) -> list[str]:
        """Keep deterministic section membership as a provider-proof floor."""
        values = list(authoritative) + list_field(key, [])
        merged: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = value.casefold().strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                merged.append(value)
        return merged[:limit]

    def requirement_key(value: str) -> str:
        return re.sub(r"^[\s\-*•]+", "", value.casefold()).strip()

    work_mode = text_field("work_mode", heuristic.work_mode).lower()
    if work_mode not in {"remote", "hybrid", "on-site", "onsite", "relocation", "unknown"}:
        work_mode = heuristic.work_mode
    if work_mode == "onsite":
        work_mode = "on-site"

    ats_platform = text_field("ats_platform", heuristic.ats_platform).lower()
    if ats_platform not in {"workday", "greenhouse", "lever", "ashby", "icims", "bamboohr", "unknown"}:
        ats_platform = heuristic.ats_platform

    required = merged_list("required_qualifications", heuristic.required_qualifications, limit=8)
    required_normalized = {requirement_key(value) for value in required}
    preferred = [
        value
        for value in merged_list("preferred_qualifications", heuristic.preferred_qualifications, limit=16)
        if requirement_key(value) not in required_normalized
    ][:8]
    return JDProfile(
        title=text_field("title", heuristic.title),
        company=text_field("company", heuristic.company),
        work_mode=work_mode,
        location=text_field("location", heuristic.location),
        required_qualifications=required,
        preferred_qualifications=preferred,
        responsibilities=merged_list("responsibilities", heuristic.responsibilities, limit=5),
        technical_keywords=merged_list("technical_keywords", heuristic.technical_keywords, limit=18),
        domain=text_field("domain", heuristic.domain),
        ats_platform=ats_platform,
    )


def _extract_title(text: str, lines: list[str]) -> str:
    patterns = [
        r"(?:job title|position|role)\s*[:\-]\s*([^\n|]+)",
        r"hiring\s+(?:a|an)\s+([A-Z][A-Za-z0-9 /&+#.-]{3,70})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_title(match.group(1))

    for line in lines[:8]:
        lowered = line.lower()
        if any(word in lowered for word in ["engineer", "developer", "analyst", "scientist", "architect"]):
            if len(line) <= 90 and not line.endswith("."):
                return _clean_title(line)
    return ""


def _extract_company(text: str, lines: list[str]) -> str:
    patterns = [
        r"(?:company|organization|employer)\s*[:\-]\s*([^\n|]+)",
        r"\bat\s+([A-Z][A-Za-z0-9 &.,-]{2,60})\s+(?:is|we are|seeks|seeking|hiring)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _trim_company(match.group(1))

    for line in lines[:6]:
        if line.lower().startswith("about "):
            return _trim_company(line[6:])
    for line in lines[1:8]:
        cleaned = line.strip()
        lowered = cleaned.lower()
        if not cleaned or len(cleaned) > 80:
            continue
        if lowered.startswith(("job ", "location", "$")) or "out of 5" in lowered:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
            continue
        if any(word in lowered for word in ["engineer", "developer", "analyst", "scientist", "architect"]):
            continue
        if re.search(r"[A-Za-z]", cleaned):
            return _trim_company(cleaned)
    return ""


def _extract_section_items(lines: list[str], headings: list[str], stop_headings: list[str] | None = None) -> list[str]:
    items: list[str] = []
    active = False
    for line in lines:
        lowered = line.lower().strip(":")
        # A stop heading always ends the section first, even if the same line
        # also happens to contain one of our own (generic) start headings.
        if active and stop_headings and any(stop in lowered for stop in stop_headings) and len(line) < 80:
            active = False
            continue
        if any(heading in lowered for heading in headings) and len(line) < 80:
            active = True
            continue
        if active and re.match(r"^[A-Z][A-Za-z /&-]{2,40}:?$", line) and len(line) < 60:
            break
        if active:
            cleaned = re.sub(r"^[\-*•]\s*", "", line).strip()
            if cleaned:
                items.append(cleaned)
    return items


def _extract_keywords(text: str, profile: Profile) -> list[str]:
    lowered = text.lower()
    candidates = set(COMMON_TECH_TERMS)
    candidates.update(profile.tier_a.keys())
    candidates.update(profile.tier_b.keys())
    candidates.update(profile.tier_c.keys())
    candidates.update(profile.adjacency.keys())

    found: list[str] = []
    for term in sorted(candidates, key=len, reverse=True):
        if re.search(rf"(?<![\w+#.-]){re.escape(term.lower())}(?![\w+#.-])", lowered):
            display = _display_keyword(term, profile)
            if display not in found:
                found.append(display)

    tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9+#.-]{2,}\b", lowered)
    counts = Counter(tokens)
    for token, count in counts.most_common(20):
        if count > 1 and token not in _GENERIC_KEYWORD_TOKENS:
            display = _display_keyword(token, profile)
            if display not in found:
                found.append(display)
    return found


_GENERIC_KEYWORD_TOKENS = {
    "the",
    "and",
    "for",
    "with",
    "you",
    "our",
    "are",
    "that",
    "this",
    "will",
    "job",
    "role",
    "tools",
    "business",
    "data",
    "rbh",
    "work",
    "team",
    "teams",
    "needs",
    "using",
    "including",
    "experience",
    "knowledge",
    "techniques",
    "processes",
}


def _display_keyword(term: str, profile: Profile) -> str:
    normalized = term.lower()
    for source in [profile.tier_a, profile.tier_b, profile.tier_c]:
        if normalized in source:
            return source[normalized]
    return {
        "aws": "AWS",
        "gcp": "GCP",
        "rag": "RAG",
        "llm": "LLM",
        "ml": "ML",
        "rest": "REST APIs",
    }.get(normalized, term)


def _extract_work_mode(text: str) -> str:
    lowered = text.lower()
    if "hybrid" in lowered:
        return "hybrid"
    if "remote" in lowered:
        return "remote"
    if "on-site" in lowered or "onsite" in lowered or "in office" in lowered:
        return "on-site"
    if "relocat" in lowered:
        return "relocation"
    return "unknown"


def _extract_location(text: str, lines: list[str]) -> str:
    match = re.search(r"(?:location|based in)\s*[:\-]\s*([^\n|]+)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    for line in lines[:12]:
        if any(place in line.lower() for place in ["toronto", "ontario", "canada", "remote", "hybrid"]):
            return line[:90].strip()
    return ""


def _extract_domain(text: str) -> str:
    lowered = text.lower()
    domains = [
        ("medical device", "medical device"),
        ("healthcare", "healthcare"),
        ("finance", "finance"),
        ("mining", "mining"),
        ("commerce", "commerce"),
        ("saas", "SaaS"),
        ("ai", "AI"),
        ("data", "data"),
    ]
    for needle, domain in domains:
        if needle in lowered:
            return domain
    return ""


def _extract_ats_platform(text: str) -> str:
    lowered = text.lower()
    for platform in ["workday", "greenhouse", "lever", "ashby", "icims", "bamboohr"]:
        if platform in lowered:
            return platform
    return "unknown"


def _sentences_with_keywords(text: str, keywords: list[str]) -> list[str]:
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]
    matched: list[str] = []
    for sentence in sentences:
        if any(keyword.lower() in sentence.lower() for keyword in keywords):
            matched.append(sentence)
    return matched


def _clean_title(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip(" -|")
    return cleaned[:80]


def _trim_company(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip(" -|.")
    return cleaned[:70]
