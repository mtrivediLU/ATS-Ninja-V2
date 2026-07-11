from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ats_engine.kit.contract import (
    CLAIM_TEXT_MAX_CHARS,
    EVIDENCE_EXCERPT_MAX_CHARS,
    ArtifactKind,
    ClaimRecord,
    ClaimStatus,
    ClaimType,
    EvidenceRef,
)
from ats_engine.models import JDProfile, Profile
from ats_engine.validation.claims import HIGH_RISK_METRIC_PATTERN

"""Structured claim extraction and evidence grounding — the Phase 2A truth gate.

Generated prose is untrusted. This module turns each candidate-specific claim in
that prose into a structured :class:`ClaimRecord`, classifies whether the
candidate's own evidence supports it, and — for anything unsupported —
deterministically removes it so the fabricated value is **absent** from the final
artifact (or, if it cannot be removed cleanly, reports the artifact as fatally
invalid so it can be withheld). See ADR-0009 and ADR-0011.

Design tenets:

- **Evidence-first support test.** A claim is supported only if it traces to the
  candidate's own resume evidence (structured profile fields plus the raw
  resume). The job description is a *targeting* source, never candidate evidence,
  with one deliberate exception: naming the target company/role is allowed (it is
  not a claim about the candidate's history).
- **Precision over recall on removal.** Removal can never make a fabrication
  survive, so the cost of a false positive is only lost (truthful) wording, and
  the cost of a false negative is a shipped fabrication. Extractors are tuned to
  be confident; the repair pass is deterministic and bounded (one pass).
- **All artifacts, not just the resume.** Cover letters and application answers
  can hallucinate candidate facts too, so the same gate runs over their prose.
"""

# Well-known employers used to catch the most common fabrication ("worked at
# Google"). Any of these appearing as a candidate employer that is not in the
# candidate's own evidence is unsupported. This is a recall aid on top of the
# generic org-suffix detector below; it is intentionally not exhaustive.
_KNOWN_EMPLOYERS: frozenset[str] = frozenset(
    {
        "google",
        "alphabet",
        "amazon",
        "aws",
        "microsoft",
        "meta",
        "facebook",
        "apple",
        "netflix",
        "ibm",
        "oracle",
        "salesforce",
        "uber",
        "lyft",
        "airbnb",
        "tesla",
        "spacex",
        "twitter",
        "linkedin",
        "adobe",
        "intel",
        "nvidia",
        "deloitte",
        "accenture",
        "mckinsey",
        "goldman sachs",
        "jpmorgan",
        "stripe",
        "shopify",
        "spotify",
        "openai",
        "anthropic",
    }
)

_ORG_SUFFIXES = (
    "inc",
    "llc",
    "corp",
    "corporation",
    "ltd",
    "limited",
    "technologies",
    "analytics",
    "labs",
    "systems",
    "solutions",
    "group",
    "software",
    "consulting",
    "capital",
    "ventures",
    "partners",
    "holdings",
    "industries",
    "networks",
    "motors",
)

_ORG_SUFFIX_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+){0,3})\s+(" + "|".join(_ORG_SUFFIXES) + r")\b"
)

_EMPLOYER_CONTEXT = re.compile(
    r"\b(?:at|for|with|by|joined|employed\s+(?:at|by)|worked\s+at)\s+([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+){0,3})"
)

# Executive titles are flagged wherever they appear (they are essentially never
# the candidate's real role unless the resume shows it); ambiguous senior titles
# (director/head/principal/...) are flagged only in an explicit self-claim.
_EXEC_TITLE = re.compile(
    r"\b(chief\s+[a-z]+\s+officer|chief\s+[a-z]+|c\.?\s*[etfoi]\.?\s*o\.?|vice\s+president|"
    r"v\.?\s*p\.?|founder|co-founder|"
    r"founding\s+(?:engineer|developer|architect|designer))\b",
    re.IGNORECASE,
)
_SELF_TITLE = re.compile(
    r"\b(?:as|became|promoted\s+to|served\s+as|worked\s+as|role\s+as|title\s+(?:of|was)|position\s+of|i\s+was|i\s+am)\s+"
    r"(?:an?|the)?\s*"
    r"((?:director|head(?:\s+of|,)?|principal|staff\s+engineer|senior\s+director|managing\s+director|executive)"
    r"[a-z, ]{0,35})",
    re.IGNORECASE,
)

_SKILL_CLAIM = re.compile(
    r"\b(?:expert(?:ise)?|mastery|proficient|proficiency|advanced|specialist|specializ(?:ed|ing)|"
    r"deep\s+(?:expertise|knowledge)|fluent|seasoned|highly\s+skilled|world-class|"
    r"familiar\s+with|working\s+knowledge\s+of|hands-on\s+(?:with|experience\s+(?:in|with))|"
    r"skilled\s+in|competent\s+in|versed\s+in|experience\s+(?:in|with))\b"
    r"(?:\s+(?:in|with|at|of|level))?\s+"
    r"([A-Za-z][A-Za-z0-9+.#/-]*(?:\s+[A-Za-z0-9+.#/-]+){0,2})",
    re.IGNORECASE,
)

# Common technologies that may appear lowercased; used so a skill claim on a real
# tool name is recognized even without capitalization in the generated prose.
_KNOWN_TECH: frozenset[str] = frozenset(
    {
        "python",
        "java",
        "javascript",
        "typescript",
        "rust",
        "golang",
        "go",
        "c++",
        "c#",
        "ruby",
        "php",
        "scala",
        "kotlin",
        "swift",
        "sql",
        "postgresql",
        "postgres",
        "mysql",
        "mongodb",
        "redis",
        "kafka",
        "spark",
        "hadoop",
        "airflow",
        "kubernetes",
        "docker",
        "terraform",
        "aws",
        "azure",
        "gcp",
        "tableau",
        "react",
        "angular",
        "vue",
        "django",
        "flask",
        "fastapi",
        "pytorch",
        "tensorflow",
    }
)

# Words that follow an expertise verb but are not skills (avoid false positives
# like "highly skilled professional").
_SKILL_STOPWORDS: frozenset[str] = frozenset(
    {
        "professional",
        "engineer",
        "developer",
        "individual",
        "communicator",
        "leader",
        "team",
        "work",
        "delivery",
        "environments",
        "environment",
        "systems",
        "solutions",
        "people",
        "person",
        "candidate",
        "generalist",
        "contributor",
        "problem",
        "technologies",
        "domains",
        "areas",
    }
)

_CERT_PATTERN = re.compile(
    r"\b("
    r"aws\s+certified[\w \-]*"
    r"|azure\s+(?:certified|solutions\s+architect|administrator|developer)[\w \-]*"
    r"|google\s+cloud\s+(?:certified|professional)[\w \-]*"
    r"|certified\s+[a-z][\w \-]*?(?=[.,;:]|\s+(?:and|with|in|to|for)\b|$)"
    r"|[A-Za-z][\w \-]*?\s+certification"
    r"|pmp|cissp|cfa|cpa|ccna|ccnp|ckad|cka|togaf|pmi-acp|comptia\s+[a-z+]+"
    r")\b",
    re.IGNORECASE,
)

_DEGREE_PATTERN = re.compile(
    r"\b("
    r"ph\.?\s?d\.?|doctorate|doctoral"
    r"|m\.?b\.?a\.?|master(?:'s|s)?(?:\s+(?:of|in|'?s\s+in)\s+[a-z ]+?)?|m\.?sc\.?|m\.?s\.?(?=\s+in\b)"
    r"|bachelor(?:'s|s)?(?:\s+(?:of|in)\s+[a-z ]+?)?|b\.?sc\.?|b\.?a\.?(?=\s+in\b)"
    r"|associate(?:'s)?\s+degree"
    r")\b",
    re.IGNORECASE,
)

# Spelled-out metric variants the structured HIGH_RISK_METRIC_PATTERN misses:
# "47 percent" (vs "47%"), "2.4 million dollars" (vs "$2.4M"). Catching these is
# what closes the "47 percent" / "$2.4 million" adversarial bypasses (ADR-0011).
_EXTRA_METRIC_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:percent|per\s+cent|percentage\s+points?|pct)\b"
    r"|\b(?:usd|cad|eur|gbp)\s*\$?\s*\d[\d,]*(?:\.\d+)?\s*(?:thousand|million|billion|trillion|k|m|mm|bn|b)?\b"
    r"|(?:\$\s*)?\b\d[\d,]*(?:\.\d+)?\s*(?:million|billion|thousand|trillion|k|m|mm|bn|b)?\s*"
    r"(?:dollars|usd|cad|eur|euros|pounds|gbp)\b"
    r"|\b\d[\d,]*(?:\.\d+)?\s*(?:mm|bn)\b",
    flags=re.IGNORECASE,
)

_NUMBER_WORD_ATOM = (
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"hundred|thousand|million|billion)"
)
_NUMBER_WORDS = rf"{_NUMBER_WORD_ATOM}(?:[ -]+(?:and[ -]+)?{_NUMBER_WORD_ATOM})*"
_SPELLED_METRIC_PATTERN = re.compile(
    rf"\b{_NUMBER_WORDS}\s+(?:percent|per\s+cent|percentage\s+points?)\b"
    rf"|\b{_NUMBER_WORDS}\s+(?:dollars|usd|cad|euros?|pounds|gbp)\b"
    rf"|\b{_NUMBER_WORDS}\s+(?:engineers?|people|employees|staff|reports)\b",
    re.IGNORECASE,
)

_TENURE_PATTERN = re.compile(
    rf"\b(?P<years>\d{{1,2}}|{_NUMBER_WORDS})\s*\+?\s*(?:years?|yrs?)\b"
    r"|\b(?P<since>since\s+(?:19|20)\d{2})\b"
    r"|\b(?P<decade>(?:over\s+the\s+past|for\s+over\s+a|more\s+than\s+a|a)\s+decade)\b",
    re.IGNORECASE,
)

_MANAGEMENT_PATTERN = re.compile(
    r"\b((?:managed|supervised|co-led|helped\s+lead|led|oversaw|owned)\s+"
    r"(?:[a-z-]+\s+){0,5}(?:teams?|engineers?|employees|people|staff|reports|departments?|divisions?|"
    r"organizations?|org|roadmaps?|portfolios?))\b",
    re.IGNORECASE,
)

_CLIENT_OR_PROJECT_PATTERN = re.compile(
    r"\b((?:fortune\s+\d{3}|faang|big\s+tech|government|federal|provincial|state|municipal|banking|financial|hospital|"
    r"healthcare)\s+(?:[a-z]+\s+)?client)\b"
    r"|\b(project\s+[A-Z][A-Za-z0-9_-]+)\b",
    re.IGNORECASE,
)

_OTHER_CREDENTIAL_PATTERN = re.compile(
    rf"\b((?:[A-Z][A-Za-z-]+\s+){{1,5}}Award)\b"
    rf"|\b((?:\d+|{_NUMBER_WORDS})\s+patents?)\b"
    rf"|\b((?:\d+|{_NUMBER_WORDS})\s+(?:peer-reviewed\s+)?(?:papers?|publications?))\b"
    r"|\b((?:(?:active|current)\s+)?(?:top\s+secret|secret|confidential)\s+security\s+clearance)\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass(slots=True)
class EvidenceContext:
    """Precomputed, normalized view of the candidate's evidence for grounding."""

    evidence_text: str  # word-normalized candidate evidence for term membership
    evidence_metric: str  # metric-normalized candidate evidence for metric membership
    allowed_orgs: frozenset[str]  # candidate employers + schools
    target_org: str  # target company, allowed only as targeting (never history)
    real_title_tokens: frozenset[str]
    allowed_title_tokens: frozenset[str]  # candidate titles only
    target_title_tokens: frozenset[str]  # target role, allowed only as targeting
    skills: frozenset[str]
    max_degree_level: int
    career_years: int


@dataclass(slots=True)
class _RawClaim:
    claim_type: ClaimType
    text: str
    start: int
    end: int
    supported: bool
    reason: str
    evidence: list[EvidenceRef] = field(default_factory=list)


@dataclass(slots=True)
class GroundingOutcome:
    """Result of grounding one piece of generated text."""

    clean_text: str
    claims: list[ClaimRecord]
    fatal: bool = False
    repaired: int = 0
    rejected: int = 0


_DEGREE_LEVELS: tuple[tuple[str, int], ...] = (
    ("phd", 4),
    ("ph.d", 4),
    ("doctor", 4),
    ("mba", 3),
    ("master", 3),
    ("msc", 3),
    ("m.sc", 3),
    ("m.s", 3),
    ("bachelor", 2),
    ("bsc", 2),
    ("b.sc", 2),
    ("b.a", 2),
    ("b.s", 2),
    ("associate", 1),
)


def _word_normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _metric_normalize(text: str) -> str:
    lowered = (text or "").lower().replace(",", "")
    lowered = lowered.replace("per cent", "%").replace("percent", "%")
    word_match = re.match(
        rf"^({_NUMBER_WORDS})(?=\s+(?:%|dollars|usd|cad|euros?|pounds|gbp|years?|yrs?|engineers?|people|employees|staff|reports|patents?))",
        lowered,
    )
    if word_match:
        value = _parse_number_words(word_match.group(1))
        if value is not None:
            lowered = str(value) + lowered[word_match.end() :]
    lowered = lowered.replace("million", "m").replace("billion", "b").replace("thousand", "k")
    return re.sub(r"\s+", "", lowered)


_SMALL_NUMBER_WORDS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


def _parse_number_words(text: str) -> int | None:
    """Parse the bounded English number grammar used by claim extractors."""
    tokens = re.findall(r"[a-z]+", text.lower().replace("-", " "))
    if not tokens:
        return None
    total = 0
    current = 0
    for token in tokens:
        if token == "and":
            continue
        if token in _SMALL_NUMBER_WORDS:
            current += _SMALL_NUMBER_WORDS[token]
        elif token == "hundred":
            current = max(1, current) * 100
        elif token in {"thousand", "million", "billion"}:
            scale = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}[token]
            total += max(1, current) * scale
            current = 0
        else:
            return None
    return total + current


def _degree_level(text: str) -> int:
    lowered = text.lower().replace(" ", "")
    for marker, level in _DEGREE_LEVELS:
        if marker.replace(" ", "") in lowered:
            return level
    return 0


def _career_years(profile: Profile) -> int:
    years: list[int] = []
    current = False
    for experience in profile.experiences:
        years.extend(int(match) for match in re.findall(r"(?:19|20)\d{2}", experience.dates))
        if re.search(r"present|current", experience.dates, flags=re.IGNORECASE):
            current = True
    if not years:
        return 0
    from datetime import datetime

    end = datetime.now().year if current else max(years)
    return max(0, end - min(years))


def build_evidence_context(profile: Profile, jd_profile: JDProfile) -> EvidenceContext:
    """Precompute the normalized candidate-evidence view used by all extractors."""
    evidence_parts: list[str] = [profile.raw_markdown]
    for experience in profile.experiences:
        evidence_parts.extend([experience.company, experience.title, experience.dates, *experience.bullets])
    for education in profile.education:
        evidence_parts.extend([education.institution, education.degree, education.dates, *education.bullets])
    for cert in profile.certifications:
        evidence_parts.append(cert.name)
    for tier in (profile.tier_a, profile.tier_b, profile.tier_c):
        evidence_parts.extend(tier.keys())
        evidence_parts.extend(tier.values())
    evidence_parts.extend(profile.role_identities)
    evidence_parts.extend(profile.adjacency.values())

    joined = " ".join(part for part in evidence_parts if part)
    evidence_text = _word_normalize(joined)
    evidence_metric = _metric_normalize(joined)

    allowed_orgs = {_word_normalize(experience.company) for experience in profile.experiences if experience.company}
    allowed_orgs |= {_word_normalize(education.institution) for education in profile.education if education.institution}
    target_org = (
        _word_normalize(jd_profile.company) if jd_profile.company and jd_profile.company != "Target Company" else ""
    )

    real_title_tokens: set[str] = set()
    for experience in profile.experiences:
        real_title_tokens |= _title_tokens(experience.title)
    for role in profile.role_identities:
        real_title_tokens |= _title_tokens(role)
    allowed_title_tokens = set(real_title_tokens)
    target_title_tokens = (
        _title_tokens(jd_profile.title) if jd_profile.title and jd_profile.title != "Target Role" else set()
    )

    skills: set[str] = set()
    for tier in (profile.tier_a, profile.tier_b, profile.tier_c):
        for key, value in tier.items():
            skills.add(_word_normalize(key))
            skills.add(_word_normalize(value))

    max_degree_level = max((_degree_level(education.degree) for education in profile.education), default=0)

    return EvidenceContext(
        evidence_text=evidence_text,
        evidence_metric=evidence_metric,
        allowed_orgs=frozenset(org for org in allowed_orgs if org),
        target_org=target_org,
        real_title_tokens=frozenset(real_title_tokens),
        allowed_title_tokens=frozenset(allowed_title_tokens),
        target_title_tokens=frozenset(target_title_tokens),
        skills=frozenset(skill for skill in skills if skill),
        max_degree_level=max_degree_level,
        career_years=_career_years(profile),
    )


def _title_tokens(title: str) -> set[str]:
    return {token for token in re.findall(r"[a-z]+", (title or "").lower()) if len(token) > 2}


def _term_present(term: str, haystack: str) -> bool:
    term = term.strip().lower()
    if not term:
        return False
    return bool(re.search(rf"(?<![\w+#]){re.escape(term)}(?![\w+#])", haystack))


def _org_allowed(org: str, context: EvidenceContext, *, candidate_history: bool) -> bool:
    normalized = _word_normalize(org)
    if not normalized:
        return True
    if _term_present(normalized, context.evidence_text):
        return True
    if any(normalized in allowed or allowed in normalized for allowed in context.allowed_orgs):
        return True
    return (
        not candidate_history
        and bool(context.target_org)
        and (normalized in context.target_org or context.target_org in normalized)
    )


def _bounded(text: str, limit: int) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed[:limit]


def _evidence_ref(locator: str, value: str) -> EvidenceRef:
    return EvidenceRef(source="candidate-resume", locator=locator, excerpt=_bounded(value, EVIDENCE_EXCERPT_MAX_CHARS))


# --------------------------------------------------------------------------- #
# Extractors
# --------------------------------------------------------------------------- #
def _extract_metrics(text: str, context: EvidenceContext) -> list[_RawClaim]:
    claims: list[_RawClaim] = []
    seen: list[tuple[int, int]] = []
    for pattern in (HIGH_RISK_METRIC_PATTERN, _EXTRA_METRIC_PATTERN, _SPELLED_METRIC_PATTERN):
        for match in pattern.finditer(text):
            span = (match.start(), match.end())
            if any(span[0] < end and start < span[1] for start, end in seen):
                continue
            seen.append(span)
            raw = match.group(0).strip()
            normalized = _metric_normalize(raw)
            supported = bool(normalized) and normalized in context.evidence_metric
            claims.append(
                _RawClaim(
                    claim_type=_metric_type(raw),
                    text=raw,
                    start=span[0],
                    end=span[1],
                    supported=supported,
                    reason="metric present in candidate evidence"
                    if supported
                    else "metric absent from candidate evidence",
                    evidence=[_evidence_ref("supported_metric", raw)] if supported else [],
                )
            )
    return claims


def _metric_type(raw: str) -> ClaimType:
    lowered = raw.lower()
    if "$" in lowered or re.search(r"dollars|usd|cad|eur|euros|pounds|gbp|\d(?:\.\d+)?\s*(?:mm|bn)\b", lowered):
        return ClaimType.MONETARY
    if re.search(r"engineers?|people|employees|staff|reports|team\s+of", lowered):
        return ClaimType.TEAM_SIZE
    return ClaimType.METRIC


def _extract_employers(text: str, context: EvidenceContext) -> list[_RawClaim]:
    claims: list[_RawClaim] = []
    seen: set[tuple[int, int]] = set()

    for match in _EMPLOYER_CONTEXT.finditer(text):
        org = match.group(1)
        if _word_normalize(org) in _SOFT_ORG_WORDS:
            continue
        candidate_history = _candidate_history_near(text, (match.start(1), match.end(1)))
        if not (_word_normalize(org) in _KNOWN_EMPLOYERS or _looks_like_org(org) or candidate_history):
            continue
        span = (match.start(1), match.end(1))
        seen.add(span)
        claims.append(_employer_claim(org, span, context, candidate_history=candidate_history))

    for match in _ORG_SUFFIX_PATTERN.finditer(text):
        span = (match.start(), match.end())
        if span in seen:
            continue
        claims.append(
            _employer_claim(match.group(0), span, context, candidate_history=_candidate_history_near(text, span))
        )

    for token in _KNOWN_EMPLOYERS:
        for match in re.finditer(rf"(?<![\w])({re.escape(token)})(?![\w])", text, flags=re.IGNORECASE):
            span = (match.start(1), match.end(1))
            if any(s <= span[0] < e for s, e in seen):
                continue
            seen.add(span)
            claims.append(
                _employer_claim(match.group(1), span, context, candidate_history=_candidate_history_near(text, span))
            )

    return claims


_SOFT_ORG_WORDS: frozenset[str] = frozenset({"the", "a", "an", "our", "your", "their", "this", "that", "them", "us"})


def _looks_like_org(org: str) -> bool:
    lowered = org.lower()
    return any(lowered.endswith(suffix) or f" {suffix}" in f" {lowered}" for suffix in _ORG_SUFFIXES)


def _candidate_history_near(
    text: str,
    span: tuple[int, int],
    *,
    identity_language: bool = False,
) -> bool:
    window = text[max(0, span[0] - 70) : min(len(text), span[1] + 70)]
    history = bool(
        re.search(
            r"\b(?:worked|employed|joined|served|built|led|managed|delivered|consulted|promoted|became|career|"
            r"experience)\b",
            window,
            re.IGNORECASE,
        )
    )
    if identity_language:
        history = history or bool(re.search(r"\bi\s+(?:am|was)\b", window, re.IGNORECASE))
    return history


def _employer_claim(
    org: str,
    span: tuple[int, int],
    context: EvidenceContext,
    *,
    candidate_history: bool,
) -> _RawClaim:
    supported = _org_allowed(org, context, candidate_history=candidate_history)
    return _RawClaim(
        claim_type=ClaimType.EMPLOYER,
        text=org.strip(),
        start=span[0],
        end=span[1],
        supported=supported,
        reason="employer present in candidate evidence" if supported else "employer absent from candidate evidence",
        evidence=[_evidence_ref("experience", org)] if supported else [],
    )


def _extract_titles(text: str, context: EvidenceContext) -> list[_RawClaim]:
    claims: list[_RawClaim] = []
    seen: set[tuple[int, int]] = set()

    for match in _EXEC_TITLE.finditer(text):
        span = (match.start(1), match.end(1))
        seen.add(span)
        claims.append(
            _title_claim(
                match.group(1),
                span,
                context,
                candidate_history=_candidate_history_near(text, span, identity_language=True),
            )
        )

    for match in _SELF_TITLE.finditer(text):
        span = (match.start(1), match.end(1))
        if any(s <= span[0] < e for s, e in seen):
            continue
        claims.append(
            _title_claim(
                match.group(1),
                span,
                context,
                candidate_history=_candidate_history_near(text, span, identity_language=True),
            )
        )

    return claims


def _title_claim(
    title: str,
    span: tuple[int, int],
    context: EvidenceContext,
    *,
    candidate_history: bool,
) -> _RawClaim:
    # Support hinges on the *seniority* head token (director/chief/vp/head/...),
    # NOT on shared domain words: "Director of Data Engineering" must not count as
    # supported merely because the candidate is a "Data Analyst" (both say "data").
    normalized = _word_normalize(title)
    head = normalized.split()[0] if normalized else ""
    supported = head in context.allowed_title_tokens or _term_present(normalized, context.evidence_text)
    if not supported and not candidate_history:
        supported = head in context.target_title_tokens
    return _RawClaim(
        claim_type=ClaimType.TITLE,
        text=title.strip(),
        start=span[0],
        end=span[1],
        supported=supported,
        reason="title consistent with candidate evidence" if supported else "seniority/title not supported by evidence",
        evidence=[_evidence_ref("title", title)] if supported else [],
    )


def _extract_skills(text: str, context: EvidenceContext) -> list[_RawClaim]:
    claims: list[_RawClaim] = []
    seen: list[tuple[int, int]] = []
    for match in _SKILL_CLAIM.finditer(text):
        phrase = match.group(1).strip()
        head = phrase.split()[0] if phrase else ""
        normalized = _word_normalize(head)
        if not normalized or normalized in _SKILL_STOPWORDS:
            continue
        is_named_tech = head[:1].isupper() or normalized in _KNOWN_TECH or bool(re.search(r"[+#0-9]", head))
        supported = normalized in context.skills or _term_present(normalized, context.evidence_text)
        if supported:
            seen.append((match.start(1), match.end(1)))
            claims.append(
                _RawClaim(
                    claim_type=ClaimType.SKILL,
                    text=phrase,
                    start=match.start(1),
                    end=match.end(1),
                    supported=True,
                    reason="skill present in candidate evidence",
                    evidence=[_evidence_ref("skills", phrase)],
                )
            )
        elif is_named_tech:
            seen.append((match.start(1), match.end(1)))
            claims.append(
                _RawClaim(
                    claim_type=ClaimType.SKILL,
                    text=phrase,
                    start=match.start(1),
                    end=match.end(1),
                    supported=False,
                    reason="claimed skill/expertise absent from candidate evidence",
                )
            )

    # Expertise qualifiers are not required for a candidate-specific skill
    # claim: "I built production systems in Rust" is just as factual as "I am
    # an expert in Rust". Catch named technologies anywhere in generated prose,
    # except the highly ambiguous word "go" unless the explicit skill pattern
    # above already identified it.
    for tech in sorted(_KNOWN_TECH - {"go"}, key=len, reverse=True):
        for match in re.finditer(rf"(?<![\w+#]){re.escape(tech)}(?![\w+#])", text, re.IGNORECASE):
            span = (match.start(), match.end())
            if any(start <= span[0] < end for start, end in seen):
                continue
            raw = match.group(0)
            supported = _term_present(tech, context.evidence_text)
            claims.append(
                _RawClaim(
                    claim_type=ClaimType.SKILL,
                    text=raw,
                    start=span[0],
                    end=span[1],
                    supported=supported,
                    reason="skill present in candidate evidence"
                    if supported
                    else "claimed skill absent from candidate evidence",
                    evidence=[_evidence_ref("skills", raw)] if supported else [],
                )
            )
    return claims


def _extract_certifications(text: str, context: EvidenceContext) -> list[_RawClaim]:
    claims: list[_RawClaim] = []
    for match in _CERT_PATTERN.finditer(text):
        raw = match.group(0).strip()
        supported = _term_present(_word_normalize(raw), context.evidence_text)
        claims.append(
            _RawClaim(
                claim_type=ClaimType.CERTIFICATION,
                text=raw,
                start=match.start(),
                end=match.end(),
                supported=supported,
                reason="certification present in candidate evidence"
                if supported
                else "certification absent from candidate evidence",
                evidence=[_evidence_ref("certification", raw)] if supported else [],
            )
        )
    return claims


def _extract_degrees(text: str, context: EvidenceContext) -> list[_RawClaim]:
    claims: list[_RawClaim] = []
    for match in _DEGREE_PATTERN.finditer(text):
        raw = match.group(0).strip()
        level = _degree_level(raw)
        in_evidence = _term_present(_word_normalize(raw), context.evidence_text)
        supported = in_evidence or (level != 0 and level <= context.max_degree_level)
        claims.append(
            _RawClaim(
                claim_type=ClaimType.EDUCATION,
                text=raw,
                start=match.start(),
                end=match.end(),
                supported=supported,
                reason="degree consistent with candidate evidence"
                if supported
                else "degree exceeds or is absent from candidate evidence",
                evidence=[_evidence_ref("education", raw)] if supported else [],
            )
        )
    return claims


def _extract_tenure(text: str, context: EvidenceContext) -> list[_RawClaim]:
    claims: list[_RawClaim] = []
    for match in _TENURE_PATTERN.finditer(text):
        raw = match.group(0).strip()
        years_text = match.group("years")
        since_text = match.group("since")
        decade_text = match.group("decade")
        if years_text:
            years = int(years_text) if years_text.isdigit() else (_parse_number_words(years_text) or 0)
        elif since_text:
            from datetime import datetime

            years = datetime.now().year - int(re.search(r"\d{4}", since_text).group(0))  # type: ignore[union-attr]
        elif decade_text:
            years = 10
        else:
            years = 0
        in_evidence = _word_normalize(raw) in context.evidence_text or _metric_normalize(raw) in context.evidence_metric
        # Allow up to the candidate's real career span (+1 year of rounding).
        supported = years > 0 and (in_evidence or (context.career_years > 0 and years <= context.career_years + 1))
        claims.append(
            _RawClaim(
                claim_type=ClaimType.TENURE,
                text=raw,
                start=match.start(),
                end=match.end(),
                supported=supported,
                reason="tenure within candidate's real span" if supported else "tenure exceeds candidate's real span",
                evidence=[_evidence_ref("experience", raw)] if supported else [],
            )
        )
    return claims


def _extract_management(text: str, context: EvidenceContext) -> list[_RawClaim]:
    claims: list[_RawClaim] = []
    for match in _MANAGEMENT_PATTERN.finditer(text):
        raw = match.group(1).strip()
        supported = _term_present(_word_normalize(raw), context.evidence_text)
        claims.append(
            _RawClaim(
                claim_type=ClaimType.MANAGEMENT,
                text=raw,
                start=match.start(1),
                end=match.end(1),
                supported=supported,
                reason="management claim present in candidate evidence"
                if supported
                else "management claim absent from candidate evidence",
                evidence=[_evidence_ref("experience", raw)] if supported else [],
            )
        )
    return claims


def _extract_clients_and_projects(text: str, context: EvidenceContext) -> list[_RawClaim]:
    claims: list[_RawClaim] = []
    for match in _CLIENT_OR_PROJECT_PATTERN.finditer(text):
        raw = next(group for group in match.groups() if group is not None).strip()
        supported = _term_present(_word_normalize(raw), context.evidence_text)
        claims.append(
            _RawClaim(
                claim_type=ClaimType.EMPLOYER,
                text=raw,
                start=match.start(),
                end=match.end(),
                supported=supported,
                reason="client/project identity present in candidate evidence"
                if supported
                else "client/project identity absent from candidate evidence",
                evidence=[_evidence_ref("experience", raw)] if supported else [],
            )
        )
    return claims


def _extract_other_credentials(text: str, context: EvidenceContext) -> list[_RawClaim]:
    """Catch award, patent, and clearance credentials outside cert syntax."""
    claims: list[_RawClaim] = []
    for match in _OTHER_CREDENTIAL_PATTERN.finditer(text):
        raw = next(group for group in match.groups() if group is not None).strip()
        supported = _term_present(_word_normalize(raw), context.evidence_text)
        claims.append(
            _RawClaim(
                claim_type=ClaimType.CERTIFICATION,
                text=raw,
                start=match.start(),
                end=match.end(),
                supported=supported,
                reason="credential present in candidate evidence"
                if supported
                else "credential absent from candidate evidence",
                evidence=[_evidence_ref("certification", raw)] if supported else [],
            )
        )
    return claims


def _extract_claims(text: str, context: EvidenceContext) -> list[_RawClaim]:
    claims: list[_RawClaim] = []
    claims.extend(_extract_metrics(text, context))
    claims.extend(_extract_employers(text, context))
    claims.extend(_extract_titles(text, context))
    claims.extend(_extract_skills(text, context))
    claims.extend(_extract_certifications(text, context))
    claims.extend(_extract_degrees(text, context))
    claims.extend(_extract_tenure(text, context))
    claims.extend(_extract_management(text, context))
    claims.extend(_extract_clients_and_projects(text, context))
    claims.extend(_extract_other_credentials(text, context))
    return sorted(claims, key=lambda claim: claim.start)


# --------------------------------------------------------------------------- #
# Repair
# --------------------------------------------------------------------------- #
def _repair_prose(text: str, spans: list[tuple[int, int]]) -> str:
    """Remove whole sentences that overlap any unsupported span."""
    if not spans:
        return text
    sentences = _split_sentences(text)
    kept: list[str] = []
    for sentence_text, start, end in sentences:
        if any(span_start < end and start < span_end for span_start, span_end in spans):
            continue
        kept.append(sentence_text)
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def _repair_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Redact exact unsupported spans in place (used for candidate-authored bullets)."""
    if not spans:
        return text
    result = text
    for start, end in sorted(spans, key=lambda span: span[0], reverse=True):
        result = result[:start] + result[end:]
    result = re.sub(r"\s+([.,;:%])", r"\1", result)
    return re.sub(r"\s{2,}", " ", result).strip(" ,;-").strip()


def _split_sentences(text: str) -> list[tuple[str, int, int]]:
    sentences: list[tuple[str, int, int]] = []
    cursor = 0
    for piece in _SENTENCE_SPLIT.split(text):
        if not piece:
            continue
        index = text.find(piece, cursor)
        if index == -1:
            index = cursor
        sentences.append((piece, index, index + len(piece)))
        cursor = index + len(piece)
    return sentences


def ground_text(
    text: str,
    *,
    artifact: ArtifactKind,
    context: EvidenceContext,
    id_prefix: str,
    granularity: str = "prose",
) -> GroundingOutcome:
    """Ground one piece of generated text and return the cleaned text plus trace.

    ``granularity="prose"`` removes whole offending sentences (summary, cover
    letter, answers); ``granularity="span"`` redacts the exact offending token in
    place (candidate-authored resume bullets, where dropping the whole line would
    corrupt completeness accounting).
    """
    # Canonicalize compatibility characters (e.g. full-width ４７％) and strip
    # invisible formatting controls before computing offsets. Otherwise a model
    # can split a sensitive token with a zero-width character and evade every
    # word-boundary extractor while the rendered output still reads identically.
    text = unicodedata.normalize("NFKC", text)
    text = "".join(character for character in text if unicodedata.category(character) != "Cf")
    if not text.strip():
        return GroundingOutcome(clean_text=text, claims=[])

    raw_claims = _extract_claims(text, context)
    unsupported_spans = [(claim.start, claim.end) for claim in raw_claims if not claim.supported]

    if granularity == "span":
        clean_text = _repair_spans(text, unsupported_spans)
    else:
        clean_text = _repair_prose(text, unsupported_spans)

    records: list[ClaimRecord] = []
    repaired = 0
    rejected = 0
    clean_metric = _metric_normalize(clean_text)
    clean_word = _word_normalize(clean_text)
    for index, claim in enumerate(raw_claims, start=1):
        claim_id = f"{id_prefix}-{index}"
        if claim.supported:
            records.append(_record(claim_id, artifact, claim, ClaimStatus.SUPPORTED, "kept: supported by evidence"))
            continue
        still_present = _still_present(claim, clean_metric, clean_word)
        if still_present:
            rejected += 1
            records.append(
                _record(claim_id, artifact, claim, ClaimStatus.REJECTED, "rejected: could not be safely removed")
            )
        else:
            repaired += 1
            records.append(
                _record(claim_id, artifact, claim, ClaimStatus.REPAIRED, "repaired: removed unsupported claim")
            )

    return GroundingOutcome(
        clean_text=clean_text,
        claims=records,
        fatal=rejected > 0,
        repaired=repaired,
        rejected=rejected,
    )


def _still_present(claim: _RawClaim, clean_metric: str, clean_word: str) -> bool:
    if claim.claim_type in (ClaimType.METRIC, ClaimType.MONETARY, ClaimType.TEAM_SIZE, ClaimType.TENURE):
        return _metric_normalize(claim.text) in clean_metric
    return _term_present(_word_normalize(claim.text), clean_word)


def _record(
    claim_id: str,
    artifact: ArtifactKind,
    claim: _RawClaim,
    status: ClaimStatus,
    disposition: str,
) -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        artifact=artifact,
        claim_type=claim.claim_type,
        text=_bounded(claim.text, CLAIM_TEXT_MAX_CHARS),
        status=status,
        disposition=disposition,
        reason=claim.reason,
        evidence=claim.evidence,
    )
