"""Source-aware requirement resolution for Tailoring Engine v2."""

from __future__ import annotations

import re

from ats_engine.evidence.adjacency import find_category
from ats_engine.models import EvidenceLink, Profile, RequirementTerm
from ats_engine.parsing.resume import term_in_text_affirmative
from ats_engine.parsing.vocab import (
    aliases_for,
    certification_codes,
    certification_implications,
    normalize_term,
)

# These bridges are intentionally narrow.  They make a small number of
# resume-native formulations usable for their corresponding typed JD
# requirements, but only when the source profile contains an exact supporting
# skill item or experience bullet.  They are not semantic similarity or a
# general synonym engine.
_BRIDGE_REQUIREMENTS = frozenset(
    {
        "version control",
        "data ingestion",
        "multi source data pipelines",
        "dashboards",
    }
)
_VERSION_CONTROL_TOOLS = ("git", "github", "gitlab", "bitbucket")
_INGEST_STEM = re.compile(r"\bingest\w*\b", flags=re.IGNORECASE)
_ETL_SIGNAL = re.compile(r"(?<![\w-])(?:etl|elt)(?![\w-])", flags=re.IGNORECASE)
_PIPELINE_CONTEXT = re.compile(r"\b(?:pipelines?|ingest\w*|integrat\w*)\b", flags=re.IGNORECASE)
_DASHBOARD_WORD = re.compile(r"\bdashboards?\b", flags=re.IGNORECASE)
_DASHBOARD_BUILD_VERB = re.compile(
    r"\b(?:build|built|develop|developed|design|designed|create|created|implement|implemented|"
    r"deliver|delivered|automate|automated|maintain|maintained)\b",
    flags=re.IGNORECASE,
)
_BI_PLATFORM = re.compile(r"\b(?:tableau|power\s+bi)\b", flags=re.IGNORECASE)

# A source system is deliberately a named platform, a concrete interchange
# format, or a clearly bounded operational source.  Generic phrases such as
# "multiple systems" and a pair of generic nouns are not enough to bridge to
# a multi-source pipeline claim.
_SOURCE_SYSTEM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("salesforce", re.compile(r"\bsalesforce\b", flags=re.IGNORECASE)),
    ("hubspot", re.compile(r"\bhubspot\b", flags=re.IGNORECASE)),
    ("zoominfo", re.compile(r"\bzoom\s*-?\s*info\b", flags=re.IGNORECASE)),
    ("lead forensics", re.compile(r"\blead\s+forensics\b", flags=re.IGNORECASE)),
    ("sharepoint", re.compile(r"\bshare\s*point\b", flags=re.IGNORECASE)),
    ("excel", re.compile(r"\b(?:microsoft\s+)?excel\b", flags=re.IGNORECASE)),
    ("sql server", re.compile(r"\b(?:ms\s+)?sql\s+server\b", flags=re.IGNORECASE)),
    ("postgresql", re.compile(r"\bpostgres(?:ql)?\b", flags=re.IGNORECASE)),
    ("mysql", re.compile(r"\bmysql\b", flags=re.IGNORECASE)),
    ("oracle", re.compile(r"\boracle\b", flags=re.IGNORECASE)),
    ("snowflake", re.compile(r"\bsnowflake\b", flags=re.IGNORECASE)),
    ("redshift", re.compile(r"\bredshift\b", flags=re.IGNORECASE)),
    ("mongodb", re.compile(r"\bmongo(?:db)?\b", flags=re.IGNORECASE)),
    ("google analytics", re.compile(r"\bgoogle\s+analytics\b", flags=re.IGNORECASE)),
    ("device logs", re.compile(r"\bdevice\s+logs?\b", flags=re.IGNORECASE)),
    ("apis", re.compile(r"\bapis?\b", flags=re.IGNORECASE)),
    ("csv", re.compile(r"\bcsv\b", flags=re.IGNORECASE)),
    ("json", re.compile(r"\bjson\b", flags=re.IGNORECASE)),
    ("sftp", re.compile(r"\bsftp\b", flags=re.IGNORECASE)),
)

# PL-300 directly supports Power BI Service in the narrow certification table.
# These are its safe child concepts for a JD that names workspace or refresh
# administration.  They remain certification-backed knowledge, never direct
# production experience, and inherit the exact certificate provenance.
_CERTIFICATE_CHILDREN: dict[str, frozenset[str]] = {
    "power bi service": frozenset({"workspaces", "refresh cycles"}),
}


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
    # Curated bridge rules run before direct matching only for the very narrow
    # formulations they explain.  A Tableau dashboard bullet, for example, is
    # better represented to reviewers as a bridged dashboard capability than
    # as a coincidental token hit; all other direct evidence retains its exact
    # / variant / alias classification below.
    bridged_experience = _bridge_from_experience(requirement, profile)
    if bridged_experience is not None:
        return bridged_experience

    # Strongest source: an affirmative, structured experience bullet.
    for exp_index, experience in enumerate(profile.experiences):
        for bullet_index, bullet in enumerate(experience.bullets):
            if _is_dashboard_requirement(requirement) and _contains_affirmative_match(_DASHBOARD_WORD, bullet):
                # Mentioning that a candidate reviewed dashboard requirements is
                # not the same fact as building dashboards. Direct wording still
                # earns credit when the bullet has a concrete build verb; the
                # Tableau/Power BI variant above is labeled as a bridge.
                if not _contains_affirmative_match(_DASHBOARD_BUILD_VERB, bullet):
                    continue
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

    bridged_skill = _bridge_from_skills(requirement, profile)
    if bridged_skill is not None:
        return bridged_skill

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

    bridged_certificate = _bridge_from_certification(requirement, profile)
    if bridged_certificate is not None:
        return bridged_certificate

    for certification in profile.certifications:
        implied = {normalize_term(term) for term in certification_implications(certification)}
        if normalize_term(requirement.canonical) not in implied:
            continue
        span = _certification_span(certification)
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


def _bridge_from_experience(requirement: RequirementTerm, profile: Profile) -> EvidenceLink | None:
    """Resolve a curated bridge only from affirmative experience bullets."""
    canonical = normalize_term(requirement.canonical)
    if canonical not in _BRIDGE_REQUIREMENTS:
        return None

    if canonical == "multi source data pipelines":
        etl_evidence = _etl_evidence(profile)
        if etl_evidence is None:
            return None
        etl_span, etl_location = etl_evidence
        for exp_index, experience in enumerate(profile.experiences):
            for bullet_index, bullet in enumerate(experience.bullets):
                if len(_source_systems_in(bullet)) < 2 or not _contains_affirmative_match(_PIPELINE_CONTEXT, bullet):
                    continue
                bullet_location = f"experience:{exp_index}:bullet:{bullet_index}"
                supporting = _dedupe_provenance(((etl_span, etl_location), (bullet, bullet_location)))
                return _bridged_link(
                    requirement,
                    tier="A",
                    span=bullet,
                    location=bullet_location,
                    placement="bullet",
                    supporting_spans=tuple(span for span, _location in supporting),
                    supporting_locations=tuple(location for _span, location in supporting),
                )
        return None

    for exp_index, experience in enumerate(profile.experiences):
        for bullet_index, bullet in enumerate(experience.bullets):
            if not _matches_experience_bridge(canonical, bullet):
                continue
            return _bridged_link(
                requirement,
                tier="A",
                span=bullet,
                location=f"experience:{exp_index}:bullet:{bullet_index}",
                placement="bullet",
            )
    return None


def _bridge_from_skills(requirement: RequirementTerm, profile: Profile) -> EvidenceLink | None:
    """Resolve bridges that are safe for a listed skill, never a summary guess."""
    if normalize_term(requirement.canonical) != "version control":
        return None
    for item, location in _skill_evidence(profile):
        if _contains_any_affirmative(item, _VERSION_CONTROL_TOOLS):
            return _bridged_link(
                requirement,
                tier="C",
                span=item,
                location=location,
                placement="skills",
            )
    return None


def _bridge_from_certification(requirement: RequirementTerm, profile: Profile) -> EvidenceLink | None:
    """Inherit narrow child concepts from a named, source-backed certification."""
    canonical = normalize_term(requirement.canonical)
    # A foundation Azure certificate is deliberately never a bridge to Azure
    # DevOps.  Keep this explicit even though the certificate implication table
    # already excludes it, so a future broadening cannot silently over-claim.
    if canonical == "azure devops":
        return None
    if canonical in {"workspaces", "refresh cycles"} and requirement.category != "bi_analytics":
        return None
    for certification in profile.certifications:
        implied = {normalize_term(term) for term in certification_implications(certification)}
        if not any(canonical in children and parent in implied for parent, children in _CERTIFICATE_CHILDREN.items()):
            continue
        span = _certification_span(certification)
        return _bridged_link(
            requirement,
            tier="cert",
            span=span,
            location="certification",
            placement="summary",
        )
    return None


def _matches_experience_bridge(canonical: str, bullet: str) -> bool:
    if canonical == "version control":
        return _contains_any_affirmative(bullet, _VERSION_CONTROL_TOOLS)
    if canonical == "data ingestion":
        return _contains_affirmative_match(_INGEST_STEM, bullet)
    if canonical == "dashboards":
        return (
            _contains_affirmative_match(_DASHBOARD_WORD, bullet)
            and _contains_affirmative_match(_BI_PLATFORM, bullet)
            and _contains_affirmative_match(_DASHBOARD_BUILD_VERB, bullet)
        )
    return False


def _is_dashboard_requirement(requirement: RequirementTerm) -> bool:
    return normalize_term(requirement.canonical) == "dashboards"


def _etl_evidence(profile: Profile) -> tuple[str, str] | None:
    """Return a real ETL/ELT span, first preferring experience evidence."""
    for exp_index, experience in enumerate(profile.experiences):
        for bullet_index, bullet in enumerate(experience.bullets):
            if _contains_affirmative_match(_ETL_SIGNAL, bullet):
                return bullet, f"experience:{exp_index}:bullet:{bullet_index}"
    for item, location in _skill_evidence(profile):
        if _contains_affirmative_match(_ETL_SIGNAL, item):
            return item, location
    return None


def _source_systems_in(text: str) -> set[str]:
    """Return distinct, affirmative concrete source systems from one bullet."""
    found: set[str] = set()
    for system, pattern in _SOURCE_SYSTEM_PATTERNS:
        if _contains_affirmative_match(pattern, text):
            found.add(system)
    return found


def _skill_evidence(profile: Profile) -> list[tuple[str, str]]:
    """Enumerate the parser's structured skills with stable source locations."""
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    if profile.source_skill_groups:
        for group_index, (_heading, items) in enumerate(profile.source_skill_groups):
            for item_index, item in enumerate(items):
                normalized = normalize_term(item)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                result.append((item, f"skills:{group_index}:{item_index}"))

    # Source taxonomy wins whenever it has the item, but older/mixed profile
    # parsers can populate a tier map more completely than their group list.
    # Keep those map-only values as a compatibility fallback rather than
    # silently dropping otherwise structured candidate evidence.
    for source in (profile.tier_c, profile.tier_a, profile.tier_b):
        for key, display in source.items():
            span = display or key
            normalized = normalize_term(span)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append((span, "skills"))
    return result


def _contains_any_affirmative(text: str, terms: tuple[str, ...]) -> bool:
    return any(term_in_text_affirmative(term, text) for term in terms)


def _contains_affirmative_match(pattern: re.Pattern[str], text: str) -> bool:
    for match in pattern.finditer(text or ""):
        if term_in_text_affirmative(match.group(0), text):
            return True
    return False


def _certification_span(certification: object) -> str:
    """Keep one readable, source-backed certification provenance span."""
    name = str(getattr(certification, "name", "") or "").strip()
    codes = list(dict.fromkeys(certification_codes(certification)))
    name_upper = name.upper()
    missing_codes = [code for code in codes if code not in name_upper]
    if name and not missing_codes:
        return name
    if name and missing_codes:
        return f"{name} ({', '.join(missing_codes)})"
    return ", ".join(codes)


def _bridged_link(
    requirement: RequirementTerm,
    *,
    tier: str,
    span: str,
    location: str,
    placement: str,
    supporting_spans: tuple[str, ...] = (),
    supporting_locations: tuple[str, ...] = (),
) -> EvidenceLink | None:
    """Return a bridge only when its caller supplied a candidate-authored span."""
    if not span.strip():
        return None
    return _link(
        requirement,
        tier=tier,
        span=span,
        location=location,
        match_type="bridged",
        placement=placement,
        supporting_spans=supporting_spans,
        supporting_locations=supporting_locations,
    )


def _link(
    requirement: RequirementTerm,
    *,
    tier: str,
    span: str,
    location: str,
    match_type: str,
    placement: str,
    supporting_spans: tuple[str, ...] = (),
    supporting_locations: tuple[str, ...] = (),
) -> EvidenceLink:
    return EvidenceLink(
        requirement=requirement,
        tier=tier,
        resume_span=span,
        resume_location=location,
        supporting_spans=supporting_spans or ((span,) if span else ()),
        supporting_locations=supporting_locations or ((location,) if location else ()),
        match_type=match_type,
        surface_to_use=requirement.surface,
        max_placement=placement,
    )


def _dedupe_provenance(
    values: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """Preserve source order while removing a same-span bridge conjunction."""
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for span, location in values:
        key = (span.strip(), location.strip())
        if not key[0] or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return tuple(result)


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
