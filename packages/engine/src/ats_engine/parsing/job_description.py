from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import replace

from ats_engine.models import JDProfile, Profile, RequirementTerm
from ats_engine.parsing.jd_requirements import (
    JDHygiene,
    extract_requirements,
    filter_hygienic_jd_values,
    is_person_name,
    sanitize_jd_for_parsing,
)
from ats_engine.parsing.line_refs import number_lines, render_numbered_lines, resolve_line_numbers
from ats_engine.parsing.resume import empty_profile
from ats_engine.parsing.vocab import normalize_term
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
    # Power Platform / low-code and .NET-adjacent enterprise development —
    # absent from the original list, which was built from BI/data-engineering
    # postings and missed an entire category of requirements for roles like
    # Power Platform developer.
    "power apps",
    "power automate",
    "power pages",
    "power platform",
    "dataverse",
    "model driven apps",
    "model-driven apps",
    "pcf",
    "pcf controls",
    "sharepoint",
    "azure functions",
    "azure function apps",
    "azure api management",
    "dynamics 365",
    ".net framework",
    "html5",
    "css",
    "source control",
    "branching and merging",
    "root-cause analysis",
    "root cause analysis",
    "liquid",
    "powershell",
    # Non-tool requirement phrases that recur across enterprise/government
    # postings (business-analysis, integration, support, documentation) —
    # missing from the original list, which only named products/languages.
    "business requirements",
    "user experience",
    "ux",
    "technical documentation",
    "system integration",
    "system integrations",
    "application support",
    "production support",
    "plug-ins",
    "plug-in",
    "plugins",
    "custom apis",
    # Software testing / quality vocabulary — development-and-testing roles (SDET,
    # full-stack + QA) name these explicitly, and they were previously undetected,
    # so a testing requirement never even reached the evidence matrix. Detection
    # only; crediting is still evidence-gated (see ats_engine.evidence.transfer).
    "unit testing",
    "unit tests",
    "integration testing",
    "integration tests",
    "api testing",
    "test automation",
    "automated testing",
    "automated tests",
    "regression testing",
    "test cases",
    "test coverage",
    "test-driven development",
    "tdd",
    "quality assurance",
    "quality engineering",
    "software testing",
    "software quality",
    "code review",
    "code reviews",
    "ci/cd",
    "cicd",
    "continuous integration",
    "continuous delivery",
    "debugging",
    "defect resolution",
    "selenium",
    "cypress",
    "playwright",
    "junit",
    "mockito",
    "jest",
    "pytest",
    "performance testing",
    "load testing",
    "security testing",
    # General web development vocabulary the BI-era list omitted.
    "node.js",
    "express",
    "next.js",
    "angular",
    "vue",
    "rest apis",
    "restful apis",
    "web development",
    "frontend",
    "backend",
    "full-stack",
    "full stack",
]


def parse_jd(
    job_description: str,
    profile: Profile | None = None,
    provider: LLMProvider | None = None,
    *,
    tailoring_v2: bool = True,
) -> JDProfile:
    """Parse a job description into structured planning fields.

    Runs the deterministic heuristic parser first (always available), then, if a
    provider is supplied, layers an LLM extraction on top and prefers its fields
    whenever they are non-empty. This keeps the pipeline fully functional with no
    LLM while giving materially better extraction when one is available.
    """
    profile = profile or empty_profile()
    # V2 requirement extraction is JD-only by construction.  Retain the
    # historical candidate-seeded heuristic behind the explicit flag for
    # persisted/legacy callers that need it, never as the default path.
    heuristic_profile = empty_profile() if tailoring_v2 else profile
    hygiene = sanitize_jd_for_parsing(job_description)
    heuristic = _parse_jd_heuristic(job_description, heuristic_profile, hygiene=hygiene)
    requirements = extract_requirements(job_description) if tailoring_v2 else []
    if requirements:
        heuristic = _apply_v2_requirements(heuristic, requirements)
    if provider is None:
        return heuristic

    # Give the provider the same contact-free, post-qualification-cleaned
    # source view used by the deterministic parser. The provider's numbered
    # references therefore cannot point at an application, HR, salary, or EEO
    # line that the merger would later discard.
    lines = number_lines("\n".join(hygiene.scoring_lines))
    prompt = JD_EXTRACTION_PROMPT.format(numbered_lines=render_numbered_lines(lines)[:8000])
    llm_data = generate_json(provider, prompt)
    if not isinstance(llm_data, dict):
        return heuristic

    llm_data = _resolve_line_list_fields(llm_data, lines)
    return _merge_jd_profile(heuristic, llm_data, hygiene)


def _apply_v2_requirements(heuristic: JDProfile, requirements: list[RequirementTerm]) -> JDProfile:
    """Project typed v2 requirements onto legacy JD fields without losing them."""

    def lines(section: str) -> list[str]:
        return _dedupe_requirement_lines(item.jd_evidence_line for item in requirements if item.section == section)

    # Responsibilities remain a useful presentation/letter input. A
    # requirement labelled responsibility gets its own source line rather than
    # being promoted into a generic unigram keyword list.
    required = lines("required")
    preferred = lines("preferred")
    responsibilities = lines("responsibility")
    keywords = _dedupe_requirement_lines(item.surface for item in requirements)
    return replace(
        heuristic,
        required_qualifications=required or heuristic.required_qualifications,
        preferred_qualifications=preferred or heuristic.preferred_qualifications,
        responsibilities=responsibilities or heuristic.responsibilities,
        technical_keywords=keywords[:30] or heuristic.technical_keywords,
        requirements=requirements,
        parse_confidence=max(
            heuristic.parse_confidence,
            _parse_confidence(
                title=heuristic.title,
                company=heuristic.company,
                required=required or heuristic.required_qualifications,
                responsibilities=responsibilities or heuristic.responsibilities,
            ),
        ),
    )


def _dedupe_requirement_lines(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _parse_confidence(
    *,
    title: str,
    company: str,
    required: list[str],
    responsibilities: list[str],
) -> float:
    """Return a bounded deterministic parse-completeness annotation."""
    score = 0.1
    if title and title != "Target Role":
        score += 0.25
    if company and company != "Target Company":
        score += 0.2
    if required:
        score += 0.25
    if responsibilities:
        score += 0.2
    return round(min(score, 1.0), 2)


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


def _parse_jd_heuristic(job_description: str, profile: Profile, *, hygiene: JDHygiene | None = None) -> JDProfile:
    hygiene = hygiene or sanitize_jd_for_parsing(job_description)
    target_lines = list(hygiene.target_lines)
    scoring_lines = list(hygiene.scoring_lines)
    target_text = "\n".join(target_lines)
    clean_text = "\n".join(scoring_lines)
    title = _extract_title(target_text, target_lines)
    company = _extract_company(target_text, target_lines, title, hygiene)
    required = _extract_section_items(
        scoring_lines,
        [
            "required",
            "requirements",
            "qualifications",
            "must have",
            "what we are looking for",
            # Postings phrase the mandatory-qualifications heading as a
            # question or an instruction rather than the word "required"
            # (e.g. a "What you need to succeed" / "In addition, you have:"
            # pair) often enough that matching only "required"/"qualifications"
            # silently produced an empty required list for them.
            "what you need to succeed",
            "in addition, you have",
            "in addition you have",
        ],
        # "qualifications" alone would otherwise also match a "Preferred
        # qualifications:" heading, absorbing the preferred section's bullets
        # into the required list. A stop heading always ends the section, even
        # though it shares a word with a start heading.
        stop_headings=["preferred", "nice to have", "nice-to-have", "bonus"],
    )
    preferred = _extract_section_items(
        scoring_lines,
        # A hyphenated "Nice-to-have" heading does not contain the substring
        # "nice to have" (space, not hyphen), so it silently matched nothing.
        ["preferred", "nice to have", "nice-to-have", "bonus"],
    )
    responsibilities = _extract_section_items(
        scoring_lines, ["responsibilities", "what you will do", "duties", "role", "your day to day", "day to day"]
    )
    education_experience = _extract_section_items(
        scoring_lines,
        ["education and experience", "your education and experience", "combined education and work experience"],
    )
    security_language = _extract_section_items(
        scoring_lines, ["language requirement", "security", "official languages"]
    )
    employment_conditions = _extract_section_items(
        scoring_lines, ["what you need to know", "hybrid work model", "work arrangement"]
    )
    compensation_benefits = _extract_section_items(
        scoring_lines, ["what you can expect", "salary", "compensation and benefits", "benefits"]
    )
    boilerplate = _dedupe_requirement_lines([*hygiene.context_lines, *_extract_boilerplate_lines(target_lines)])

    # The employer's own name (and the target title's words) must never
    # surface as a "technical keyword" gap — a fragment like "Bank" repeated
    # throughout the posting is the company's name, not a missing skill.
    org_words = {
        word.lower() for word in re.findall(r"[A-Za-z]+", " ".join((title, company, *hygiene.organization_names)))
    }
    keywords = _extract_keywords(clean_text, clean_text, profile, exclude_tokens=org_words)
    work_mode = _extract_work_mode(clean_text)
    location = _extract_location(target_text, target_lines)
    domain = _extract_domain(clean_text)
    ats = _extract_ats_platform(clean_text)

    if not required:
        required = _sentences_with_keywords(clean_text, keywords[:6])
    if not responsibilities:
        responsibilities = _sentences_with_keywords(clean_text, keywords[:5])[:8]

    return JDProfile(
        title=title or "Target Role",
        company=company or "Target Company",
        work_mode=work_mode,
        location=location,
        required_qualifications=required[:8],
        preferred_qualifications=preferred[:8],
        # 8, not the previous 5: an intro paragraph or a "More specifically,
        # you will:" sub-heading line routinely occupies the first slot or
        # two under a responsibilities heading before the real bulleted
        # duties start, so a tight cap silently dropped genuine
        # responsibilities (now a primary tailoring input, not just an
        # interview-prep source — see build_evidence_matrix).
        responsibilities=responsibilities[:8],
        # 30, not the previous 18: a posting with a genuinely long, specific
        # requirement list (e.g. a full Power Platform stack) was silently
        # truncating short-but-critical acronyms like "C#" off the end,
        # since longer phrases sort first (see _extract_keywords below).
        technical_keywords=_prioritize_required_keywords(keywords, required)[:30],
        domain=domain,
        ats_platform=ats,
        education_experience_requirements=education_experience[:8],
        security_language_requirements=security_language[:8],
        employment_conditions=employment_conditions[:8],
        compensation_benefits=compensation_benefits[:8],
        organizational_boilerplate=boilerplate[:20],
        parse_confidence=_parse_confidence(
            title=title,
            company=company,
            required=required,
            responsibilities=responsibilities,
        ),
    )


def _prioritize_required_keywords(keywords: list[str], required_lines: list[str]) -> list[str]:
    """Put keywords that literally appear in the required-qualifications text
    first, so a long candidate list never truncates a short, critical,
    explicitly-required term (e.g. "C#") in favor of a longer generic one."""
    required_text = " ".join(required_lines).lower()
    in_required = [keyword for keyword in keywords if keyword.lower() in required_text]
    rest = [keyword for keyword in keywords if keyword not in in_required]
    return in_required + rest


def _merge_jd_profile(heuristic: JDProfile, llm_data: dict[str, object], hygiene: JDHygiene) -> JDProfile:
    def text_field(key: str, fallback: str) -> str:
        value = str(llm_data.get(key, "") or "").strip()
        values = filter_hygienic_jd_values([value], hygiene, require_scoring_source=False)
        return values[0] if values else fallback

    def list_field(key: str, *, company: str = "") -> list[str]:
        value = llm_data.get(key)
        if isinstance(value, list):
            return filter_hygienic_jd_values(value, hygiene, company=company)[:18]
        return []

    def merged_list(key: str, authoritative: list[str], *, limit: int) -> list[str]:
        """Keep deterministic section membership as a provider-proof floor."""
        values = list(authoritative) + list_field(key, company=heuristic.company)
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
    # Target parsing is deterministic by policy. A provider may fill a truly
    # absent value, but cannot overwrite a source-backed title/company with a
    # less-specific role phrase, person name, or application contact.
    llm_title = _safe_llm_title(llm_data.get("title", ""), hygiene)
    llm_company = _safe_llm_company(llm_data.get("company", ""), heuristic.title, hygiene)
    title = heuristic.title if heuristic.title != "Target Role" else (llm_title or heuristic.title)
    company = heuristic.company if heuristic.company != "Target Company" else (llm_company or heuristic.company)
    return JDProfile(
        title=title,
        company=company,
        work_mode=work_mode,
        location=text_field("location", heuristic.location),
        required_qualifications=required,
        preferred_qualifications=preferred,
        responsibilities=merged_list("responsibilities", heuristic.responsibilities, limit=8),
        technical_keywords=merged_list("technical_keywords", heuristic.technical_keywords, limit=30),
        domain=text_field("domain", heuristic.domain),
        ats_platform=ats_platform,
        education_experience_requirements=heuristic.education_experience_requirements,
        security_language_requirements=heuristic.security_language_requirements,
        employment_conditions=heuristic.employment_conditions,
        compensation_benefits=heuristic.compensation_benefits,
        organizational_boilerplate=heuristic.organizational_boilerplate,
        requirements=heuristic.requirements,
        parse_confidence=heuristic.parse_confidence,
    )


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


def _extract_company(text: str, lines: list[str], title: str, hygiene: JDHygiene) -> str:
    # 1. Explicit source label always wins.
    for line in lines:
        match = re.match(r"^(?:company|organization|organisation|employer)\s*[:\-]\s*(.+)$", line, re.I)
        if match is not None:
            candidate = _trim_company(match.group(1))
            if _is_valid_company_candidate(candidate, title, explicit_label=True):
                return candidate

    # 2. An About heading is a strong, direct organization signal.  "About the
    # role" is intentionally not a company name; look at the nearby source
    # sentence for its "The Org ..." form instead.
    about_candidate = _company_from_about_heading(lines, title)
    if about_candidate:
        return about_candidate

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


def _is_valid_title_candidate(value: str, *, explicit_label: bool = False) -> bool:
    cleaned = _clean_title(value)
    words = re.findall(r"[A-Za-z]+", cleaned.casefold())
    if not cleaned or len(cleaned) > 80 or _looks_like_contact_value(cleaned):
        return False
    if normalize_term(cleaned) in _CONTACT_ROLE_TITLES and not explicit_label:
        return False
    if not words or not (set(words) & _TITLE_ROLE_WORDS):
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
    """Whether an extracted employer phrase is only a boilerplate noun."""

    normalized = _ARTICLE_PREFIX.sub("", value).casefold().strip(" .,:;-")
    return normalized in {"company", "organization", "organisation", "employer"}


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


def _extract_section_items(lines: list[str], headings: list[str], stop_headings: list[str] | None = None) -> list[str]:
    items: list[str] = []
    active = False
    for line in lines:
        cleaned_prefix = re.sub(r"^[\-*•]\s*", "", line.lower()).strip(":")
        # A stop heading always ends the section first, even if the same line
        # also happens to contain one of our own (generic) start headings.
        if (
            active
            and stop_headings
            and any(cleaned_prefix.startswith(stop) for stop in stop_headings)
            and len(line) < 80
        ):
            active = False
            continue
        # ``startswith``, not "contains": a body bullet that merely mentions a
        # heading word mid-sentence (e.g. "...to meet business requirements")
        # must never be mistaken for a "Requirements" section heading and
        # swallow every following responsibility bullet into required
        # qualifications. A real heading word always opens the line.
        if any(cleaned_prefix.startswith(heading) for heading in headings) and len(line) < 80:
            active = True
            continue
        if active and re.match(r"^[A-Z][A-Za-z /&-]{2,40}:?$", line) and len(line) < 60:
            break
        if active:
            cleaned = re.sub(r"^[\-*•]\s*", "", line).strip()
            if cleaned:
                items.append(cleaned)
    return items


def _extract_keywords(
    text: str, clean_text: str, profile: Profile, exclude_tokens: set[str] | None = None
) -> list[str]:
    lowered = text.lower()
    exclude = exclude_tokens or set()
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

    # Frequency-based discovery (anything repeated and not an explicit tech
    # term) runs on boilerplate-stripped text only: organizational/D&I/
    # benefits/recruitment-process paragraphs repeat words like "Bank",
    # "diversity", or "recruitment" often enough to otherwise leak into the
    # keyword list as a fake "technical requirement" and a fake gap.
    tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9+#.-]{2,}\b", clean_text.lower())
    counts = Counter(tokens)
    for token, count in counts.most_common(20):
        if count <= 1 or token in _GENERIC_KEYWORD_TOKENS or token in exclude:
            continue
        # A bare token that is already just a fragment of a longer keyword
        # the whitelist scan already found (e.g. "power"/"platform" once
        # "power platform" is already in ``found``) is redundant noise in the
        # requirement map, not a second, distinct requirement.
        if any(token in existing.lower() for existing in found):
            continue
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
    "have",
    "requirements",
    "positions",
    "years",
    "candidates",
    "provide",
    "ensure",
    "apply",
    "applicants",
    "position",
    "opportunity",
    "opportunities",
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
        # Word-boundary match, not a bare substring test: "ai" as a bare
        # substring matches "maintain", "training", "certain", "domain"
        # itself, and countless other common words, misclassifying almost
        # any posting's domain as "AI".
        if re.search(rf"\b{re.escape(needle)}\b", lowered):
            return domain
    return ""


# Substrings that mark a line as organizational messaging rather than a real
# requirement, responsibility, or logistics fact — diversity/inclusion and
# accommodation language, benefits/compensation marketing, and boilerplate
# recruitment-process copy. Matched case-insensitively against the whole line
# so it works whether or not the line sits under a recognized heading.
_BOILERPLATE_KEYWORDS = (
    "diversity",
    "inclusion",
    "equity, ",
    "accommodation",
    "self-identify",
    "indigenous",
    "disabilit",
    "racialized",
    "visible minorit",
    "pension plan",
    "defined-benefit pension",
    "vacation entitlement",
    "vacation days",
    "benefits package",
    "we wish to thank",
    "only candidates selected",
    "top employer",
    "barrier-free",
    "let our team know",
    "recruitment process",
    "gender identity",
    "sexual orientation",
)


def _extract_boilerplate_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if any(marker in line.lower() for marker in _BOILERPLATE_KEYWORDS)]


def _strip_boilerplate_lines(lines: list[str], boilerplate: list[str]) -> str:
    boilerplate_set = set(boilerplate)
    return "\n".join(line for line in lines if line not in boilerplate_set)


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
