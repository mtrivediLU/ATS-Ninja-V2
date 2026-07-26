"""Raw-source fidelity checks for Tailoring Engine v2.

The claim validator answers "is a generated claim supported at all?".  This
module answers the complementary question that matters when tailoring an
otherwise truthful resume: "did a rewrite quietly remove or alter a source
fact?"  Its checks are intentionally conservative.  A failed check should
cause an optimizer to retain the candidate-authored source sentence, rather
than attempt to paraphrase a fact into compliance.

The public entry points accept plain text in addition to a :class:`Profile` so
they are usable before rendering, by the renderer, and by persisted-kit change
actions.  They have no provider or framework dependency.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ats_engine.models import Profile
from ats_engine.parsing.resume import find_metrics

_LATEX_ESCAPES: tuple[tuple[str, str], ...] = (
    (r"\&", "&"),
    (r"\%", "%"),
    (r"\$", "$"),
    (r"\#", "#"),
    (r"\_", "_"),
    (r"\textendash", "-"),
    (r"\textemdash", "-"),
)
_DASH_TRANSLATION = str.maketrans({"–": "-", "—": "-", "−": "-"})
_TEAM_FACT_RE = re.compile(
    r"\b(?:team|group)\s+of\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:engineers?|developers?|analysts?|people|members?|staff)\b",
    flags=re.IGNORECASE,
)
_CREDENTIAL_ID_RE = re.compile(r"\b[A-Z]{2,8}-\d{2,6}\b")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#./-]*")
_TERMINAL_SPLIT_RE = re.compile(r"\s*(?:;|:|—|–|--)\s*")
_TRAILING_CLAUSE_RE = re.compile(
    r",\s*((?:for|to|while|with|through|resulting\s+in|which)\b.+)$",
    flags=re.IGNORECASE,
)
# Keep this deliberately local to the fidelity boundary instead of reusing the
# profile parser's bullet list.  A parser can be incomplete or corrupt a
# wrapped source line; raw-source fidelity must still see what the candidate
# actually supplied.  Numbered list markers are included because a few common
# resume exporters replace bullet glyphs with ordered-list markers.
_RAW_BULLET_RE = re.compile(r"^\s*(?:(?:-(?!\d))|[*•●▪◦‣–—]|(?:\d+|[A-Za-z])[.)])\s*(?P<text>\S.*)$")
_RAW_BULLET_CONTINUATION_RE = re.compile(
    r"^(?:[,;:)]|(?:and|or|but|with|for|to|through|while|which|that|including|"
    r"ensuring|supporting|resulting)\b)",
    flags=re.IGNORECASE,
)
_RAW_ORPHAN_BULLET_CONTINUATION_RE = re.compile(
    r"^[A-Za-z0-9+#./ -]{1,80},\s*"
    r"(?:configuring|using|with|for|and|or|to|which|that|including|ensuring|supporting)\b",
    flags=re.IGNORECASE,
)

# Words which are useful grammar but do not identify the factual content of a
# terminal clause.  The set is deliberately small: retaining an extra content
# word is safer than treating a dropped result as harmless prose variation.
_CONTENT_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "the",
        "to",
        "via",
        "while",
        "with",
        "within",
    }
)
_LOW_SIGNAL_BULLET_TERMS = frozenset(
    {
        "architected",
        "build",
        "built",
        "collaborated",
        "collaborate",
        "created",
        "create",
        "delivered",
        "deliver",
        "designed",
        "design",
        "developed",
        "develop",
        "implemented",
        "implement",
        "improved",
        "improve",
        "led",
        "lead",
        "maintained",
        "maintain",
        "managed",
        "manage",
        "optimized",
        "optimize",
        "supported",
        "support",
        "used",
        "use",
        "using",
        "worked",
        "work",
    }
)
_GENERIC_ENTITY_WORDS = frozenset(
    {
        "Achievements",
        "Additional",
        "Certifications",
        "Contact",
        "Education",
        "Experience",
        "Highlights",
        "Professional",
        "Projects",
        "Skills",
        "Summary",
        "Technical",
        "Work",
        "Built",
        "Created",
        "Developed",
        "Designed",
        "Implemented",
        "Improved",
        "Led",
        "Managed",
        "Supported",
        "Worked",
    }
)


@dataclass(frozen=True, slots=True)
class BulletPair:
    """One original/candidate bullet pair, optionally labelled for diagnostics."""

    original: str
    candidate: str
    location: str = ""


@dataclass(frozen=True, slots=True)
class FidelityReport:
    """Stable result for the raw-source fidelity gate."""

    errors: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        """Whether every checked fact remains faithful to the source."""
        return not self.errors


def validate_raw_source_fidelity(
    source_text: str,
    candidate_text: str,
    *,
    profile: Profile | None = None,
    bullet_pairs: Sequence[BulletPair] = (),
) -> FidelityReport:
    """Validate a tailored resume against raw candidate-authored source evidence.

    The gate preserves parsed experience, education, certificate, credential-ID,
    metric, and remote/location facts *only when the raw source actually
    contains them*.  That condition prevents a suspicious parser extraction
    from being turned into a new hard requirement.  It also independently
    extracts explicit raw-source bullet lines and their continuations, so a
    bullet lost before :class:`Profile` construction cannot evade this gate.
    ``bullet_pairs`` supplies an additional, location-aware check for known
    rewritten bullets.

    ``candidate_text`` may be plain text or LaTeX-like text.  Basic LaTeX
    escapes and typography are normalized only for comparison; no generated
    prose is changed here.
    """
    raw_source = source_text or (profile.raw_markdown if profile is not None else "")
    errors: list[str] = []

    if profile is not None:
        for label, fact in _profile_facts(profile, raw_source):
            if not _contains_fact(raw_source, fact):
                # Raw source is authoritative; do not turn an extraction guess
                # into a fidelity failure.  Extraction plausibility is checked
                # separately by the parser-quality gate.
                continue
            if not _contains_fact(candidate_text, fact):
                errors.append(f"fidelity: missing source {label}: {fact}")

    errors.extend(_unsupported_candidate_metrics(raw_source, candidate_text))
    errors.extend(_unsupported_credential_ids(raw_source, candidate_text))
    errors.extend(_raw_source_bullet_errors(raw_source, candidate_text))

    for index, pair in enumerate(bullet_pairs):
        prefix = pair.location.strip() or f"bullet {index + 1}"
        errors.extend(
            f"{prefix}: {error}"
            for error in bullet_fidelity_errors(
                pair.original,
                pair.candidate,
                source_text=raw_source,
            )
        )

    return FidelityReport(errors=tuple(_dedupe(errors)))


def validate_resume_fidelity(
    source_text: str,
    candidate_text: str,
    *,
    profile: Profile | None = None,
    bullet_pairs: Sequence[BulletPair] = (),
) -> list[str]:
    """List-form compatibility entry point for the resume fidelity gate."""
    return list(
        validate_raw_source_fidelity(
            source_text,
            candidate_text,
            profile=profile,
            bullet_pairs=bullet_pairs,
        ).errors
    )


def bullet_fidelity_errors(
    original: str,
    candidate: str,
    *,
    source_text: str = "",
) -> list[str]:
    """Return fact-retention errors for a single rewritten resume bullet.

    A rewrite must retain every original metric, named entity, team-size fact,
    and material terminal-clause fact.  It may mention a source-supported term
    from elsewhere in the resume (the scoped-evidence allowance used by v2),
    but cannot introduce a metric, credential, or named entity absent from the
    raw source.  Passing ``source_text`` therefore enables valid cross-bullet
    integration without weakening the raw-evidence boundary.
    """
    errors = _bullet_retention_errors(original, candidate)
    evidence_text = source_text or original

    candidate_metrics = _normalized_metric_set(candidate)
    source_metrics = _normalized_metric_set(evidence_text)
    for metric in sorted(candidate_metrics - source_metrics):
        errors.append(f"fidelity: unsupported metric introduced: {metric}")

    candidate_entities = extract_named_entities(candidate)
    for entity in candidate_entities:
        if not _contains_fact(evidence_text, entity):
            errors.append(f"fidelity: unsupported named entity introduced: {entity}")

    return _dedupe(errors)


def bullet_preserves_facts(original: str, candidate: str, *, source_text: str = "") -> bool:
    """True when :func:`bullet_fidelity_errors` finds no fact loss or invention."""
    return not bullet_fidelity_errors(original, candidate, source_text=source_text)


def _raw_source_bullet_errors(
    raw_source: str,
    candidate_text: str,
) -> list[str]:
    """Check source glyph bullets even when no parsed profile preserved them.

    The comparison intentionally targets the full rendered document.  A valid,
    approved rewrite can move a source-backed fact from a bullet to a summary
    or another faithful placement; requiring exact whole-bullet identity would
    reject that harmless presentation change.  What must survive is the
    candidate fact content, including terminal-clause facts such as scope,
    result, or audience.
    """
    errors: list[str] = []

    for index, original in enumerate(_extract_raw_source_bullets(raw_source), start=1):
        prefix = f"raw source bullet {index}"
        errors.extend(f"{prefix}: {error}" for error in _bullet_retention_errors(original, candidate_text))
        if not _raw_bullet_content_survives(original, candidate_text):
            errors.append(f"{prefix}: fidelity: raw source bullet content not retained: {original}")

    return errors


def _extract_raw_source_bullets(source_text: str) -> tuple[str, ...]:
    """Extract explicit source bullet glyph lines with conservative wraps.

    This intentionally does not call the resume parser or inspect a
    :class:`Profile`: it is the independent backstop for a parser that drops a
    bullet entirely.  A continuation is joined only when its shape strongly
    signals that it belongs to the preceding glyph line, so headings and a
    subsequent employer are never silently absorbed as bullet prose.
    """
    bullets: list[str] = []
    current: str = ""

    def finish_current() -> None:
        nonlocal current
        cleaned = re.sub(r"\s+", " ", current).strip()
        if cleaned:
            bullets.append(cleaned)
        current = ""

    for raw_line in (source_text or "").splitlines():
        marker = _RAW_BULLET_RE.match(raw_line)
        if marker is not None:
            finish_current()
            current = marker.group("text").strip()
            continue

        line = raw_line.strip()
        if current and line and _is_raw_bullet_continuation(raw_line, current):
            separator = "" if current.endswith("-") else " "
            current = f"{current}{separator}{line}"
            continue
        finish_current()

    finish_current()
    return tuple(bullets)


def _is_raw_bullet_continuation(raw_line: str, current: str) -> bool:
    """Return whether an unmarked physical line continues a raw bullet."""
    line = raw_line.strip()
    if not line:
        return False
    if current.rstrip().endswith("-"):
        return True
    if raw_line[:1].isspace():
        return True
    return (
        line[:1].islower()
        or _RAW_BULLET_CONTINUATION_RE.match(line) is not None
        or _RAW_ORPHAN_BULLET_CONTINUATION_RE.match(line) is not None
    )


def _raw_bullet_content_survives(original: str, candidate_text: str) -> bool:
    """Check broad source-content coverage without demanding exact wording."""
    original_terms = {term for term in _content_terms(original) if term not in _LOW_SIGNAL_BULLET_TERMS}
    if not original_terms:
        return True
    candidate_terms = set(_content_terms(candidate_text))
    retained = len(original_terms & candidate_terms)
    # A half-overlap preserves meaningful content under ordinary paraphrases
    # ("developed REST APIs in Python" -> "built Python API services") while
    # a missing/corrupted raw bullet has no meaningful overlap at all.
    return retained / len(original_terms) >= 0.5


def _bullet_retention_errors(original: str, candidate: str) -> list[str]:
    """Return only the source-fact loss portion of bullet validation.

    Raw-source bullets are checked against the complete rendered document so
    an approved rewrite may relocate a fact.  The document also contains
    renderer labels (for example ``Professional Headline``), which must not be
    mistaken for an entity invented by *this* source bullet.  Unsupported new
    claims remain covered by the document-level validators.
    """
    errors: list[str] = []
    original_metrics = _normalized_metric_set(original)
    candidate_metrics = _normalized_metric_set(candidate)
    for metric in sorted(original_metrics - candidate_metrics):
        errors.append(f"fidelity: missing original metric: {metric}")

    for team_fact in _team_facts(original):
        if not _contains_fact(candidate, team_fact):
            errors.append(f"fidelity: missing original team fact: {team_fact}")

    for entity in extract_named_entities(original):
        if not _contains_fact(candidate, entity):
            errors.append(f"fidelity: missing original named entity: {entity}")

    terminal_clause = _terminal_clause(original)
    if terminal_clause and not _terminal_clause_preserved(terminal_clause, candidate):
        errors.append(f"fidelity: terminal clause facts not retained: {terminal_clause}")

    return _dedupe(errors)


def extract_named_entities(text: str) -> tuple[str, ...]:
    """Extract conservative proper-name / branded-term candidates from text.

    This is intentionally not an NLP entity recognizer.  It catches the kinds
    of source facts a resume optimizer must never erase or invent: multi-word
    title-case names (``Tata Consultancy Services``), all-caps terms (``SQL``),
    and mixed/hyphenated branded forms (``ZoomInfo`` and ``M-Files``).  Ordinary
    sentence-initial action verbs and section headings are excluded.
    """
    tokens = _TOKEN_RE.findall(text or "")
    entities: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _is_brand_token(token):
            entities.append(token)
            index += 1
            continue

        if not _is_title_token(token):
            index += 1
            continue

        parts = [token]
        cursor = index + 1
        title_parts = 1
        while cursor < len(tokens):
            candidate = tokens[cursor]
            if _is_title_token(candidate) or candidate.casefold() in {"of", "the", "and"}:
                parts.append(candidate)
                if _is_title_token(candidate):
                    title_parts += 1
                cursor += 1
                continue
            break
        if title_parts >= 2:
            entity = " ".join(parts).strip()
            if entity not in _GENERIC_ENTITY_WORDS:
                entities.append(entity)
            index = cursor
            continue
        index += 1
    return tuple(_dedupe(entities))


def _profile_facts(profile: Profile, raw_source: str) -> list[tuple[str, str]]:
    facts: list[tuple[str, str]] = []
    for experience in profile.experiences:
        facts.extend(
            (
                ("employer", experience.company),
                ("title", experience.title),
                ("dates", experience.dates),
                ("location", experience.location),
            )
        )
        if "remote" in experience.location.casefold():
            facts.append(("remote work mode", "remote"))

    if "remote" in profile.contact.location.casefold() or "remote" in profile.contact.work_mode.casefold():
        facts.append(("remote work mode", "remote"))

    for education in profile.education:
        facts.extend(
            (
                ("education institution", education.institution),
                ("education degree", education.degree),
                ("education dates", education.dates),
                ("education location", education.location),
            )
        )

    for certification in profile.certifications:
        facts.append(("certification", certification.name))
        if certification.credential_id:
            facts.append(("certification credential ID", certification.credential_id))

    metric_values = [*find_metrics(raw_source), *profile.supported_metrics]
    facts.extend(("metric", metric) for metric in metric_values)
    return [(label, fact.strip()) for label, fact in facts if _meaningful_fact(fact)]


def _unsupported_candidate_metrics(source_text: str, candidate_text: str) -> list[str]:
    source_metrics = _normalized_metric_set(source_text)
    candidate_metrics = _normalized_metric_set(candidate_text)
    return [
        f"fidelity: unsupported metric introduced: {metric}" for metric in sorted(candidate_metrics - source_metrics)
    ]


def _unsupported_credential_ids(source_text: str, candidate_text: str) -> list[str]:
    source_ids = {match.group(0).casefold() for match in _CREDENTIAL_ID_RE.finditer(source_text or "")}
    candidate_ids = {match.group(0).casefold() for match in _CREDENTIAL_ID_RE.finditer(candidate_text or "")}
    return [
        f"fidelity: unsupported certification credential ID introduced: {credential_id.upper()}"
        for credential_id in sorted(candidate_ids - source_ids)
    ]


def _normalized_metric_set(text: str) -> set[str]:
    return {_normalize_for_matching(metric) for metric in find_metrics(text) if _normalize_for_matching(metric)}


def _team_facts(text: str) -> tuple[str, ...]:
    return tuple(_dedupe(match.group(0).strip() for match in _TEAM_FACT_RE.finditer(text or "")))


def _terminal_clause(text: str) -> str:
    """Return an explicitly delimited terminal clause, if one exists."""
    cleaned = (text or "").strip().rstrip(".?!")
    if not cleaned:
        return ""
    pieces = [piece.strip() for piece in _TERMINAL_SPLIT_RE.split(cleaned) if piece.strip()]
    if len(pieces) > 1:
        return pieces[-1]
    match = _TRAILING_CLAUSE_RE.search(cleaned)
    return match.group(1).strip() if match else ""


def _terminal_clause_preserved(terminal_clause: str, candidate: str) -> bool:
    required_terms = _content_terms(terminal_clause)
    if len(required_terms) < 2:
        return True
    candidate_terms = set(_content_terms(candidate))
    retained = sum(term in candidate_terms for term in required_terms)
    # Preserve at least three quarters of material terminal-clause words.  The
    # deterministic optimizer can retain the original bullet if a stylistic
    # paraphrase fails this deliberately fact-first threshold.
    return retained / len(required_terms) >= 0.75


def _content_terms(text: str) -> tuple[str, ...]:
    terms = [
        token.casefold()
        for token in _TOKEN_RE.findall(text or "")
        if len(token) > 2 and token.casefold() not in _CONTENT_STOP_WORDS
    ]
    return tuple(_dedupe(terms))


def _contains_fact(text: str, fact: str) -> bool:
    needle = _normalize_for_matching(fact)
    haystack = _normalize_for_matching(text)
    if not needle or not haystack:
        return False
    return needle == haystack or f" {needle} " in f" {haystack} "


def _normalize_for_matching(text: str) -> str:
    normalized = (text or "").translate(_DASH_TRANSLATION)
    # A PDF word wrap can split a visible hyphenated name across lines. Join
    # the physical break before comparing facts so ``Zoom-\nInfo`` remains
    # the same source entity as the parser's ``Zoom-Info``.
    normalized = re.sub(r"([A-Za-z0-9])-\s*\n\s*([A-Za-z0-9])", r"\1-\2", normalized)
    for escaped, replacement in _LATEX_ESCAPES:
        normalized = normalized.replace(escaped, replacement)
    normalized = re.sub(r"\\(?:textbf|textit|emph|href|url)\{([^{}]*)\}", r"\1", normalized)
    normalized = normalized.replace("{", " ").replace("}", " ")
    normalized = re.sub(r"\s+", " ", normalized.casefold()).strip()
    # A period is terminal punctuation for fidelity facts, not part of a
    # source metric/team/entity. URLs are never compared through this helper.
    normalized = re.sub(r"[^a-z0-9+#/-]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _meaningful_fact(value: str) -> bool:
    normalized = _normalize_for_matching(value)
    return len(normalized) >= 2 and normalized not in {"n a", "na", "none", "unknown"}


def _is_title_token(token: str) -> bool:
    if token in _GENERIC_ENTITY_WORDS:
        return False
    return len(token) > 1 and token[0].isupper() and token[1:].islower()


def _is_brand_token(token: str) -> bool:
    stripped = token.strip(".,;:()[]{}")
    if stripped in _GENERIC_ENTITY_WORDS or len(stripped) < 2:
        return False
    if stripped.isupper() and any(character.isalpha() for character in stripped):
        return True
    if any(character.isupper() for character in stripped[1:]):
        return True
    return "-" in stripped and any(character.isupper() for character in stripped)


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


__all__ = [
    "BulletPair",
    "FidelityReport",
    "bullet_fidelity_errors",
    "bullet_preserves_facts",
    "extract_named_entities",
    "validate_raw_source_fidelity",
    "validate_resume_fidelity",
]
