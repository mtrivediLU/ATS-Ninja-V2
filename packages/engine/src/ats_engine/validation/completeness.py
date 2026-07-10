from __future__ import annotations

import re
from typing import Any

from ats_engine.generation.latex_renderer import parse_resume_sections
from ats_engine.models import PipelineResult, Profile

"""Completeness validation.

Ensures the rendered outputs did not silently drop facts that exist in the
candidate's source profile — a resume that quietly loses an employer, bullets,
skills, education, or certifications is a truthfulness failure of a different
kind (omission), so it is treated as fatal downstream.
"""

EMPTY_LABEL_PATTERN = re.compile(
    r"(?:^|\|\s*)([A-Za-z][A-Za-z /&.-]{1,40}):\s*(?=\||$)",
    flags=re.MULTILINE,
)


def validate_completeness(result: PipelineResult, profile: Profile) -> list[str]:
    """Ensure rendered outputs did not silently drop source-profile facts."""
    errors: list[str] = []
    if result.resume_text:
        sections = parse_resume_sections(result.resume_text)
        errors.extend(_validate_resume_completeness(sections, profile))
        errors.extend(_validate_empty_labels(result.resume_text, "resume"))
    if result.resume_latex:
        errors.extend(_validate_empty_labels(_latex_to_textish(result.resume_latex), "resume latex"))
    if result.cover_letter_text:
        errors.extend(_validate_empty_labels(result.cover_letter_text, "cover letter"))
        errors.extend(_validate_cover_letter_coherence(result.cover_letter_text))
    if result.cover_letter_latex:
        errors.extend(_validate_empty_labels(_latex_to_textish(result.cover_letter_latex), "cover letter latex"))
    return _dedupe(errors)


def _validate_resume_completeness(sections: dict[str, Any], profile: Profile) -> list[str]:
    errors: list[str] = []
    source_experience_count = len(profile.experiences)
    source_bullet_count = sum(len(entry.bullets) for entry in profile.experiences)
    source_skill_count = len(_profile_skills(profile))
    output_experience_count = len(sections.get("experience") or [])
    output_bullet_count = sum(len(entry.get("bullets") or []) for entry in sections.get("experience") or [])
    output_skill_count = len(_rendered_skills(sections))

    if output_experience_count < source_experience_count:
        errors.append(
            f"completeness: resume has {output_experience_count} experience entries, source has {source_experience_count}"
        )
    if output_bullet_count < source_bullet_count:
        errors.append(
            f"completeness: resume has {output_bullet_count} experience bullets, source has {source_bullet_count}"
        )
    if output_skill_count < source_skill_count:
        errors.append(f"completeness: resume has {output_skill_count} skills, source has {source_skill_count}")
    if profile.education and not sections.get("education"):
        errors.append("completeness: source education exists but rendered resume has no education entries")
    if profile.certifications and not sections.get("certifications"):
        errors.append("completeness: source certifications exist but rendered resume has no certifications")
    return errors


def _profile_skills(profile: Profile) -> set[str]:
    return {
        _normalize_skill(skill)
        for skill in [*profile.tier_a.values(), *profile.tier_b.values(), *profile.tier_c.values()]
        if _normalize_skill(skill)
    }


def _rendered_skills(sections: dict[str, Any]) -> set[str]:
    skills: set[str] = set()
    for group in sections.get("skills") or []:
        for item in group.get("items") or []:
            normalized = _normalize_skill(item)
            if normalized:
                skills.add(normalized)
    return skills


def _validate_empty_labels(text: str, label: str) -> list[str]:
    errors: list[str] = []
    for match in EMPTY_LABEL_PATTERN.finditer(text or ""):
        field = match.group(1).strip()
        if field.lower() in {"http", "https"}:
            continue
        errors.append(f"completeness: {label} contains empty label '{field}:'")
    return errors


def _validate_cover_letter_coherence(text: str) -> list[str]:
    lowered = (text or "").lower()
    errors: list[str] = []
    if "i also the candidate" in lowered:
        errors.append("completeness: cover letter contains broken phrase 'I also the candidate'")
    if re.search(r"\bbased in\s+senior software engineer\b", lowered):
        errors.append("completeness: cover letter used a job title as the location")
    return errors


def _latex_to_textish(text: str) -> str:
    return (
        (text or "").replace(r"\&", "&").replace(r"\%", "%").replace(r"\$", "$").replace(r"\#", "#").replace(r"\_", "_")
    )


def _normalize_skill(skill: str) -> str:
    return re.sub(r"[.\s]+$", "", re.sub(r"\s+", " ", (skill or "").lower()).strip())


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out
