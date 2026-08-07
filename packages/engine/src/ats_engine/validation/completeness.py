from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from ats_engine.generation.latex_renderer import parse_resume_sections
from ats_engine.models import PipelineResult, Profile, RemovedContent

"""Completeness validation.

Ensures the rendered outputs did not silently drop facts that exist in the
candidate's source profile — a resume that quietly loses an employer, bullets,
skills, education, or certifications is a truthfulness failure of a different
kind (omission), so it is treated as fatal downstream.

**Ledger awareness.** The operative word above is *silently*. As of the
pruning step an accepted ``PRUNE`` may deliberately remove a low-relevance
bullet, and that removal is recorded, reversible, and shown to the user. The
gate therefore distinguishes a *ledgered* removal from a silent loss instead
of treating every disappearance as fatal. This is deliberately not a
weakening, and the asymmetry is worth stating precisely:

* A ledger entry excuses **exactly** the bullet it names, and only after this
  module has verified both halves of its claim -- that the named text really
  is in the candidate's source, and that it really is absent from the render.
  A fabricated entry (naming text the source never had) and a false entry
  (naming text that is still on the page) are both errors in their own right.
* Because each excused bullet must be *individually* proven absent, and the
  surviving count must still match source-minus-ledger, the two checks
  together pin down the missing set exactly. A render that drops bullet Y
  while the ledger claims bullet X still fails, even though the arithmetic
  alone would balance -- which is the laundering route a count-only allowance
  would have opened.
* With no ledger (the default, and every caller that predates pruning) the
  behavior is bit-for-bit what it always was: any shortfall is fatal.
"""

EMPTY_LABEL_PATTERN = re.compile(
    r"(?:^|\|\s*)([A-Za-z][A-Za-z /&.-]{1,40}):\s*(?=\||$)",
    flags=re.MULTILINE,
)


def validate_completeness(
    result: PipelineResult,
    profile: Profile,
    removed: Sequence[RemovedContent] = (),
) -> list[str]:
    """Ensure rendered outputs did not silently drop source-profile facts.

    ``removed`` is the accepted-removal ledger for this render (see
    :class:`~ats_engine.models.RemovedContent` and the module docstring).
    Defaulting it to empty keeps every existing caller on the original,
    strictest behavior.
    """
    errors: list[str] = []
    if result.resume_text:
        sections = parse_resume_sections(result.resume_text)
        errors.extend(_validate_resume_completeness(sections, profile, removed, result.resume_text))
        errors.extend(_validate_empty_labels(result.resume_text, "resume"))
    if result.resume_latex:
        errors.extend(_validate_empty_labels(_latex_to_textish(result.resume_latex), "resume latex"))
    if result.cover_letter_text:
        errors.extend(_validate_empty_labels(result.cover_letter_text, "cover letter"))
        errors.extend(_validate_cover_letter_coherence(result.cover_letter_text))
    if result.cover_letter_latex:
        errors.extend(_validate_empty_labels(_latex_to_textish(result.cover_letter_latex), "cover letter latex"))
    return _dedupe(errors)


def resume_completeness_errors(
    resume_text: str,
    profile: Profile,
    removed: Sequence[RemovedContent] = (),
) -> list[str]:
    """Completeness errors for a rendered resume text against its source profile.

    The text-only entry point (no ``PipelineResult`` needed) used by the change-
    action rebuild so a persisted revision is held to the same completeness bar as
    initial generation: no source employer, distinct bullet, skill, education, or
    certification may silently disappear.

    ``removed`` carries the same accepted-removal ledger as
    :func:`validate_completeness`, so a persisted revision cannot launder a
    removal through a rebuild: the rebuild must present the *same* verified
    ledger, and an unledgered drop still fails here exactly as it does on the
    initial generation path."""
    if not resume_text.strip():
        return []
    sections = parse_resume_sections(resume_text)
    errors = _validate_resume_completeness(sections, profile, removed, resume_text)
    errors.extend(_validate_empty_labels(resume_text, "resume"))
    return _dedupe(errors)


def _normalize_bullet(text: str) -> str:
    """Comparison key for bullet identity, tolerant of render-time reflow.

    Whitespace and punctuation are dropped rather than merely collapsed: the
    real fixtures carry soft-hyphen line-wrap artifacts ("specifi-cations")
    from PDF extraction, and a bullet must be recognizable as the same bullet
    whether or not the renderer re-wrapped it.
    """
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _ledgered_bullet_removals(
    removed: Sequence[RemovedContent],
    profile: Profile,
    rendered_text: str,
) -> tuple[int, list[str]]:
    """Verify each claimed bullet removal; return (allowance, errors).

    The allowance is the number of removals this function was able to *prove*
    -- present in the source, absent from the render. A claim that fails
    either half raises its own error and grants no allowance, so a bad ledger
    can never widen the count comparison below.
    """
    errors: list[str] = []
    allowance = 0
    source_keys = {
        _normalize_bullet(bullet)
        for experience in profile.experiences
        for bullet in experience.bullets
        if _normalize_bullet(bullet)
    }
    rendered_key = _normalize_bullet(rendered_text)
    for item in removed:
        if item.kind != "bullet":
            continue
        key = _normalize_bullet(item.original_text)
        if not key:
            errors.append(f"completeness: removal ledger entry at {item.location} records no original text")
            continue
        if key not in source_keys:
            errors.append(
                f"completeness: removal ledger at {item.location} names text that is not a source bullet: "
                f"{item.original_text!r}"
            )
            continue
        if key in rendered_key:
            errors.append(
                f"completeness: removal ledger at {item.location} claims a removal that is still rendered: "
                f"{item.original_text!r}"
            )
            continue
        allowance += 1
    return allowance, errors


def _validate_resume_completeness(
    sections: dict[str, Any],
    profile: Profile,
    removed: Sequence[RemovedContent] = (),
    rendered_text: str = "",
) -> list[str]:
    errors: list[str] = []
    source_experience_count = len(profile.experiences)
    # Count *distinct* source bullets per entry. The rendered resume is re-parsed
    # by ``parse_resume_sections``, which deduplicates identical bullet lines
    # within an entry, so comparing against a raw (un-deduplicated) source count
    # would falsely flag a candidate's own duplicate bullet as lost content and
    # withhold an otherwise valid resume. Counting distinct bullets keeps the
    # comparison apples-to-apples: a genuinely dropped *distinct* bullet still
    # lowers the output count below the source and is still caught below.
    source_bullet_count = sum(len(_distinct_bullets(entry.bullets)) for entry in profile.experiences)
    source_skill_count = len(_profile_skills(profile))
    output_experience_count = len(sections.get("experience") or [])
    output_bullet_count = sum(len(entry.get("bullets") or []) for entry in sections.get("experience") or [])
    output_skill_count = len(_rendered_skills(sections))
    # Only *proven* removals reduce what the render is required to contain.
    # An experience entry is never excusable this way: pruning may empty no
    # role and remove no role, so the entry comparison stays absolute.
    bullet_allowance, ledger_errors = _ledgered_bullet_removals(removed, profile, rendered_text)
    errors.extend(ledger_errors)

    if output_experience_count < source_experience_count:
        errors.append(
            f"completeness: resume has {output_experience_count} experience entries, source has {source_experience_count}"
        )
    if output_bullet_count < source_bullet_count - bullet_allowance:
        expected = source_bullet_count - bullet_allowance
        ledgered = f" ({bullet_allowance} ledgered removal(s) allowed for)" if bullet_allowance else ""
        errors.append(
            f"completeness: resume has {output_bullet_count} experience bullets, source has {source_bullet_count}"
            f"{ledgered}, expected at least {expected}"
        )
    if output_skill_count < source_skill_count:
        errors.append(f"completeness: resume has {output_skill_count} skills, source has {source_skill_count}")
    if profile.education and not sections.get("education"):
        errors.append("completeness: source education exists but rendered resume has no education entries")
    if profile.certifications and not sections.get("certifications"):
        errors.append("completeness: source certifications exist but rendered resume has no certifications")
    return errors


def _distinct_bullets(bullets: list[str]) -> list[str]:
    """Distinct bullets within one entry, keyed the same way the resume parser
    deduplicates them (case-insensitive, whitespace-trimmed)."""
    seen: set[str] = set()
    distinct: list[str] = []
    for bullet in bullets:
        key = (bullet or "").lower().strip()
        if key and key not in seen:
            seen.add(key)
            distinct.append(bullet)
    return distinct


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
