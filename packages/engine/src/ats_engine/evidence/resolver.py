"""Source-aware requirement resolution for Tailoring Engine v2."""

from __future__ import annotations

from ats_engine.evidence.adjacency import find_category
from ats_engine.models import EvidenceLink, Profile, RequirementTerm
from ats_engine.parsing.resume import term_in_text_affirmative
from ats_engine.parsing.vocab import (
    aliases_for,
    certification_codes,
    certification_implications,
    normalize_term,
)


def resolve_requirements(
    requirements: list[RequirementTerm],
    profile: Profile,
    raw_resume_text: str,
) -> list[EvidenceLink]:
    """Resolve typed JD requirements strictly against candidate source evidence.

    ``raw_resume_text`` is accepted as an explicit provenance boundary, but is
    not blindly keyword-scanned: unstructured trailing text (including a pasted
    JD) must not become candidate evidence.  Resolution uses the parser's
    structured experiences, summary tier, skills taxonomy, and certifications.
    """
    del raw_resume_text
    return [_resolve_one(requirement, profile) for requirement in requirements]


def _resolve_one(requirement: RequirementTerm, profile: Profile) -> EvidenceLink:
    # Strongest source: an affirmative, structured experience bullet.
    for exp_index, experience in enumerate(profile.experiences):
        for bullet_index, bullet in enumerate(experience.bullets):
            match_type = _match_type(requirement, bullet)
            if match_type:
                return _link(
                    requirement,
                    tier="A",
                    span=bullet,
                    location=f"experience:{exp_index}:bullet:{bullet_index}",
                    match_type=match_type,
                    placement="bullet",
                )

    # Tier B is deliberately sourced from the parser's existing summary map,
    # not arbitrary raw prose, so an appended JD cannot become summary evidence.
    for key, display in profile.tier_b.items():
        match_type = _match_type(requirement, f"{key} {display}")
        if match_type:
            return _link(
                requirement,
                tier="B",
                span=display,
                location="summary",
                match_type=match_type,
                placement="summary",
            )

    # Preserve source taxonomy when available; tier maps are a compatibility
    # fallback for profiles parsed before v2.
    for group_index, (_heading, items) in enumerate(profile.source_skill_groups):
        for item_index, item in enumerate(items):
            match_type = _match_type(requirement, item)
            if match_type:
                return _link(
                    requirement,
                    tier="C",
                    span=item,
                    location=f"skills:{group_index}:{item_index}",
                    match_type=match_type,
                    placement="skills",
                )
    for key, display in {**profile.tier_c, **profile.tier_a, **profile.tier_b}.items():
        match_type = _match_type(requirement, f"{key} {display}")
        if match_type:
            return _link(
                requirement,
                tier="C",
                span=display,
                location="skills",
                match_type=match_type,
                placement="skills",
            )

    for certification in profile.certifications:
        implied = {normalize_term(term) for term in certification_implications(certification)}
        if normalize_term(requirement.canonical) not in implied:
            continue
        codes = ", ".join(certification_codes(certification))
        span = certification.name if not codes else f"{certification.name} ({codes})"
        return _link(
            requirement,
            tier="cert",
            span=span,
            location="certification",
            match_type="cert_implies",
            placement="summary",
        )

    adjacency = _adjacent_evidence(requirement, profile)
    if adjacency:
        return EvidenceLink(
            requirement=requirement,
            tier="adjacency",
            resume_span=adjacency,
            resume_location="adjacent_source",
            match_type="adjacent_tool",
            surface_to_use="",
            max_placement="none",
        )
    return EvidenceLink(requirement=requirement, tier="missing")


def _link(
    requirement: RequirementTerm,
    *,
    tier: str,
    span: str,
    location: str,
    match_type: str,
    placement: str,
) -> EvidenceLink:
    return EvidenceLink(
        requirement=requirement,
        tier=tier,
        resume_span=span,
        resume_location=location,
        match_type=match_type,
        surface_to_use=requirement.surface,
        max_placement=placement,
    )


def _match_type(requirement: RequirementTerm, text: str) -> str:
    """Return a deterministic exact/variant/alias classification for text."""
    if not text:
        return ""
    canonical = normalize_term(requirement.canonical)
    text_key = normalize_term(text)
    # Resolver calls are hot: requirements are already vocabulary-derived, so
    # scanning every vocabulary entry here is unnecessary and turns a normal
    # resume into millions of regex operations. Match just this requirement's
    # canonical form and aliases against normalized structured source text.
    forms = (requirement.canonical, requirement.surface, *requirement.aliases, *aliases_for(requirement.canonical))
    for form in dict.fromkeys(forms):
        normalized_form = normalize_term(form)
        # A raw mention is evidence only when it appears in an affirmative
        # clause.  "No Kubernetes experience" and "currently learning Rust"
        # are source facts, but never proof that the candidate has those skills.
        if not normalized_form or not _contains_normalized(text_key, normalized_form):
            continue
        if not term_in_text_affirmative(form, text):
            continue
        if _contains_literal_phrase(text, requirement.canonical):
            return "exact"
        if normalize_term(form) == canonical:
            return "variant_spelling"
        return "alias"
    return ""


def _contains_phrase(text: str, phrase: str) -> bool:
    return _contains_normalized(normalize_term(text), normalize_term(phrase))


def _contains_normalized(text_key: str, phrase_key: str) -> bool:
    """Perform whole-phrase matching on normalize_term output without regex."""
    return bool(phrase_key and f" {phrase_key} " in f" {text_key} ")


def _contains_literal_phrase(text: str, phrase: str) -> bool:
    """Match formatting variation while retaining spelling distinctions.

    ``normalize_term`` intentionally equates modelling/modeling; this helper
    is only used to report whether that source spelling was exact or a
    supported variant. It must therefore avoid that spelling normalization.
    """
    text_key = _literal_key(text)
    phrase_key = _literal_key(phrase)
    return bool(phrase_key and f" {phrase_key} " in f" {text_key} ")


def _literal_key(value: str) -> str:
    lowered = (value or "").casefold().replace("&", " and ")
    return " ".join(
        "".join(character if character.isalnum() or character == "#" else " " for character in lowered).split()
    )


def _adjacent_evidence(requirement: RequirementTerm, profile: Profile) -> str:
    category = find_category(requirement.canonical)
    if category is None:
        return ""
    _key, _label, tools = category
    for tool in tools:
        for source in (profile.tier_a, profile.tier_b, profile.tier_c):
            for key, display in source.items():
                if normalize_term(key) == normalize_term(tool) or normalize_term(display) == normalize_term(tool):
                    return display
        for experience in profile.experiences:
            for bullet in experience.bullets:
                if term_in_text_affirmative(tool, bullet):
                    return bullet
    return ""


__all__ = ["resolve_requirements"]
