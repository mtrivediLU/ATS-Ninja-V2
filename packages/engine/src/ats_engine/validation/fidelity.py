"""Evidence-preserving fidelity validation with structured findings.

The truth validator asks whether generated claims are supported at all. This
module asks the complementary fidelity question: whether tailoring silently
dropped a source fact. Its primary API emits typed findings; legacy string
wrappers stay available for existing pipeline callers during migration.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ats_engine.models import Experience, Profile
from ats_engine.parsing.resume import find_metrics
from ats_engine.parsing.vocab import find_vocabulary_matches
from ats_engine.validation.calibration import (
    FIDELITY_DETECTOR_VERSION,
    CalibrationKey,
    CalibrationProfile,
    apply_calibration,
)
from ats_engine.validation.findings import canonicalize_fact
from ats_engine.validation.severity import (
    CAL_FALSE_POSITIVE,
    FIDELITY_MISSING_NAMED_ENTITY,
    FIDELITY_MISSING_ORIGINAL_METRIC,
    FIDELITY_MISSING_RESPONSIBILITY,
    FIDELITY_MISSING_SOURCE_FACT,
    FIDELITY_MISSING_TEAM_FACT,
    FIDELITY_MISSING_TECHNOLOGY,
    FIDELITY_RAW_BULLET_CONTENT_LOST,
    FIDELITY_TERMINAL_CLAUSE_LOST,
    FIDELITY_UNSUPPORTED_CREDENTIAL_ID,
    FIDELITY_UNSUPPORTED_METRIC,
    FIDELITY_UNSUPPORTED_NAMED_ENTITY,
    ValidationFinding,
    ValidationSeverity,
    severity_for_code,
)

_TEAM_FACT_RE = re.compile(
    r"\b(?:team|group)\s+of\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:engineers?|developers?|analysts?|people|members?|staff)\b",
    flags=re.IGNORECASE,
)
_CREDENTIAL_ID_RE = re.compile(r"\b[A-Z]{2,8}-\d{2,6}\b")
_CONTENT_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#./-]*")
_ENTITY_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#.]*(?:-[A-Za-z0-9][A-Za-z0-9+#.]*)*")
_TERMINAL_SPLIT_RE = re.compile(r"\s*(?:;|:|—|–|--)\s*")
_TRAILING_CLAUSE_RE = re.compile(
    r",\s*((?:for|to|while|with|through|resulting\s+in|which)\b.+)$",
    flags=re.IGNORECASE,
)

# Entity extraction operates on punctuation-bounded segments. ASCII hyphens
# remain valid inside a token (``M-Files``), while separator dashes with
# surrounding whitespace and sentence/list punctuation terminate a sequence.
# Periods and legal-suffix commas need a small scanner below so tokens such as
# ``U.S. Bank``, ``D3.js``, and ``Acme, Inc.`` remain intact.
_ENTITY_BOUNDARY_RE = re.compile(r"\s+-\s+|[–—:/;|!?\"'“”‘’()\[\]{}]")
_ENTITY_COMMA_RE = re.compile(r",")
_LEGAL_SUFFIX_AFTER_COMMA_RE = re.compile(
    r"^\s*(?:inc|incorporated|llc|ltd|limited|corp|corporation|co|company|llp|lp|plc)\.?\b",
    flags=re.IGNORECASE,
)
_NONTERMINAL_PERIOD_TOKENS = frozenset(
    {
        "b.sc",
        "dr",
        "e.g",
        "i.e",
        "jr",
        "m.sc",
        "mr",
        "mrs",
        "ms",
        "ph.d",
        "prof",
        "sr",
        "st",
        "u.k",
        "u.s",
        "vs",
    }
)

# Raw-bullet retention is intentionally restricted to experience sections.
# Education, certification, and skill bullets are covered by their dedicated
# profile facts and must not be reclassified as experience evidence.
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
_EXPERIENCE_HEADINGS = frozenset(
    {
        "experience",
        "professional experience",
        "work experience",
        "employment history",
        "work history",
        "relevant experience",
        "career history",
    }
)
_NON_EXPERIENCE_HEADINGS = frozenset(
    {
        "academic background",
        "certificates",
        "certifications",
        "core competencies",
        "education",
        "licenses",
        "licenses and certifications",
        "licenses certifications",
        "professional summary",
        "profile",
        "publications",
        "projects",
        "awards",
        "skills",
        "summary",
        "technical skills",
        "volunteer experience",
        "volunteering",
    }
)

# A deliberately narrow equivalence table for high-signal responsibility
# phrases that are not tools and therefore do not belong in the canonical
# technology vocabulary. Patterns include conservative semantic rewrites so
# fidelity protects factual meaning without requiring verbatim prose.
_RESPONSIBILITY_EQUIVALENTS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "incident response",
        (
            re.compile(r"\bincident response\b", flags=re.IGNORECASE),
            re.compile(r"\bincident handling\b", flags=re.IGNORECASE),
            re.compile(r"\b(?:handled|responded to|resolved)\s+(?:production\s+)?incidents?\b", flags=re.IGNORECASE),
        ),
    ),
    (
        "knowledge transfer",
        (
            re.compile(r"\bknowledge transfer\b", flags=re.IGNORECASE),
            re.compile(r"\btransferred knowledge\b", flags=re.IGNORECASE),
        ),
    ),
    (
        "quality checks",
        (
            re.compile(r"\bquality checks?\b", flags=re.IGNORECASE),
            re.compile(r"\bchecked (?:data |reporting )?quality\b", flags=re.IGNORECASE),
            re.compile(r"\bvalidated (?:data |reporting )?quality\b", flags=re.IGNORECASE),
        ),
    ),
    (
        "release documentation",
        (
            re.compile(r"\brelease documentation\b", flags=re.IGNORECASE),
            re.compile(r"\bdocumented releases?\b", flags=re.IGNORECASE),
        ),
    ),
    (
        "production deployments",
        (
            re.compile(r"\bproduction deployments?\b", flags=re.IGNORECASE),
            re.compile(r"\bdeployed (?:services?|systems?|applications?) to production\b", flags=re.IGNORECASE),
        ),
    ),
)

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
        "Architected",
        "Built",
        "Candidate",
        "Certifications",
        "Contact",
        "Created",
        "Developed",
        "Designed",
        "Education",
        "Experience",
        "Header",
        "Headline",
        "Highlights",
        "Implemented",
        "Improved",
        "Led",
        "Location",
        "Managed",
        "Professional",
        "Projects",
        "Skills",
        "Summary",
        "Supported",
        "Technical",
        "Work",
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
class _SourceFact:
    label: str
    fact: str
    source_span: str


@dataclass(frozen=True, slots=True)
class _RawSourceBullet:
    text: str
    source_span: str


@dataclass(frozen=True, slots=True)
class FidelityReport:
    """Structured fidelity result with legacy string compatibility."""

    findings: tuple[ValidationFinding, ...]

    @property
    def errors(self) -> tuple[str, ...]:
        """Legacy non-calibrated error strings, preserving historical callers."""
        return tuple(_legacy_errors(self.findings))

    @property
    def fatal_findings(self) -> tuple[ValidationFinding, ...]:
        """Truth-critical findings that must block delivery."""
        return tuple(finding for finding in self.findings if finding.severity is ValidationSeverity.FATAL)

    @property
    def is_valid(self) -> bool:
        """Whether the report contains no delivery-blocking finding."""
        return not self.fatal_findings


def validate_raw_source_fidelity(
    source_text: str,
    candidate_text: str,
    *,
    profile: Profile | None = None,
    candidate_experiences: Sequence[Experience] | None = None,
    bullet_pairs: Sequence[BulletPair] = (),
    calibrations: Iterable[CalibrationKey] | CalibrationProfile = (),
    detector_version: str = FIDELITY_DETECTOR_VERSION,
    removed_bullets: Sequence[str] = (),
) -> FidelityReport:
    """Validate a rendered resume against raw candidate-authored evidence.

    Raw experience bullets are independently checked even when profile parsing
    lost them. Calibration accepts only exact reviewed identities and merely
    changes matching findings to ``CAL_FALSE_POSITIVE``; it never suppresses
    another source fact or mutates detector evidence.

    ``removed_bullets`` carries the verbatim text of bullets an accepted
    ``PRUNE`` removed; see ``_raw_source_bullet_findings`` for why a ledgered
    removal is not the silent loss this validator exists to catch, and for the
    limits that keep the exclusion from laundering anything.
    """
    raw_source = source_text or (profile.raw_markdown if profile is not None else "")
    findings: list[ValidationFinding] = []

    if profile is not None:
        for source_fact in _profile_facts(profile, raw_source):
            if not _contains_fact(raw_source, source_fact.fact):
                # Raw source is authoritative. A parser-only extraction is not
                # turned into a hard requirement by this validator.
                continue
            if not _contains_fact(candidate_text, source_fact.fact):
                findings.append(
                    _finding(
                        FIDELITY_MISSING_SOURCE_FACT,
                        fact=source_fact.fact,
                        source_span=source_fact.source_span,
                        detail=f"fidelity: missing source {source_fact.label}: {source_fact.fact}",
                        detector_version=detector_version,
                    )
                )

        if candidate_experiences is not None:
            findings.extend(
                _experience_tuple_findings(
                    profile,
                    candidate_experiences,
                    raw_source,
                    detector_version,
                )
            )

    findings.extend(_unsupported_candidate_metric_findings(raw_source, candidate_text, detector_version))
    findings.extend(_unsupported_credential_id_findings(raw_source, candidate_text, detector_version))
    findings.extend(
        _raw_source_bullet_findings(raw_source, candidate_text, detector_version, _removal_keys(removed_bullets))
    )

    for index, pair in enumerate(bullet_pairs):
        source_span = pair.location.strip() or _source_span_for_fact(raw_source or pair.original, pair.original)
        prefix = pair.location.strip() or f"bullet {index + 1}"
        findings.extend(
            _with_detail_prefix(
                bullet_fidelity_findings(
                    pair.original,
                    pair.candidate,
                    source_text=raw_source,
                    source_span=source_span,
                    detector_version=detector_version,
                ),
                prefix,
            )
        )

    return FidelityReport(
        findings=_dedupe_findings(
            apply_calibration(
                findings,
                calibrations,
                fact_is_present=lambda fact: _contains_fact(candidate_text, fact),
            )
        )
    )


def validate_raw_source_findings(
    source_text: str,
    candidate_text: str,
    *,
    profile: Profile | None = None,
    candidate_experiences: Sequence[Experience] | None = None,
    bullet_pairs: Sequence[BulletPair] = (),
    calibrations: Iterable[CalibrationKey] | CalibrationProfile = (),
    detector_version: str = FIDELITY_DETECTOR_VERSION,
    removed_bullets: Sequence[str] = (),
) -> tuple[ValidationFinding, ...]:
    """Return typed findings directly for structured validation consumers."""
    return validate_raw_source_fidelity(
        source_text,
        candidate_text,
        profile=profile,
        candidate_experiences=candidate_experiences,
        bullet_pairs=bullet_pairs,
        calibrations=calibrations,
        detector_version=detector_version,
        removed_bullets=removed_bullets,
    ).findings


def validate_resume_fidelity(
    source_text: str,
    candidate_text: str,
    *,
    profile: Profile | None = None,
    candidate_experiences: Sequence[Experience] | None = None,
    bullet_pairs: Sequence[BulletPair] = (),
    calibrations: Iterable[CalibrationKey] | CalibrationProfile = (),
    detector_version: str = FIDELITY_DETECTOR_VERSION,
    removed_bullets: Sequence[str] = (),
) -> list[str]:
    """Legacy list-string compatibility wrapper around structured fidelity."""
    return list(
        validate_raw_source_fidelity(
            source_text,
            candidate_text,
            profile=profile,
            candidate_experiences=candidate_experiences,
            bullet_pairs=bullet_pairs,
            calibrations=calibrations,
            detector_version=detector_version,
            removed_bullets=removed_bullets,
        ).errors
    )


def bullet_fidelity_findings(
    original: str,
    candidate: str,
    *,
    source_text: str = "",
    source_span: str = "",
    calibrations: Iterable[CalibrationKey] | CalibrationProfile = (),
    detector_version: str = FIDELITY_DETECTOR_VERSION,
) -> tuple[ValidationFinding, ...]:
    """Return typed retention and unsupported-claim findings for one bullet."""
    evidence_text = source_text or original
    resolved_span = source_span or _source_span_for_fact(evidence_text, original)
    findings = _bullet_retention_findings(
        original,
        candidate,
        source_span=resolved_span,
        detector_version=detector_version,
    )

    candidate_metrics = _normalized_metric_set(candidate)
    source_metrics = _normalized_metric_set(evidence_text)
    for metric in sorted(candidate_metrics - source_metrics):
        findings.append(
            _finding(
                FIDELITY_UNSUPPORTED_METRIC,
                fact=metric,
                source_span=_source_span_for_fact(candidate, metric, namespace="candidate"),
                detail=f"fidelity: unsupported metric introduced: {metric}",
                detector_version=detector_version,
            )
        )

    evidence_vocabulary = _vocabulary_alias_canonicals(evidence_text)
    for entity in extract_named_entities(candidate):
        entity_vocabulary = _vocabulary_alias_canonicals(entity)
        if not _contains_fact(evidence_text, entity) and not entity_vocabulary & evidence_vocabulary:
            findings.append(
                _finding(
                    FIDELITY_UNSUPPORTED_NAMED_ENTITY,
                    fact=entity,
                    source_span=_source_span_for_fact(candidate, entity, namespace="candidate"),
                    detail=f"fidelity: unsupported named entity introduced: {entity}",
                    detector_version=detector_version,
                )
            )

    return _dedupe_findings(
        apply_calibration(
            findings,
            calibrations,
            fact_is_present=lambda fact: _contains_fact(candidate, fact),
        )
    )


def bullet_fidelity_errors(
    original: str,
    candidate: str,
    *,
    source_text: str = "",
    calibrations: Iterable[CalibrationKey] | CalibrationProfile = (),
    detector_version: str = FIDELITY_DETECTOR_VERSION,
) -> list[str]:
    """Legacy list-string wrapper for :func:`bullet_fidelity_findings`."""
    return _legacy_errors(
        bullet_fidelity_findings(
            original,
            candidate,
            source_text=source_text,
            calibrations=calibrations,
            detector_version=detector_version,
        )
    )


def bullet_preserves_facts(original: str, candidate: str, *, source_text: str = "") -> bool:
    """True when no non-calibrated bullet fidelity error remains."""
    return not bullet_fidelity_errors(original, candidate, source_text=source_text)


def _removal_keys(removed_bullets: Sequence[str]) -> frozenset[str]:
    """Normalized keys for ledgered removals, matching completeness's own rule."""
    return frozenset(
        key for key in (re.sub(r"[^a-z0-9]+", "", (text or "").lower()) for text in removed_bullets) if key
    )


def _raw_source_bullet_findings(
    raw_source: str,
    candidate_text: str,
    detector_version: str,
    removed_keys: frozenset[str] = frozenset(),
) -> list[ValidationFinding]:
    """Check raw *experience* bullets independently of parsed profile state.

    ``removed_keys`` excuses exactly the source bullets an accepted, recorded
    ``PRUNE`` deliberately removed. This is the same distinction
    ``validation.completeness`` draws, and for the same reason: this check
    exists to catch content *silently* lost while rewriting, and a removal
    that is ledgered, reversible, and shown to the user is the opposite of
    silent. Without it a legitimate removal would read here as the very
    failure it is not.

    The exclusion is deliberately narrow and cannot launder anything:

    * it is keyed on the ledger's verbatim ``original_text``, so it can only
      ever skip a bullet the ledger actually names;
    * the ledger itself is not trusted here -- ``completeness`` independently
      proves each entry names real source text that is really absent from the
      render, and rejects the run otherwise;
    * every *other* source bullet is checked exactly as before, as is every
      profile-level fact (employers, titles, dates), which pruning may never
      remove.
    """
    findings: list[ValidationFinding] = []
    for index, source_bullet in enumerate(_extract_raw_experience_bullets(raw_source), start=1):
        prefix = f"raw source bullet {index}"
        if re.sub(r"[^a-z0-9]+", "", source_bullet.text.lower()) in removed_keys:
            continue
        findings.extend(
            _with_detail_prefix(
                _bullet_retention_findings(
                    source_bullet.text,
                    candidate_text,
                    source_span=source_bullet.source_span,
                    detector_version=detector_version,
                ),
                prefix,
            )
        )
        if not _raw_bullet_content_survives(source_bullet.text, candidate_text):
            findings.append(
                _finding(
                    FIDELITY_RAW_BULLET_CONTENT_LOST,
                    fact=source_bullet.text,
                    source_span=source_bullet.source_span,
                    detail=f"{prefix}: fidelity: raw source bullet content not retained: {source_bullet.text}",
                    detector_version=detector_version,
                )
            )
    return findings


def _extract_raw_experience_bullets(source_text: str) -> tuple[_RawSourceBullet, ...]:
    """Extract explicit bullet glyph lines only while inside an experience section."""
    bullets: list[_RawSourceBullet] = []
    section = ""
    current = ""
    start_line = 0
    end_line = 0

    def finish_current() -> None:
        nonlocal current, start_line, end_line
        cleaned = re.sub(r"\s+", " ", current).strip()
        if cleaned:
            line_range = str(start_line) if start_line == end_line else f"{start_line}-{end_line}"
            bullets.append(_RawSourceBullet(text=cleaned, source_span=f"experience:lines:{line_range}"))
        current = ""
        start_line = 0
        end_line = 0

    for line_number, raw_line in enumerate((source_text or "").splitlines(), start=1):
        section_heading = _section_heading(raw_line)
        if section_heading is not None:
            finish_current()
            section = section_heading
            continue

        marker = _RAW_BULLET_RE.match(raw_line)
        if marker is not None:
            finish_current()
            if section == "experience":
                current = marker.group("text").strip()
                start_line = line_number
                end_line = line_number
            continue

        line = raw_line.strip()
        if current and line and _is_raw_bullet_continuation(raw_line, current):
            separator = "" if current.endswith("-") else " "
            current = f"{current}{separator}{line}"
            end_line = line_number
            continue
        finish_current()

    finish_current()
    return tuple(bullets)


def _section_heading(raw_line: str) -> str | None:
    """Classify compact source headings without relying on profile parsing."""
    stripped = raw_line.strip()
    if not stripped or len(stripped) > 60:
        return None
    normalized = canonicalize_fact(stripped)
    if normalized in _EXPERIENCE_HEADINGS:
        return "experience"
    if normalized in _NON_EXPERIENCE_HEADINGS:
        return "other"
    return None


def _is_raw_bullet_continuation(raw_line: str, current: str) -> bool:
    """Return whether an unmarked physical line continues a source bullet."""
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
    """Check broad source-content coverage without requiring exact wording."""
    original_terms = {term for term in _content_terms(original) if term not in _LOW_SIGNAL_BULLET_TERMS}
    if not original_terms:
        return True
    candidate_terms = set(_content_terms(candidate_text))
    return len(original_terms & candidate_terms) / len(original_terms) >= 0.5


def _bullet_retention_findings(
    original: str,
    candidate: str,
    *,
    source_span: str,
    detector_version: str,
) -> list[ValidationFinding]:
    """Return source-fact loss findings without candidate-invention checks."""
    findings: list[ValidationFinding] = []
    # Matching is deliberately order-independent, but a source bullet that has
    # no paired candidate bullet is never an acceptable "rewrite". Comparing
    # it to the whole rendered resume would let a sibling with a few shared
    # words mask the complete loss of a distinct responsibility.
    if original.strip() and not candidate.strip():
        findings.append(
            _finding(
                FIDELITY_RAW_BULLET_CONTENT_LOST,
                fact=original,
                source_span=source_span,
                detail=f"fidelity: source bullet was deleted: {original}",
                detector_version=detector_version,
            )
        )
        return findings

    original_metrics = _normalized_metric_set(original)
    candidate_metrics = _normalized_metric_set(candidate)
    for metric in sorted(original_metrics - candidate_metrics):
        findings.append(
            _finding(
                FIDELITY_MISSING_ORIGINAL_METRIC,
                fact=metric,
                source_span=source_span,
                detail=f"fidelity: missing original metric: {metric}",
                detector_version=detector_version,
            )
        )

    for team_fact in _team_facts(original):
        if not _contains_fact(candidate, team_fact):
            findings.append(
                _finding(
                    FIDELITY_MISSING_TEAM_FACT,
                    fact=team_fact,
                    source_span=source_span,
                    detail=f"fidelity: missing original team fact: {team_fact}",
                    detector_version=detector_version,
                )
            )

    candidate_vocabulary = _protected_vocabulary_canonicals(candidate)
    for entity in extract_named_entities(original):
        entity_vocabulary = _protected_vocabulary_canonicals(entity)
        if not _contains_fact(candidate, entity) and not entity_vocabulary & candidate_vocabulary:
            findings.append(
                _finding(
                    FIDELITY_MISSING_NAMED_ENTITY,
                    fact=entity,
                    source_span=source_span,
                    detail=f"fidelity: missing original named entity: {entity}",
                    detector_version=detector_version,
                )
            )

    for canonical, surface in _protected_vocabulary_facts(original):
        if canonical in candidate_vocabulary:
            continue
        findings.append(
            _finding(
                FIDELITY_MISSING_TECHNOLOGY,
                fact=surface,
                source_span=source_span,
                detail=f"fidelity: missing original technology or methodology: {surface}",
                detector_version=detector_version,
            )
        )

    candidate_responsibilities = _responsibility_canonicals(candidate)
    for canonical, surface in _responsibility_facts(original):
        if canonical in candidate_responsibilities:
            continue
        findings.append(
            _finding(
                FIDELITY_MISSING_RESPONSIBILITY,
                fact=surface,
                source_span=source_span,
                detail=f"fidelity: missing original responsibility: {surface}",
                detector_version=detector_version,
            )
        )

    terminal_clause = _terminal_clause(original)
    if terminal_clause and not _terminal_clause_preserved(terminal_clause, candidate):
        findings.append(
            _finding(
                FIDELITY_TERMINAL_CLAUSE_LOST,
                fact=terminal_clause,
                source_span=source_span,
                detail=f"fidelity: terminal clause facts not retained: {terminal_clause}",
                detector_version=detector_version,
            )
        )

    return findings


def _protected_vocabulary_facts(text: str) -> tuple[tuple[str, str], ...]:
    """Return non-overlapping source tools/methodologies with exact surfaces."""
    output: list[tuple[str, str]] = []
    occupied_until = -1
    seen: set[str] = set()
    for match in find_vocabulary_matches(text or ""):
        if match.start < occupied_until:
            continue
        occupied_until = match.end
        if match.entry.kind not in {"tool", "methodology"}:
            continue
        canonical = match.entry.canonical
        if canonical in seen:
            continue
        seen.add(canonical)
        output.append((canonical, match.surface))
    return tuple(output)


def _protected_vocabulary_canonicals(text: str) -> set[str]:
    return {canonical for canonical, _surface in _protected_vocabulary_facts(text)}


def _vocabulary_alias_canonicals(text: str) -> set[str]:
    """Every vocabulary canonical with a registered surface anywhere in *text*.

    Unlike :func:`_protected_vocabulary_facts` (tool/methodology kinds only,
    used for the *missing*-content direction), this covers every vocabulary
    kind. The *unsupported*-entity check must recognize a candidate's own
    alias spelling of any JD-relevant term the vocabulary knows about --
    ``ReactJS``/``React``, ``front-end``/``frontend``, ``GenAI``/``Generative
    AI`` -- not only the technology/methodology subset. This is exact
    alias identity via the vocabulary registry, never a fuzzy or semantic
    match: a term absent from the registry (an employer, a metric, a
    fabricated skill with no registered alias) falls straight back to the
    literal ``_contains_fact`` check, unaffected.
    """
    return {match.entry.canonical for match in find_vocabulary_matches(text or "")}


def _responsibility_facts(text: str) -> tuple[tuple[str, str], ...]:
    output: list[tuple[str, str]] = []
    for canonical, patterns in _RESPONSIBILITY_EQUIVALENTS:
        for pattern in patterns:
            match = pattern.search(text or "")
            if match is not None:
                output.append((canonical, match.group(0)))
                break
    return tuple(output)


def _responsibility_canonicals(text: str) -> set[str]:
    return {canonical for canonical, _surface in _responsibility_facts(text)}


def extract_named_entities(text: str) -> tuple[str, ...]:
    """Extract punctuation-bounded proper-name and branded-term candidates.

    Entity sequences never cross ``-`` separators, en/em dashes, colons,
    semicolons, commas, terminal sentence punctuation, pipes, slashes, quotes,
    or parentheses. Internal ASCII hyphens and dotted brand/acronym tokens
    remain intact.
    """
    entities: list[str] = []
    for segment in _entity_segments(text):
        tokens = _ENTITY_TOKEN_RE.findall(segment)
        index = 0
        while index < len(tokens):
            token = tokens[index].rstrip(".")
            if not token:
                index += 1
                continue
            if _is_dotted_initialism(token):
                parts = [token]
                cursor = index + 1
                while cursor < len(tokens):
                    candidate = tokens[cursor].rstrip(".")
                    if not _is_title_token(candidate):
                        break
                    parts.append(candidate)
                    cursor += 1
                entity = " ".join(parts)
                _append_entity_if_source_backed(entities, entity, segment)
                index = cursor
                continue
            if _is_brand_token(token):
                _append_entity_if_source_backed(entities, token, segment)
                index += 1
                continue

            if not _is_title_token(token):
                index += 1
                continue

            parts = [token]
            cursor = index + 1
            title_parts = 1
            while cursor < len(tokens):
                candidate = tokens[cursor].rstrip(".")
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
                    _append_entity_if_source_backed(entities, entity, segment)
                index = cursor
                continue
            index += 1
    return tuple(_dedupe_entities(entities))


def _entity_segments(text: str) -> tuple[str, ...]:
    """Split entity candidates without breaking dotted/acronym/legal tokens."""
    coarse: list[str] = []
    for segment in _ENTITY_BOUNDARY_RE.split(text or ""):
        start = 0
        for comma in _ENTITY_COMMA_RE.finditer(segment):
            if _LEGAL_SUFFIX_AFTER_COMMA_RE.match(segment[comma.end() :]):
                continue
            coarse.append(segment[start : comma.start()])
            start = comma.end()
        coarse.append(segment[start:])

    output: list[str] = []
    for segment in coarse:
        start = 0
        for period in re.finditer(r"\.(?=\s+[A-Z])", segment):
            prefix = segment[start : period.start()]
            token_match = re.search(r"([A-Za-z][A-Za-z.]*)$", prefix)
            token = token_match.group(1).casefold() if token_match is not None else ""
            dotted_token = f"{token}."
            is_initialism = re.fullmatch(r"(?:[a-z]\.)+[a-z]\.", dotted_token) is not None
            if token in _NONTERMINAL_PERIOD_TOKENS or is_initialism:
                continue
            output.append(segment[start : period.start()])
            start = period.end()
        output.append(segment[start:])
    return tuple(part for part in output if part.strip())


def _append_entity_if_source_backed(entities: list[str], entity: str, source_segment: str) -> None:
    """Append only an entity that the shared canonicalizer finds in its source."""
    if _contains_fact(source_segment, entity):
        entities.append(entity)


def _profile_facts(profile: Profile, raw_source: str) -> list[_SourceFact]:
    facts: list[_SourceFact] = []

    def add(label: str, fact: str, source_span: str = "") -> None:
        if _meaningful_fact(fact):
            facts.append(
                _SourceFact(
                    label,
                    fact.strip(),
                    source_span or _source_span_for_fact(raw_source, fact),
                )
            )

    for experience_facts in _experience_source_facts(profile, raw_source):
        facts.extend(experience_facts)
    for experience in profile.experiences:
        if "remote" in experience.location.casefold():
            add("remote work mode", "remote")

    if "remote" in profile.contact.location.casefold() or "remote" in profile.contact.work_mode.casefold():
        add("remote work mode", "remote")

    for education in profile.education:
        add("education institution", education.institution)
        add("education degree", education.degree)
        add("education dates", education.dates)
        add("education location", education.location)
        for detail in education.bullets:
            add("education detail", detail)

    for certification in profile.certifications:
        add("certification", certification.name)
        if certification.credential_id:
            add("certification credential ID", certification.credential_id)

    for heading, lines in profile.remaining_sections:
        add("source section heading", heading)
        for line in lines:
            add(f"{heading or 'additional'} source detail", line)

    for metric in [*find_metrics(raw_source), *profile.supported_metrics]:
        add("metric", metric)
    return facts


_EXPERIENCE_FACT_FIELDS: tuple[tuple[str, str], ...] = (
    ("employer", "company"),
    ("title", "title"),
    ("dates", "dates"),
    ("location", "location"),
)


def _experience_source_facts(
    profile: Profile,
    raw_source: str,
) -> list[tuple[_SourceFact, ...]]:
    """Return protected experience fields with entry-specific source spans.

    Titles and locations commonly repeat across a career. Using the first
    global occurrence for every repeated fact would make two distinct source
    entries share one calibration identity. Anchor each experience at its
    employer line and search only until the next experience instead.
    """
    lines = (raw_source or "").splitlines()
    starts: list[int] = []
    cursor = 0
    for experience in profile.experiences:
        start = _find_fact_line(lines, experience.company, cursor, len(lines))
        if start is None:
            start = _find_fact_line(lines, experience.title, cursor, len(lines))
        if start is None:
            start = cursor
        starts.append(start)
        cursor = min(start + 1, len(lines))

    output: list[tuple[_SourceFact, ...]] = []
    for index, experience in enumerate(profile.experiences):
        start = starts[index] if index < len(starts) else 0
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        entry_facts: list[_SourceFact] = []
        for label, attribute in _EXPERIENCE_FACT_FIELDS:
            fact = str(getattr(experience, attribute, "") or "").strip()
            if not _meaningful_fact(fact):
                continue
            line_index = _find_fact_line(lines, fact, start, end)
            source_span = (
                f"source:line:{line_index + 1}" if line_index is not None else _source_span_for_fact(raw_source, fact)
            )
            entry_facts.append(_SourceFact(label, fact, source_span))
        output.append(tuple(entry_facts))
    return output


def _find_fact_line(
    lines: Sequence[str],
    fact: str,
    start: int,
    end: int,
) -> int | None:
    if not _meaningful_fact(fact):
        return None
    for index in range(max(0, start), min(len(lines), max(start, end))):
        if _contains_fact(lines[index], fact):
            return index
    return None


def _experience_tuple_findings(
    profile: Profile,
    candidate_experiences: Sequence[Experience],
    raw_source: str,
    detector_version: str,
) -> list[ValidationFinding]:
    """Require each source experience's protected facts to coexist in one entry.

    The comparison is order-independent. Exact employer matches are assigned
    first, then any remaining source/candidate entries are paired by their
    strongest protected-field overlap. This allows legitimate résumé
    reordering while preventing a repeated title elsewhere from masking its
    deletion from the role where the candidate actually held it.
    """
    source_facts = _experience_source_facts(profile, raw_source)
    matches = match_experience_indices(profile.experiences, candidate_experiences)

    findings: list[ValidationFinding] = []
    for source_index, entry_facts in enumerate(source_facts):
        candidate_index = matches[source_index]
        candidate = candidate_experiences[candidate_index] if candidate_index is not None else None
        for source_fact in entry_facts:
            candidate_value = (
                str(getattr(candidate, _experience_attribute(source_fact.label), "") or "")
                if candidate is not None
                else ""
            )
            if _contains_fact(candidate_value, source_fact.fact):
                continue
            findings.append(
                _finding(
                    FIDELITY_MISSING_SOURCE_FACT,
                    fact=source_fact.fact,
                    source_span=source_fact.source_span,
                    detail=(f"fidelity: missing source {source_fact.label}: {source_fact.fact}"),
                    detector_version=detector_version,
                )
            )
    return findings


def match_experience_indices(
    source_experiences: Sequence[Experience],
    candidate_experiences: Sequence[Experience],
) -> tuple[int | None, ...]:
    """Map source experiences to candidate entries without relying on order."""
    matches: dict[int, int] = {}
    unused_candidates = set(range(len(candidate_experiences)))

    # A company is normally the strongest stable role anchor. Resolve all
    # exact company pairs first so an entirely missing entry cannot shift every
    # later source role onto the wrong candidate role.
    for source_index, source_experience in enumerate(source_experiences):
        candidates = [
            candidate_index
            for candidate_index in unused_candidates
            if _contains_fact(
                candidate_experiences[candidate_index].company,
                source_experience.company,
            )
        ]
        if not candidates:
            continue
        candidate_index = max(
            candidates,
            key=lambda index: (
                _experience_match_score(source_experience, candidate_experiences[index]),
                -index,
            ),
        )
        matches[source_index] = candidate_index
        unused_candidates.remove(candidate_index)

    # If an employer itself was deleted, the remaining tuple fields still
    # identify the corresponding role. Pair unmatched entries only after all
    # source-backed company anchors have been reserved.
    for source_index, source_experience in enumerate(source_experiences):
        if source_index in matches or not unused_candidates:
            continue
        candidate_index = max(
            unused_candidates,
            key=lambda index: (
                _experience_match_score(source_experience, candidate_experiences[index]),
                -index,
            ),
        )
        matches[source_index] = candidate_index
        unused_candidates.remove(candidate_index)
    return tuple(matches.get(index) for index in range(len(source_experiences)))


def match_bullet_indices(
    source_bullets: Sequence[str],
    candidate_bullets: Sequence[str],
) -> tuple[int | None, ...]:
    """Map source bullets to candidates while allowing evidence-safe reordering."""
    matches: dict[int, int] = {}
    unused_candidates = set(range(len(candidate_bullets)))

    # Preserve exact candidate wording first. This makes pure reordering
    # unambiguous even when two bullets share much of their vocabulary.
    for source_index, source_bullet in enumerate(source_bullets):
        source_key = canonicalize_fact(source_bullet)
        candidate_index = next(
            (index for index in sorted(unused_candidates) if canonicalize_fact(candidate_bullets[index]) == source_key),
            None,
        )
        if candidate_index is None:
            continue
        matches[source_index] = candidate_index
        unused_candidates.remove(candidate_index)

    # Rewritten bullets retain facts but not necessarily exact wording. Pair
    # the remaining items by protected-fact and content-token overlap, then let
    # the authoritative bullet validator decide whether the rewrite is safe.
    for source_index, source_bullet in enumerate(source_bullets):
        if source_index in matches or not unused_candidates:
            continue
        candidate_index = max(
            unused_candidates,
            key=lambda index: (
                _bullet_match_score(source_bullet, candidate_bullets[index]),
                -index,
            ),
        )
        matches[source_index] = candidate_index
        unused_candidates.remove(candidate_index)
    return tuple(matches.get(index) for index in range(len(source_bullets)))


def _bullet_match_score(source: str, candidate: str) -> int:
    source_terms = set(_content_terms(source))
    candidate_terms = set(_content_terms(candidate))
    overlap = len(source_terms & candidate_terms)
    protected = [
        *find_metrics(source),
        *_team_facts(source),
        *extract_named_entities(source),
    ]
    protected_matches = sum(_contains_fact(candidate, fact) for fact in protected)
    return protected_matches * 100 + overlap


def _experience_match_score(source: Experience, candidate: Experience) -> int:
    weights = {"company": 16, "title": 8, "dates": 4, "location": 2}
    return sum(
        weight
        for attribute, weight in weights.items()
        if _meaningful_fact(str(getattr(source, attribute, "") or ""))
        and _contains_fact(
            str(getattr(candidate, attribute, "") or ""),
            str(getattr(source, attribute, "") or ""),
        )
    )


def _experience_attribute(label: str) -> str:
    return {
        "employer": "company",
        "title": "title",
        "dates": "dates",
        "location": "location",
    }[label]


def _unsupported_candidate_metric_findings(
    source_text: str,
    candidate_text: str,
    detector_version: str,
) -> list[ValidationFinding]:
    source_metrics = _normalized_metric_set(source_text)
    candidate_metrics = _normalized_metric_set(candidate_text)
    return [
        _finding(
            FIDELITY_UNSUPPORTED_METRIC,
            fact=metric,
            source_span=_source_span_for_fact(candidate_text, metric, namespace="candidate"),
            detail=f"fidelity: unsupported metric introduced: {metric}",
            detector_version=detector_version,
        )
        for metric in sorted(candidate_metrics - source_metrics)
    ]


def _unsupported_credential_id_findings(
    source_text: str,
    candidate_text: str,
    detector_version: str,
) -> list[ValidationFinding]:
    source_ids = {match.group(0).casefold() for match in _CREDENTIAL_ID_RE.finditer(source_text or "")}
    candidate_ids = {match.group(0).casefold() for match in _CREDENTIAL_ID_RE.finditer(candidate_text or "")}
    return [
        _finding(
            FIDELITY_UNSUPPORTED_CREDENTIAL_ID,
            fact=credential_id.upper(),
            source_span=_source_span_for_fact(candidate_text, credential_id, namespace="candidate"),
            detail=f"fidelity: unsupported certification credential ID introduced: {credential_id.upper()}",
            detector_version=detector_version,
        )
        for credential_id in sorted(candidate_ids - source_ids)
    ]


def _normalized_metric_set(text: str) -> set[str]:
    return {canonicalize_fact(metric) for metric in find_metrics(text) if canonicalize_fact(metric)}


def _team_facts(text: str) -> tuple[str, ...]:
    return tuple(_dedupe_strings(match.group(0).strip() for match in _TEAM_FACT_RE.finditer(text or "")))


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
    return retained / len(required_terms) >= 0.75


def _content_terms(text: str) -> tuple[str, ...]:
    canonical = canonicalize_fact(text)
    terms = [
        token.casefold()
        for token in _CONTENT_TOKEN_RE.findall(canonical)
        if len(token) > 2 and token.casefold() not in _CONTENT_STOP_WORDS
    ]
    return tuple(_dedupe_strings(terms))


def _contains_fact(text: str, fact: str) -> bool:
    needle = canonicalize_fact(fact)
    haystack = canonicalize_fact(text)
    if not needle or not haystack:
        return False
    return needle == haystack or f" {needle} " in f" {haystack} "


def contains_fact(text: str, fact: str) -> bool:
    """Public shared-canonicalizer fact containment helper for validators/tests."""
    return _contains_fact(text, fact)


def _source_span_for_fact(text: str, fact: str, *, namespace: str = "source") -> str:
    """Return a stable line span for calibration identity and diagnostics."""
    for line_number, line in enumerate((text or "").splitlines(), start=1):
        if _contains_fact(line, fact):
            return f"{namespace}:line:{line_number}"
    return f"{namespace}:unknown"


def _meaningful_fact(value: str) -> bool:
    normalized = canonicalize_fact(value)
    return len(normalized) >= 2 and normalized not in {"n a", "na", "none", "unknown"}


def _is_title_token(token: str) -> bool:
    if token in _GENERIC_ENTITY_WORDS:
        return False
    return len(token) > 1 and token[0].isupper() and token[1:].islower()


def _is_brand_token(token: str) -> bool:
    stripped = token.strip(".,;:()[]{}\"'“”‘’")
    if stripped in _GENERIC_ENTITY_WORDS or len(stripped) < 2:
        return False
    # Two-letter slash fragments such as ``CI/CD`` are capability notation,
    # not standalone named entities. Keeping them out avoids a source-stable
    # projection spuriously reporting ``CI`` or ``CD`` as lost.
    if len(stripped) >= 4 and stripped.isupper() and any(character.isalpha() for character in stripped):
        return True
    if not stripped.isupper() and any(character.isupper() for character in stripped[1:]):
        return True
    return "-" in stripped and any(character.isupper() for character in stripped)


def _is_dotted_initialism(token: str) -> bool:
    return re.fullmatch(r"(?:[A-Z]\.)+[A-Z]", token) is not None


def _finding(
    code: str,
    *,
    fact: str,
    source_span: str,
    detail: str,
    detector_version: str,
) -> ValidationFinding:
    return ValidationFinding(
        code=code,
        severity=severity_for_code(code),
        fact=fact,
        source_span=source_span or "source:unknown",
        detail=detail,
        detector_version=detector_version,
    )


def _with_detail_prefix(
    findings: Iterable[ValidationFinding],
    prefix: str,
) -> list[ValidationFinding]:
    return [
        ValidationFinding(
            code=finding.code,
            severity=finding.severity,
            fact=finding.fact,
            source_span=finding.source_span,
            detail=f"{prefix}: {finding.detail}",
            detector_version=finding.detector_version,
        )
        for finding in findings
    ]


def _legacy_errors(findings: Iterable[ValidationFinding]) -> list[str]:
    return _dedupe_strings(str(finding) for finding in findings if finding.code != CAL_FALSE_POSITIVE)


def _dedupe_findings(findings: Iterable[ValidationFinding]) -> tuple[ValidationFinding, ...]:
    seen: set[tuple[str, str, str, str, str, str]] = set()
    output: list[ValidationFinding] = []
    for finding in findings:
        key = (
            finding.detector_version,
            finding.code,
            finding.normalized_fact,
            finding.source_span,
            finding.detail,
            finding.severity.value,
        )
        if key not in seen:
            seen.add(key)
            output.append(finding)
    return tuple(output)


def _dedupe_entities(values: Iterable[str]) -> list[str]:
    """Deduplicate entity displays using the same canonical fact identity."""
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        key = canonicalize_fact(value)
        if key and key not in seen:
            seen.add(key)
            output.append(value)
    return output


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


__all__ = [
    "BulletPair",
    "CalibrationKey",
    "CalibrationProfile",
    "FIDELITY_DETECTOR_VERSION",
    "FidelityReport",
    "ValidationFinding",
    "ValidationSeverity",
    "bullet_fidelity_errors",
    "bullet_fidelity_findings",
    "bullet_preserves_facts",
    "canonicalize_fact",
    "contains_fact",
    "extract_named_entities",
    "match_bullet_indices",
    "match_experience_indices",
    "validate_raw_source_fidelity",
    "validate_raw_source_findings",
    "validate_resume_fidelity",
]
