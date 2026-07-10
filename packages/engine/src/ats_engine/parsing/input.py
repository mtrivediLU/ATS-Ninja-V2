from __future__ import annotations

import re
from dataclasses import fields
from typing import Any

from ats_engine.models import ContactInfo, Mode, ParsedInput, Profile
from ats_engine.parsing.pdf import extract_text_from_pdf


def parse_input(
    *,
    uploaded_resume_pdf: Any | None = None,
    resume_text: str = "",
    job_description: str = "",
    overrides: dict[str, str] | None = None,
    logistics: dict[str, str] | None = None,
    questions_text: str = "",
    requested_mode: str = "",
    profile: Profile | None = None,
) -> ParsedInput:
    """Parse all user-provided inputs into a normalized pipeline input.

    Contact fields resolve with strict precedence: explicit user override, then
    whatever was extracted from the uploaded resume, then logistics overrides
    (availability, work mode, etc). There is no hardcoded default identity; a
    field is left blank if it truly is not present anywhere.
    """
    extracted_pdf_text = extract_text_from_pdf(uploaded_resume_pdf) if uploaded_resume_pdf else ""
    combined_resume_text = "\n\n".join(
        part.strip() for part in [resume_text, extracted_pdf_text] if part and part.strip()
    )
    extracted_contacts = extract_contacts(combined_resume_text)
    contacts = resolve_contacts(
        overrides=overrides or {},
        extracted=extracted_contacts,
        profile=profile,
        logistics=logistics or {},
    )
    questions = split_questions(questions_text)
    mode = detect_mode(
        requested_text=requested_mode,
        job_description=job_description,
        questions=questions,
    )
    return ParsedInput(
        resume_text=combined_resume_text,
        job_description=job_description.strip(),
        contacts=contacts,
        questions=questions,
        logistics=logistics or {},
        mode=mode,
    )


def extract_contacts(text: str) -> ContactInfo:
    """Extract likely contact fields from resume text."""
    text = text or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    email = _first_match(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    phone = _first_match(r"(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}", text)
    linkedin = _first_match(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?", text)
    website = _first_website(text, linkedin)
    location = _extract_location(lines)
    name = _extract_name(lines)
    return ContactInfo(
        name=name,
        phone=phone,
        email=email,
        linkedin=linkedin,
        website=website,
        location=location,
    )


def resolve_contacts(
    *,
    overrides: dict[str, str],
    extracted: ContactInfo,
    profile: Profile | None = None,
    logistics: dict[str, str] | None = None,
) -> ContactInfo:
    """Resolve contacts using override, then uploaded resume, then logistics precedence.

    There is no hardcoded default identity. A field stays blank if the user did
    not provide it and it was not found in the uploaded resume.
    """
    logistics = logistics or {}
    resolved = ContactInfo()
    source: dict[str, str] = {}
    valid_fields = {field.name for field in fields(ContactInfo)} - {"source"}
    retired_emails = {email.lower() for email in (profile.retired_emails if profile else [])}

    for key in valid_fields:
        override_value = _clean(overrides.get(key, ""))
        extracted_value = _clean(getattr(extracted, key, ""))
        logistics_value = _clean(logistics.get(key, ""))

        value = ""
        chosen_source = ""
        for candidate, candidate_source in [
            (override_value, "override"),
            (extracted_value, "uploaded_resume"),
            (logistics_value, "override"),
        ]:
            if candidate:
                value = candidate
                chosen_source = candidate_source
                break

        if key == "email" and value.lower() in retired_emails:
            value, chosen_source = "", ""

        setattr(resolved, key, value)
        if value:
            source[key] = chosen_source

    resolved.source = source
    return resolved


def detect_mode(
    *,
    requested_text: str = "",
    job_description: str = "",
    questions: list[str] | None = None,
) -> Mode:
    """Detect generation mode silently from user intent, JD, and questions."""
    requested = (requested_text or "").lower()
    questions = questions or []
    wants_cover = any(term in requested for term in ["cover letter", "covering letter", " cv "])
    if requested.strip() == "cv" or requested.startswith("cv ") or requested.endswith(" cv"):
        wants_cover = True
    wants_resume = "resume" in requested or "résumé" in requested
    wants_both = wants_cover and wants_resume or "both" in requested or "resume and cover" in requested

    if questions and job_description.strip():
        return Mode.RESUME_AND_QUESTIONS
    if questions:
        return Mode.QUESTIONS
    if wants_both:
        return Mode.RESUME_AND_COVER
    if wants_cover:
        return Mode.COVER_LETTER
    if job_description.strip():
        return Mode.RESUME
    return Mode.RESUME


def split_questions(text: str) -> list[str]:
    """Split application or screening questions into paste-ready prompts."""
    if not text or not text.strip():
        return []

    chunks = re.split(r"\n\s*\n|(?:^|\n)\s*(?:Q\d+[:.)]|\d+[.)])\s*", text.strip())
    questions = [re.sub(r"\s+", " ", chunk).strip() for chunk in chunks if chunk.strip()]
    return questions


def _extract_name(lines: list[str]) -> str:
    for line in lines[:5]:
        if "@" in line or "linkedin" in line.lower() or any(char.isdigit() for char in line):
            continue
        words = line.split()
        if 2 <= len(words) <= 4:
            return line
    return ""


_LOCATION_HINTS = re.compile(
    r"\b(remote|hybrid|on-site|onsite)\b"
    r"|\b[A-Z][A-Za-z.'\s]+,\s*[A-Z]{2}\b"
    r"|\b[A-Z][A-Za-z.'\s]+,\s*[A-Z][a-z]+\b",
)


def _extract_location(lines: list[str]) -> str:
    for line in lines[:12]:
        cleaned = re.sub(r"^(?:[*•#]\s*|\(cid:\d+\)\s*)", "", line).strip()
        if not cleaned or "|" in cleaned:
            continue
        if _looks_like_resume_location(cleaned):
            return cleaned
    return ""


_PROVINCES_AND_COUNTRIES = {
    "alberta",
    "british columbia",
    "manitoba",
    "new brunswick",
    "newfoundland",
    "northwest territories",
    "nova scotia",
    "nunavut",
    "ontario",
    "prince edward island",
    "quebec",
    "saskatchewan",
    "yukon",
    "canada",
    "united states",
    "usa",
    "india",
}


def _looks_like_resume_location(line: str) -> bool:
    lowered = line.lower()
    if any(mode in lowered for mode in ["remote", "hybrid", "on-site", "onsite"]):
        return True
    if any(place in lowered for place in _PROVINCES_AND_COUNTRIES):
        return bool(re.search(r"\b[A-Z][A-Za-z.'-]+,\s*[A-Z][A-Za-z.'-]+", line))
    return bool(re.search(r"\b[A-Z][A-Za-z.'-]+,\s*[A-Z]{2}\b", line))


def _first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(0).strip() if match else ""


def _first_website(text: str, linkedin: str) -> str:
    email_domains = {
        email.split("@", 1)[1].lower() for email in re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text) if "@" in email
    }
    pattern = re.compile(r"(?:https?://)?(?:www\.)?[A-Za-z0-9-]+\.[A-Za-z]{2,}(?:/[^\s|]*)?")
    for match in pattern.finditer(text):
        candidate = match.group(0)
        lowered = candidate.lower()
        if match.start() > 0 and text[match.start() - 1] == "@":
            continue
        if lowered in email_domains:
            continue
        if "linkedin.com" in lowered or "@" in lowered:
            continue
        if linkedin and candidate in linkedin:
            continue
        return candidate.strip().rstrip(".")
    return ""


def _clean(value: str | None) -> str:
    return str(value or "").strip()
