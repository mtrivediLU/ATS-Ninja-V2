from __future__ import annotations

import re
from typing import Any

from ats_engine.caching.content_hash import default_cache, make_key
from ats_engine.models import Certification, ContactInfo, Education, Experience, Profile
from ats_engine.parsing.line_refs import number_lines, render_numbered_lines, resolve_line_numbers
from ats_engine.providers.base import LLMProvider, generate_json

# Cache namespace for parsed profiles. Bump when parsing behavior changes so
# stale cached profiles are not served after a logic update.
PROFILE_CACHE_VERSION = "profile-v7-provider-source-floor"


class ExtractionSuspectError(RuntimeError):
    """Raised when parsed resume structure is unsafe to use for generation.

    The fixed code is intentionally the entire exception message: parser
    diagnostics can contain candidate-authored text and must not leak through
    API error persistence or logs.
    """

    code = "EXTRACTION_SUSPECT"

    def __init__(self) -> None:
        super().__init__(self.code)


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
    {{"name": "", "date": "", "link": "", "credential_id": ""}}
  ],
  "skills_listed": ["..."],
  "summary_text": ""
}}

Rules:
- experiences must stay in the order they appear in the resume.
- bullet_lines must be the exact line numbers shown below that belong to that entry's bullet points. Use [] if there are none.
- skills_listed must contain every individual tool, language, platform, framework, or technology named anywhere in the resume (skills section AND bullet lines), each as a short token like "Python" or "Power BI", no duplicates.
- For certifications, keep a source-written `Credential ID`/`Credential #` value in credential_id; otherwise use "". Do not treat a parenthesized vendor exam code as a credential ID.
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
        _raise_if_extraction_suspect(cached)
        return cached

    profile = extract_profile(text, provider=provider)
    _raise_if_extraction_suspect(profile)
    if profile.experiences or profile.tier_a:
        cache.set(key, profile)
    return profile


def _raise_if_extraction_suspect(profile: Profile) -> None:
    if profile.extraction_warnings:
        raise ExtractionSuspectError


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
    else:
        # The deterministic parse is an immutable evidence floor. Provider
        # output may improve the structure of an entry the source parser
        # already identified, but it may not replace or add candidate facts.
        # This boundary is deliberately earlier than ApplicationKit grounding:
        # structured resume fields are candidate evidence themselves.
        data = _merge_provider_data(heuristic_data, data, text)

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


_CONTACT_FIELDS = ("name", "email", "phone", "linkedin", "website", "location")
_EXPERIENCE_FIELDS = ("company", "title", "location", "dates")
_EDUCATION_FIELDS = ("institution", "degree", "location", "dates")
_CERTIFICATION_FIELDS = ("name", "date", "link", "credential_id")


def _merge_provider_data(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    source_text: str,
) -> dict[str, Any]:
    """Merge source-backed provider structure onto the deterministic floor.

    The provider is not an evidence source. Unmatched provider records are
    discarded, existing deterministic values are never overwritten, and a
    provider value can fill a blank only when it occurs in the source context
    for that exact deterministic record.
    """
    sections = _split_into_sections([line.strip() for line in source_text.splitlines()])
    merged = dict(baseline)
    merged["contact"] = _merge_provider_contact(
        baseline.get("contact"),
        candidate.get("contact"),
        source_text,
    )
    merged["experiences"] = _merge_provider_entries(
        baseline.get("experiences"),
        candidate.get("experiences"),
        sections.get("experience", []),
        identity_fields=("company", "title", "dates"),
        value_fields=_EXPERIENCE_FIELDS,
    )
    merged["education"] = _merge_provider_entries(
        baseline.get("education"),
        candidate.get("education"),
        sections.get("education", []),
        identity_fields=("institution", "degree", "dates"),
        value_fields=_EDUCATION_FIELDS,
    )
    merged["certifications"] = _merge_provider_entries(
        baseline.get("certifications"),
        candidate.get("certifications"),
        sections.get("certifications", []),
        identity_fields=("name",),
        value_fields=_CERTIFICATION_FIELDS,
    )
    merged["skills_listed"] = _merge_provider_skills(
        baseline.get("skills_listed"),
        candidate.get("skills_listed"),
        baseline,
        sections,
        source_text,
    )
    # An existing summary is already recovered verbatim by the deterministic
    # parser. A provider-authored paraphrase is prose, not resume evidence.
    merged["summary_text"] = str(baseline.get("summary_text", "") or "")
    return merged


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dict_entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(entry) for entry in value if isinstance(entry, dict)]


def _merge_provider_contact(baseline: Any, candidate: Any, source_text: str) -> dict[str, Any]:
    merged = _dict_value(baseline)
    proposed = _dict_value(candidate)
    contact_context = _contact_source_context(source_text)
    for field in _CONTACT_FIELDS:
        if str(merged.get(field, "") or "").strip():
            continue
        # Name parsing has no safe provider-only fill: an employer, school, or
        # headline in the header is also literal text but is not the candidate's
        # name. The deterministic parser owns that identity decision.
        if field == "name":
            continue
        value = _source_backed_provider_field(field, proposed.get(field), contact_context)
        if value:
            merged[field] = value
    return merged


def _contact_source_context(source_text: str) -> str:
    """Return only the resume header where candidate contact facts can occur."""
    lines: list[str] = []
    for raw_line in source_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _detect_heading(line) is not None:
            break
        lines.append(line)
        if len(lines) >= 10:
            break
    return "\n".join(lines)


def _merge_provider_entries(
    baseline: Any,
    candidate: Any,
    source_lines: list[str],
    *,
    identity_fields: tuple[str, ...],
    value_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    merged = _dict_entries(baseline)
    proposed = _dict_entries(candidate)
    contexts = _entry_source_contexts(source_lines, merged, identity_fields)

    for entry in proposed:
        match_index = _matching_source_entry(entry, merged, contexts, identity_fields)
        if match_index is None:
            # A literal phrase somewhere in the resume does not prove that it
            # belongs to a new role, school, or certification. Only a provider
            # record tied to a deterministic source record may be retained.
            continue
        target = merged[match_index]
        context = contexts[match_index]
        for field in value_fields:
            # Provider output cannot establish the identity of a role, school,
            # degree, or credential. Those fields are the match anchors owned
            # by deterministic parsing; only typed metadata gaps may be filled.
            if field in identity_fields:
                continue
            if str(target.get(field, "") or "").strip():
                continue
            value = _source_backed_provider_field(field, entry.get(field), context)
            if value:
                target[field] = value

        target_bullets = _string_list(target.get("bullets"))
        seen_bullets = {_normalize(_clean_bullet(value)) for value in target_bullets}
        for raw_bullet in _string_list(entry.get("bullets")):
            bullet = _clean_bullet(raw_bullet)
            if not bullet or not _source_contains_exact(context, bullet):
                continue
            normalized = _normalize(bullet)
            if normalized not in seen_bullets:
                target_bullets.append(bullet)
                seen_bullets.add(normalized)
        if target_bullets or "bullets" in target:
            target["bullets"] = target_bullets
    return merged


def _entry_source_contexts(
    source_lines: list[str],
    entries: list[dict[str, Any]],
    identity_fields: tuple[str, ...],
) -> list[str]:
    """Map deterministic entries to their local source spans in source order."""
    starts: list[int | None] = []
    cursor = 0
    for entry in entries:
        anchors = [
            str(entry.get(field, "") or "").strip()
            for field in identity_fields
            if str(entry.get(field, "") or "").strip()
        ]
        start = next(
            (
                index
                for index in range(cursor, len(source_lines))
                if any(_source_contains_exact(source_lines[index], anchor) for anchor in anchors)
            ),
            None,
        )
        starts.append(start)
        if start is not None:
            cursor = start + 1

    contexts: list[str] = []
    for index, start in enumerate(starts):
        if start is None:
            contexts.append("")
            continue
        next_start = next(
            (candidate for candidate in starts[index + 1 :] if candidate is not None),
            len(source_lines),
        )
        contexts.append("\n".join(source_lines[start:next_start]))
    return contexts


def _matching_source_entry(
    proposed: dict[str, Any],
    baseline: list[dict[str, Any]],
    contexts: list[str],
    identity_fields: tuple[str, ...],
) -> int | None:
    best_index: int | None = None
    best_score = 0
    for index, source_entry in enumerate(baseline):
        context = contexts[index]
        if not context:
            continue
        score = 0
        for field in identity_fields:
            proposed_value = _source_backed_text(proposed.get(field), context)
            source_value = str(source_entry.get(field, "") or "").strip()
            if proposed_value and source_value and _same_source_fact(proposed_value, source_value):
                score += 1
        if score > best_score:
            best_index = index
            best_score = score
    return best_index


def _same_source_fact(left: str, right: str) -> bool:
    normalized_left = _normalize(left).strip()
    normalized_right = _normalize(right).strip()
    if not normalized_left or not normalized_right:
        return False
    return normalized_left == normalized_right or (
        min(len(normalized_left), len(normalized_right)) >= 4
        and (normalized_left in normalized_right or normalized_right in normalized_left)
    )


def _merge_provider_skills(
    baseline_skills: Any,
    candidate_skills: Any,
    baseline: dict[str, Any],
    sections: dict[str, list[str]],
    source_text: str,
) -> list[str]:
    skills = _string_list(baseline_skills)
    evidence_parts = [
        _source_summary_text(source_text),
        *sections.get("skills", []),
        *sections.get("projects", []),
    ]
    for entry in _dict_entries(baseline.get("experiences")) + _dict_entries(baseline.get("education")):
        evidence_parts.extend(_string_list(entry.get("bullets")))
    for certification in _dict_entries(baseline.get("certifications")):
        evidence_parts.append(str(certification.get("name", "") or ""))
    evidence_text = "\n".join(evidence_parts)

    for skill in _string_list(candidate_skills):
        if term_in_text_affirmative(skill, evidence_text):
            skills.append(skill)
    return _dedupe_terms(skills)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _source_backed_text(value: Any, source_text: str) -> str:
    text = str(value or "").strip()
    return text if text and _source_contains_exact(source_text, text) else ""


def _source_backed_provider_field(field: str, value: Any, source_text: str) -> str:
    """Validate the literal value and its field-specific source shape."""
    text = _source_backed_text(value, source_text)
    if not text:
        return ""
    if field == "email":
        return text if _EMAIL.fullmatch(text) is not None else ""
    if field == "phone":
        return text if _PHONE.fullmatch(text) is not None else ""
    if field == "linkedin":
        return text if _LINKEDIN.fullmatch(text) is not None else ""
    if field in {"website", "link"}:
        return text if _URL.fullmatch(text) is not None else ""
    if field == "dates":
        return text if _DATE_RANGE.fullmatch(text) is not None else ""
    if field == "date":
        return text if _YEAR.search(text) is not None else ""
    if field == "credential_id":
        _, source_credential_id = _split_credential_id(source_text)
        return text if _same_source_fact(text, source_credential_id) else ""
    if field == "location":
        is_named_location = _LOCATION_TAIL.fullmatch(text) is not None
        is_work_mode = text.lower() in {"remote", "hybrid", "on-site", "onsite"}
        return text if is_named_location or is_work_mode else ""
    return ""


def _source_contains_exact(source_text: str, value: str) -> bool:
    normalized_value = _normalize(value).strip()
    if not normalized_value:
        return False
    if normalized_value in _normalize(source_text):
        return True
    # PDF extraction commonly leaves a hard line break after a source-written
    # hyphen (``Zoom-\nInfo``). The deterministic parser rejoins that exact
    # token as ``Zoom-Info``; accept only this narrow, source-preserving
    # de-wrapping—not fuzzy token overlap.
    dewrapped_source = re.sub(r"-[ \t]*\r?\n[ \t]*(?=[A-Za-z0-9])", "-", source_text)
    return normalized_value in _normalize(dewrapped_source)


def _build_profile(data: dict[str, Any], source_text: str) -> Profile:
    contact_data = data.get("contact") or {}
    contact = ContactInfo(
        name=_source_backed_text(contact_data.get("name"), source_text),
        email=_source_backed_text(contact_data.get("email"), source_text),
        phone=_source_backed_text(contact_data.get("phone"), source_text),
        linkedin=_source_backed_text(contact_data.get("linkedin"), source_text),
        website=_source_backed_text(contact_data.get("website"), source_text),
        location=_source_backed_text(contact_data.get("location"), source_text),
    )

    experiences = _clean_experiences(data.get("experiences") or [], source_text)
    education = _clean_education(data.get("education") or [], source_text)
    # Skill taxonomy is source evidence in its own right.  Preserve the
    # candidate-authored groups even when an LLM supplied a flatter skill list
    # (or omitted some entries).  The flat list remains the compatibility
    # surface used by the existing evidence matrix.
    source_sections = _split_into_sections([line.strip() for line in source_text.splitlines()])
    source_summary = _source_summary_text(source_text)
    source_skill_groups = _heuristic_skill_groups(source_sections.get("skills", []))
    remaining_sections = _remaining_sections(source_sections)
    source_skills = [item for _, items in source_skill_groups for item in items]
    skills_listed = _dedupe_terms(
        [
            str(skill)
            for skill in (data.get("skills_listed") or [])
            if str(skill).strip() and term_in_text_affirmative(str(skill), source_text)
        ]
        + source_skills
    )

    # Certification identifiers are often omitted by an LLM because they look
    # like opaque metadata.  Enrich the structured parse from the raw source so
    # the identifier is retained as candidate evidence rather than discarded.
    certifications = _clean_certifications(data.get("certifications") or [], source_text)
    certifications = _merge_source_certifications(
        certifications,
        _clean_certifications(
            _heuristic_certifications(source_sections.get("certifications", [])),
            source_text,
        ),
    )
    summary_text = source_summary

    tier_a, tier_b, tier_c = _tier_skills(skills_listed, experiences, summary_text)
    supported_metrics = _extract_supported_metrics(experiences)
    role_identities = _dedupe_terms([exp.title for exp in experiences if exp.title])
    extraction_warnings = [
        f"EXTRACTION_SUSPECT: implausible employer header '{experience.company}'"
        for experience in experiences
        if _company_header_is_suspect(experience.company)
    ]

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
        source_summary=source_summary,
        source_skill_groups=source_skill_groups,
        remaining_sections=remaining_sections,
        extraction_warnings=extraction_warnings,
    )


def _clean_experiences(raw_entries: list[Any], source_text: str) -> list[Experience]:
    experiences: list[Experience] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        company = _source_backed_text(entry.get("company"), source_text)
        title = _source_backed_text(entry.get("title"), source_text)
        if not company and not title:
            continue
        bullets = [
            _clean_bullet(bullet)
            for bullet in _string_list(entry.get("bullets"))
            if _clean_bullet(bullet) and _source_contains_exact(source_text, _clean_bullet(bullet))
        ]
        experiences.append(
            Experience(
                company=company or title,
                title=title,
                location=_source_backed_text(entry.get("location"), source_text),
                dates=_source_backed_text(entry.get("dates"), source_text),
                bullets=bullets,
            )
        )
    return experiences


def _clean_education(raw_entries: list[Any], source_text: str) -> list[Education]:
    education: list[Education] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        institution = _source_backed_text(entry.get("institution"), source_text)
        degree = _source_backed_text(entry.get("degree"), source_text)
        if not institution and not degree:
            continue
        bullets = [
            _clean_bullet(bullet)
            for bullet in _string_list(entry.get("bullets"))
            if _clean_bullet(bullet) and _source_contains_exact(source_text, _clean_bullet(bullet))
        ]
        education.append(
            Education(
                institution=institution or degree,
                location=_source_backed_text(entry.get("location"), source_text),
                degree=degree,
                dates=_source_backed_text(entry.get("dates"), source_text),
                bullets=bullets,
            )
        )
    return education


def _clean_certifications(raw_entries: list[Any], source_text: str) -> list[Certification]:
    certifications: list[Certification] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        name, embedded_credential_id = _split_credential_id(str(entry.get("name", "")))
        name = _source_backed_text(name, source_text)
        if not name:
            continue
        credential_id = str(entry.get("credential_id", "")).strip() or embedded_credential_id
        certifications.append(
            Certification(
                name=name,
                date=_source_backed_text(entry.get("date"), source_text),
                link=_source_backed_text(entry.get("link"), source_text),
                credential_id=_source_backed_text(credential_id, source_text),
            )
        )
    return certifications


def _merge_source_certifications(parsed: list[Certification], source: list[Certification]) -> list[Certification]:
    """Fill missing cert metadata from the deterministic source parse.

    The LLM parser may improve visual structure, but source-provided
    credential IDs must never be lost merely because they are opaque strings.
    Conversely, an ID emitted only by an LLM is not evidence and is discarded.
    Matching is intentionally conservative: exact normalized name first, then
    a shared parenthesized credential code such as ``PL-300``.
    """
    if not source:
        return []

    remaining = list(source)
    merged: list[Certification] = []
    for certification in parsed:
        match_index = next(
            (
                index
                for index, candidate in enumerate(remaining)
                if _certification_keys(candidate.name) & _certification_keys(certification.name)
            ),
            None,
        )
        if match_index is None:
            # The provider cannot establish a new certification record. Even a
            # literal token elsewhere in the resume may be aspirational or name
            # a target credential rather than one the candidate holds.
            continue
        candidate = remaining.pop(match_index)
        merged.append(
            Certification(
                name=certification.name,
                date=certification.date or candidate.date,
                link=certification.link or candidate.link,
                credential_id=candidate.credential_id,
            )
        )

    # A deterministic source parse can recognize a certification the model
    # skipped entirely.  Preserve it instead of lowering the evidence floor.
    merged.extend(remaining)
    return merged


def _certification_keys(name: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    keys = {normalized} if normalized else set()
    keys.update(match.lower() for match in re.findall(r"\b[A-Za-z]{1,5}-\d{2,5}\b", name or ""))
    return keys


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
        if term_in_text_affirmative(normalized, bullet_text):
            tier_a[normalized] = skill
        elif term_in_text_affirmative(normalized, summary_lower):
            tier_b[normalized] = skill
        else:
            tier_c[normalized] = skill
    return tier_a, tier_b, tier_c


METRIC_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?%"
    # Do not let ``\s`` bridge a line boundary: a certification year followed
    # by the next certification's name (for example ``2024\nPlatform``) is not
    # a candidate metric.
    r"|\b\d+\+?[ \t]*(?:years?|engineers?|clients?|users?|customers?|platforms?|projects?|hours?)\b"
    r"|\b\d+[ \t]*(?:to|-)[ \t]*\d+[ \t]*(?:hours?|minutes?|days?)\b"
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


# A bare word-boundary match cannot distinguish "Built systems using Kubernetes"
# from "I have no Kubernetes experience" or "currently exploring Rust" — both
# contain the term but assert the OPPOSITE, or a non-current capability. Every
# caller that treats a term's presence in candidate-authored text as *proof* of
# a skill (evidence tiering) must use the affirmative-clause-aware check below
# instead of a raw substring/word-boundary test.
_NEGATION_OR_ASPIRATION = re.compile(
    r"\b(?:no|not|never|without|lack(?:s|ing)?|isn.t|wasn.t|aren.t|weren.t|doesn.t|don.t|didn.t|"
    r"haven.t|hasn.t|hadn.t|"
    r"currently\s+(?:exploring|learning|studying)|exploring|learning|studying|"
    r"planning\s+to|hop(?:e|ing)\s+to|aspir(?:e|ing)\s+to|interested\s+in|considering|"
    r"want(?:s|ing)?\s+to|would\s+like\s+to|looking\s+to|not\s+yet|in\s+progress)\b",
    re.IGNORECASE,
)


def term_in_text_affirmative(term: str, text: str) -> bool:
    """True when ``term`` appears in an affirmative clause of ``text``.

    Evidence tiering must never treat a negated ("no Kubernetes experience") or
    aspirational ("currently exploring Rust", "interested in AWS certification")
    mention as proof of a candidate skill. The check is clause-scoped (split on
    sentence/semicolon boundaries) so a negation elsewhere in a multi-clause
    bullet does not suppress genuine evidence in another clause of the same line.

    Case-insensitive regardless of caller normalization, matching the
    case-insensitive behavior callers have always relied on for this check.
    """
    lowered_term = (term or "").lower()
    for clause in re.split(r"[.!?;\n]+", (text or "").lower()):
        if term_in_text(lowered_term, clause) and not _NEGATION_OR_ASPIRATION.search(clause):
            return True
    return False


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


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
    "publications": {"publications", "selected publications", "research publications"},
    "projects": {"projects", "selected projects", "technical projects"},
    "awards": {"awards", "honours", "honors", "awards and honours", "awards and honors"},
    "volunteering": {"volunteering", "volunteer experience", "community involvement"},
}

_REMAINING_SECTION_LABELS = {
    "publications": "Publications",
    "projects": "Projects",
    "awards": "Awards",
    "volunteering": "Volunteer Experience",
}

_DATE_RANGE = re.compile(
    r"((?:\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+)?\d{4})"
    r"\s*(?:-|to|–|—)\s*"
    r"(Present|Current|(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+)?\d{4})",
    flags=re.IGNORECASE,
)

_LOCATION_TAIL = re.compile(
    r"(?P<location>[A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]*){0,2},\s*"
    r"(?:[A-Z]{2}|[A-Z][A-Za-z]+)(?:,\s*(?:[A-Z]{2}|[A-Z][A-Za-z]+))?)\s*$"
)
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_URL = re.compile(r"(https?://[^\s|]+|www\.[^\s|]+)", flags=re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}")
_LINKEDIN = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?", flags=re.IGNORECASE)
_CREDENTIAL_ID_SEGMENT = re.compile(
    r"(?:\s*(?:\||;|[-–—])\s*)?"
    r"(?:credential|certification)\s*(?:id|identifier|#)\s*[:#]?\s*"
    r"(?P<credential_id>[^|;]+?)\s*(?=(?:\||;|$))",
    flags=re.IGNORECASE,
)
_ORPHAN_BULLET_CONTINUATION = re.compile(
    r"^[A-Za-z0-9+#./ -]{1,80},\s*"
    r"(?:configuring|using|with|for|and|or|to|which|that|including|ensuring|supporting)\b",
    flags=re.IGNORECASE,
)
_SOURCE_SKILL_HEADING_HINTS = {
    "analytics",
    "backend",
    "business intelligence",
    "cloud",
    "databases",
    "devops",
    "frameworks",
    "frontend",
    "languages",
    "libraries",
    "methodologies",
    "platforms",
    "programming languages",
    "skills",
    "technologies",
    "tools",
}


def _heuristic_extract(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines()]
    sections = _split_into_sections(lines)
    skill_groups = _heuristic_skill_groups(sections.get("skills", []))

    return {
        "contact": _heuristic_contact(text),
        "experiences": _heuristic_entries(sections.get("experience", []), kind="experience"),
        "education": _heuristic_entries(sections.get("education", []), kind="education"),
        "certifications": _heuristic_certifications(sections.get("certifications", [])),
        "skills_listed": _dedupe_terms([item for _, items in skill_groups for item in items]),
        "skill_groups": skill_groups,
        "summary_text": _source_summary_text(text),
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


def _remaining_sections(sections: dict[str, list[str]]) -> list[tuple[str, list[str]]]:
    """Return source-authored non-core sections without changing their text."""
    output: list[tuple[str, list[str]]] = []
    for section, label in _REMAINING_SECTION_LABELS.items():
        values = [_clean_bullet(line) for line in sections.get(section, []) if _clean_bullet(line)]
        if values:
            output.append((label, values))
    return output


def _source_summary_text(text: str) -> str:
    """Return an explicit summary section without accidentally including contact lines."""
    collecting = False
    summary_lines: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = _detect_heading(line)
        if heading == "summary":
            collecting = True
            continue
        if heading is not None:
            if collecting:
                break
            continue
        if collecting:
            summary_lines.append(line)
    return " ".join(summary_lines).strip()


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
        location, head_without_location = _split_location_tail(head)
        if location:
            entry["location"] = entry["location"] or (location + suffix)
            head = head_without_location
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
            location, remainder_without_location = _split_location_tail(remainder)
            if location:
                current["location"] = location
                remainder = remainder_without_location
            if remainder:
                current[secondary] = remainder
            # A valid resume header is a company/institution line plus an
            # optional title/degree immediately before its dates.  Restrict
            # the parser to that local context so a PDF wrap orphan cannot be
            # promoted into an employer for the next role.
            apply_header(current, header_buffer[-2:])
            header_buffer = []
            continue

        if _is_bullet(line):
            if current is None:
                current = new_entry()
                apply_header(current, header_buffer)
                header_buffer = []
            current["bullets"].append(line)
            continue

        if (
            current is not None
            and current["bullets"]
            and (
                line[0].islower()
                or _ORPHAN_BULLET_CONTINUATION.search(line) is not None
                or current["bullets"][-1].rstrip().endswith("-")
            )
        ):
            separator = "" if current["bullets"][-1].rstrip().endswith("-") else " "
            current["bullets"][-1] = f"{current['bullets'][-1]}{separator}{line}"
        else:
            header_buffer.append(line)

    finalize(current)
    if not entries and header_buffer:
        # No date lines and no bullets found; treat the block as one entry.
        entry = new_entry()
        apply_header(entry, header_buffer)
        finalize(entry)
    return entries


def _company_header_is_suspect(value: str) -> bool:
    """Flag an extraction-shaped continuation mistaken for an employer name."""
    normalized = re.sub(r"\s+", " ", value or "").strip()
    lowered = normalized.casefold()
    if not normalized:
        return False
    if re.search(r",\s*(?:configuring|using|building|maintaining|supporting|ensuring)\b", lowered):
        return True
    return normalized.endswith(".") and len(normalized.split()) > 6


def _heuristic_certifications(lines: list[str]) -> list[dict[str, str]]:
    certifications: list[dict[str, str]] = []
    for line in lines:
        if not line:
            continue
        name, credential_id = _split_credential_id(line)
        year_match = _YEAR.search(name)
        url_match = _URL.search(name)
        if year_match:
            name = (name[: year_match.start()] + name[year_match.end() :]).strip(" |-")
        if url_match:
            name = name.replace(url_match.group(0), "").strip(" |-")
        name = name.strip(" |-:")
        if not name:
            continue
        certifications.append(
            {
                "name": name,
                "date": year_match.group(0) if year_match else "",
                "link": url_match.group(0) if url_match else "",
                "credential_id": credential_id,
            }
        )
    return certifications


def _heuristic_skills(lines: list[str]) -> list[str]:
    return _dedupe_terms([item for _, items in _heuristic_skill_groups(lines) for item in items])


def _heuristic_skill_groups(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Parse source skill headings and items without inventing a taxonomy.

    Resume writers commonly use one ``Heading: item, item`` line per group;
    some put a heading on one line and its items below.  Preserve both the
    headings and their source order, while applying only mechanical separator
    cleanup to individual entries.
    """
    groups: list[tuple[str, list[str]]] = []
    active_label = ""

    def add_items(label: str, raw_content: str) -> None:
        items = _skill_items(raw_content)
        if not items:
            return
        normalized_label = label.strip().rstrip(":") or "Skills"
        for index, (existing_label, existing_items) in enumerate(groups):
            if existing_label.lower() == normalized_label.lower():
                groups[index] = (existing_label, _dedupe_terms(existing_items + items))
                return
        groups.append((normalized_label, _dedupe_terms(items)))

    for index, raw_line in enumerate(lines):
        line = raw_line.strip().strip("•*- ")
        if not line:
            continue
        if ":" in line:
            maybe_label, content = line.split(":", 1)
            if maybe_label.strip() and len(maybe_label.strip()) <= 48:
                active_label = maybe_label.strip()
                add_items(active_label, content)
                continue
        if _looks_like_skill_heading(line) and _is_source_skill_heading(lines, index, line):
            active_label = line.rstrip(":")
            continue
        add_items(active_label, line)

    return groups


def _skill_items(content: str) -> list[str]:
    parts = re.split(r"[,;|]|\s{2,}|•|\*", content)
    items: list[str] = []
    for part in parts:
        cleaned = _clean_skill_item(part)
        if cleaned:
            items.append(cleaned)
    return items


def _clean_skill_item(value: str) -> str:
    """Keep a source skill token while discarding conversational fragments."""
    cleaned = value.strip().strip(".,;|")
    cleaned = re.sub(
        r"^(?:(?:pragmatic|practical|working)\s+)?use\s+of\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^(?:and|or|of|with|for)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip().strip(".,;|")
    if not cleaned or len(cleaned) > 80:
        return ""
    if not re.search(r"[A-Za-z0-9]", cleaned):
        return ""
    normalized = re.sub(r"[^a-z]+", " ", cleaned.casefold()).strip()
    if normalized in {"and", "or", "of", "with", "for", "use", "use of", "pragmatic use"}:
        return ""
    return cleaned


def _looks_like_skill_heading(line: str) -> bool:
    words = line.strip().rstrip(":").split()
    if not words or len(words) > 5 or any(character.isdigit() for character in line):
        return False
    return all(word[:1].isupper() or word.lower() in {"&", "and", "of"} for word in words)


def _is_source_skill_heading(lines: list[str], index: int, line: str) -> bool:
    """Avoid misclassifying a one-skill-per-line list as a taxonomy heading."""
    normalized = line.strip().rstrip(":").casefold()
    if normalized in _SOURCE_SKILL_HEADING_HINTS:
        return True
    for candidate in lines[index + 1 :]:
        next_line = candidate.strip().strip("•*- ")
        if not next_line:
            continue
        # A delimiter-bearing next line is clearly a list of items under the
        # current heading.  A new ``Heading: ...`` line is not.
        return ":" not in next_line and bool(re.search(r"[,;|•*]", next_line))
    return False


def _split_credential_id(value: str) -> tuple[str, str]:
    """Separate a labeled credential identifier from display text.

    Certification names frequently include vendor codes in parentheses
    (``PL-300``); those are part of the name and are deliberately retained.
    Only an explicit ``Credential ID``/``Credential #`` label becomes the
    separate verification identifier.
    """
    match = _CREDENTIAL_ID_SEGMENT.search(value or "")
    if match is None:
        return (value or "").strip(), ""
    credential_id = match.group("credential_id").strip(" |-:")
    without_identifier = (value[: match.start()] + value[match.end() :]).strip(" |;-:")
    return without_identifier, credential_id


def _split_location_tail(value: str) -> tuple[str, str]:
    """Return ``(location, remaining_header)`` for a plausible location tail.

    A conventional greedy regex turns ``Northstar Medical Toronto, ON`` into
    one giant location.  Consider each capitalized token boundary and choose
    the rightmost valid city/region tail instead.  Municipal employer names
    such as ``City of Greater Sudbury, ON`` remain intact unless the city is
    repeated as an actual location suffix.
    """
    text = value.strip()
    # A pipe is an explicit column boundary in common resume layouts. Honor it
    # before the capitalized-tail heuristic so a multi-word city such as
    # ``Harbor City, ON`` is not truncated to ``City, ON`` and left attached to
    # the employer as ``Northstar Medical Systems | Harbor``.
    if "|" in text:
        remainder, candidate = (part.strip() for part in text.rsplit("|", 1))
        match = _LOCATION_TAIL.fullmatch(candidate)
        if remainder and match is not None:
            return match.group("location").strip(), remainder

    candidates: list[tuple[int, str]] = []
    for start_match in re.finditer(r"(?<!\S)[A-Z]", text):
        match = _LOCATION_TAIL.match(text[start_match.start() :])
        if match is not None:
            candidates.append((start_match.start(), match.group("location").strip()))
    if not candidates:
        return "", text

    start, location = candidates[-1]
    remainder = text[:start].strip(" |-,")
    if not remainder:
        return "", text

    municipal = re.match(r"^(?:city|town|county|regional municipality)\s+of\s+", text, flags=re.IGNORECASE)
    if municipal is not None:
        city_tokens = re.sub(r",.*$", "", location).lower().split()
        prefix_tokens = remainder.lower().split()
        if city_tokens and city_tokens[-1] not in prefix_tokens:
            return "", text

    return location, remainder


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
    # `\s*` (not `\s+`) after the marker: PDF text extraction frequently
    # reconstructs a bullet glyph immediately adjacent to its text with no
    # literal space character (the visual gap comes from glyph positioning,
    # not a space codepoint). Requiring trailing whitespace here caused
    # genuine bullets to be misread as plain header text, which then made
    # their whole entry look bulletless downstream. `_clean_bullet` below
    # already strips the marker with `\s*` for the same reason.
    return bool(re.match(r"^\s*[\-*•]\s*\S", line))
