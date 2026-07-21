from __future__ import annotations

import re

from ats_engine.evidence.adjacency import find_category
from ats_engine.models import EvidenceItem, JDProfile, Profile
from ats_engine.parsing.resume import term_in_text_affirmative

"""The evidence matrix and gap ladder.

For every required/preferred JD keyword, :func:`classify_keyword` places the
candidate on a truth-grounded gap ladder:

- ``A``  proven in experience bullets (strong)
- ``B``  stated in the summary (medium)
- ``adjacency``  honest same-category substitute using a real tool they used
- ``C``  working knowledge, listed only (weak)
- ``missing``  genuine gap; the keyword is never claimed

This is the strategic capability that makes generation resistant to fabricated
claims: placement rules ride along with each item so downstream prose can never
over-claim a keyword beyond its evidence.
"""


def build_evidence_matrix(jd_profile: JDProfile, profile: Profile) -> list[EvidenceItem]:
    """Build the keyword evidence matrix for required and preferred JD keywords.

    A keyword named only in the day-to-day responsibilities (e.g. "perform
    root-cause analysis on issues"), never restated in the explicit
    requirements bullets, is still something the role genuinely needs. To
    surface it without letting a noisy, heading-less responsibilities guess
    ever outrank an explicit designation: a keyword literally in the
    required-qualifications text is always required; a keyword literally in
    the preferred-qualifications text is always preferred (an explicit
    "preferred" call-out is never promoted); only a keyword found solely via
    responsibilities — not already required or preferred — is added as an
    extra required-tier entry. This is what lets Resume tailoring actually use
    responsibilities as a primary input (see docs/architecture.md's
    JD-segmentation note) without responsibilities noise ever overriding an
    explicit required/preferred split.
    """
    # Plain substring matching against each line pool, no implicit fallback:
    # a JD with no "Preferred"/"Nice-to-have" section at all (the common
    # case) must yield a genuinely empty preferred list, not a synthetic
    # top-8 guess that then wrongly "claims" keywords (like a
    # responsibilities-only term) away from the required bucket below.
    required_from_bullets = _keywords_in_text(jd_profile.required_qualifications, jd_profile.technical_keywords)
    preferred_keywords = _keywords_in_text(jd_profile.preferred_qualifications, jd_profile.technical_keywords)
    preferred_set = {keyword.lower() for keyword in preferred_keywords}
    already_known = preferred_set | {keyword.lower() for keyword in required_from_bullets}

    responsibility_only = [
        keyword
        for keyword in _keywords_in_text(jd_profile.responsibilities, jd_profile.technical_keywords)
        if keyword.lower() not in already_known
    ]
    required_keywords = required_from_bullets + responsibility_only
    if not required_keywords:
        # Only here — nothing matched anywhere — does an empty result fall
        # back to the top technical keywords, so a Resume tailored against
        # this JD still has some signal to work with.
        required_keywords = [
            keyword for keyword in jd_profile.technical_keywords[:8] if keyword.lower() not in preferred_set
        ]

    matrix: list[EvidenceItem] = []
    for keyword in required_keywords:
        matrix.append(classify_keyword(keyword, "required", profile))
    for keyword in preferred_keywords:
        if keyword.lower() not in {item.keyword.lower() for item in matrix}:
            matrix.append(classify_keyword(keyword, "preferred", profile))
    return matrix


def classify_keyword(keyword: str, required_or_preferred: str, profile: Profile) -> EvidenceItem:
    """Apply the gap ladder to one keyword."""
    normalized = keyword.lower().strip()
    tier, evidence = _tier_lookup(normalized, profile)
    category = classify_requirement_category(normalized)

    if tier == "A":
        return EvidenceItem(
            keyword=keyword,
            required_or_preferred=required_or_preferred,
            evidence_tier="A",
            real_evidence=evidence,
            allowed_placement="summary, skills, supported bullets",
            strength="strong",
            planned_placement="summary, skills, experience bullet",
            category=category,
        )
    if tier == "B":
        return EvidenceItem(
            keyword=keyword,
            required_or_preferred=required_or_preferred,
            evidence_tier="B",
            real_evidence=evidence,
            allowed_placement="summary and skills, hedged bullets only with actual use",
            strength="medium",
            planned_placement="summary and skills",
            category=category,
        )

    adjacency = _adjacency_lookup(normalized, profile)
    if adjacency:
        return EvidenceItem(
            keyword=keyword,
            required_or_preferred=required_or_preferred,
            evidence_tier="adjacency",
            real_evidence=adjacency,
            allowed_placement="adjacency phrasing naming the real tool",
            strength="medium" if required_or_preferred == "preferred" else "weak",
            planned_placement="summary or skills with adjacent evidence",
            category=category,
        )

    if normalized in profile.tier_c:
        return EvidenceItem(
            keyword=keyword,
            required_or_preferred=required_or_preferred,
            evidence_tier="C",
            real_evidence=profile.tier_c[normalized],
            allowed_placement="Working knowledge skills line or cover-letter fast-ramp paragraph",
            strength="weak",
            planned_placement="Working knowledge",
            category=category,
        )

    return EvidenceItem(
        keyword=keyword,
        required_or_preferred=required_or_preferred,
        evidence_tier="missing",
        real_evidence="",
        allowed_placement="do not claim",
        strength="missing",
        planned_placement="analysis snapshot only",
        category=category,
    )


# Coarse categories for the typed requirement map (Phase 3). This is a
# separate, simpler classification from ``adjacency.TOOL_CATEGORIES`` (which
# groups tools for honest substitute-tool phrasing) — this one only labels a
# keyword for skills-section grouping and requirement-map display, so it is
# intentionally keyword-pattern based rather than an exhaustive enum.
_CATEGORY_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    (
        "platform",
        (
            "power apps",
            "power automate",
            "power pages",
            "power platform",
            "dataverse",
            "model driven apps",
            "model-driven apps",
            "pcf",
            "sharepoint",
            "salesforce",
            "hubspot",
            "servicenow",
            "workday",
        ),
    ),
    ("programming language", ("python", "java", "c#", "javascript", "typescript", "c++", "php", "sql", "go", "rust")),
    (
        "framework",
        (
            "react",
            "angular",
            "vue",
            "next.js",
            "spring",
            "hibernate",
            ".net",
            ".net framework",
            "django",
            "flask",
            "fastapi",
            "node.js",
        ),
    ),
    (
        "integration",
        (
            "rest",
            "restful",
            "api",
            "plug-in",
            "plugin",
            "microservices",
            "integration",
            "azure api management",
            "graphql",
        ),
    ),
    (
        "cloud",
        (
            "azure",
            "aws",
            "gcp",
            "google cloud",
            "azure functions",
            "azure function apps",
            "kubernetes",
            "docker",
            "linux",
        ),
    ),
    (
        "database",
        ("postgresql", "mysql", "mongodb", "sql server", "ms sql server", "dynamics 365", "oracle", "snowflake"),
    ),
    ("web development", ("html5", "css", "html", "web portal", "frontend", "front-end")),
    ("source control", ("source control", "git", "branching and merging", "version control")),
    (
        "business analysis",
        ("business requirements", "user experience", "ux", "requirements gathering", "stakeholder", "business analyst"),
    ),
    (
        "operations and support",
        (
            "root-cause analysis",
            "root cause analysis",
            "application support",
            "production support",
            "audit",
            "second and third-line support",
            "overtime",
        ),
    ),
    ("documentation", ("technical documentation", "documentation", "knowledge base")),
    ("communication", ("communicate", "communication", "collaborat")),
    (
        "work conditions",
        ("hybrid", "remote", "on-site", "onsite", "relocation", "security clearance", "overtime", "shift"),
    ),
]


def classify_requirement_category(normalized_keyword: str) -> str:
    """Coarsely categorize a normalized JD keyword for the typed requirement map."""
    for category, patterns in _CATEGORY_PATTERNS:
        # Word-boundary, not bare substring: "sql" as a substring would
        # otherwise misclassify "postgresql"/"mysql"/"nosql" as the
        # "programming language" category instead of "database".
        if any(
            re.search(rf"(?<![\w+#.-]){re.escape(pattern)}(?![\w+#.-])", normalized_keyword) for pattern in patterns
        ):
            return category
    return "other"


def interview_probability(matrix: list[EvidenceItem]) -> int:
    """Calibrate interview-call probability using required coverage."""
    required = [item for item in matrix if item.required_or_preferred == "required"]
    preferred = [item for item in matrix if item.required_or_preferred == "preferred"]
    if not required:
        required = matrix

    missing_required = [item for item in required if item.evidence_tier == "missing"]
    tier_c_required = [item for item in required if item.evidence_tier == "C"]
    adjacency_required = [item for item in required if item.evidence_tier == "adjacency"]
    missing_preferred = [item for item in preferred if item.evidence_tier == "missing"]

    if len(missing_required) >= 2:
        return 52
    if len(missing_required) == 1 or tier_c_required:
        return 68
    if adjacency_required or missing_preferred:
        return 82
    return 91


def _keywords_in_text(lines: list[str], candidates: list[str]) -> list[str]:
    """Candidates that literally appear in the combined line text. No fallback: an
    empty ``lines`` (e.g. a JD with no preferred-qualifications section) correctly
    yields an empty result rather than guessing."""
    text = " ".join(lines).lower()
    return [keyword for keyword in candidates if keyword.lower() in text]


def _tier_lookup(normalized_keyword: str, profile: Profile) -> tuple[str, str]:
    for tier, source in [("A", profile.tier_a), ("B", profile.tier_b)]:
        for term, display in source.items():
            if _term_matches(term, normalized_keyword):
                return tier, display
    # The deterministic resume parser intentionally keeps the skills section
    # lightweight, so backstop Tier A directly from parsed experience bullets.
    # This is evidence, not inference: the exact JD term must be present in a
    # candidate-authored bullet, in an AFFIRMATIVE clause — "I have no Kubernetes
    # experience" or "currently exploring Rust" must never count as proof.
    for experience in profile.experiences:
        if any(term_in_text_affirmative(normalized_keyword, bullet) for bullet in experience.bullets):
            return "A", normalized_keyword
    return "", ""


def _adjacency_lookup(normalized_keyword: str, profile: Profile) -> str:
    """Find an honest adjacency phrasing: same tool category, real tool the
    candidate's own resume actually shows evidence for (Tier A or B)."""
    match = find_category(normalized_keyword)
    if not match:
        return ""
    _category, label, tools = match
    candidate_evidence = {**profile.tier_a, **profile.tier_b}
    for tool in tools:
        if tool == normalized_keyword:
            continue
        if tool in candidate_evidence:
            return f"{label} ({candidate_evidence[tool]})"
        if any(
            term_in_text_affirmative(tool, bullet)
            for experience in profile.experiences
            for bullet in experience.bullets
        ):
            return f"{label} ({tool})"
    return ""


def _term_matches(term: str, keyword: str) -> bool:
    term = term.lower()
    keyword = keyword.lower()
    if term == keyword:
        return True
    return bool(
        re.search(rf"(?<![\w+#.-]){re.escape(term)}(?![\w+#.-])", keyword)
        or re.search(rf"(?<![\w+#.-]){re.escape(keyword)}(?![\w+#.-])", term)
    )
