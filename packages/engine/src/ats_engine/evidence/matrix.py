from __future__ import annotations

import re

from ats_engine.evidence.adjacency import find_category
from ats_engine.models import EvidenceItem, JDProfile, Profile

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
    """Build the keyword evidence matrix for required and preferred JD keywords."""
    required_keywords = _keywords_from_lines(jd_profile.required_qualifications, jd_profile.technical_keywords)
    preferred_keywords = _keywords_from_lines(jd_profile.preferred_qualifications, jd_profile.technical_keywords)
    if not required_keywords:
        required_keywords = jd_profile.technical_keywords[:8]

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

    if tier == "A":
        return EvidenceItem(
            keyword=keyword,
            required_or_preferred=required_or_preferred,
            evidence_tier="A",
            real_evidence=evidence,
            allowed_placement="summary, skills, supported bullets",
            strength="strong",
            planned_placement="summary, skills, experience bullet",
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
        )

    return EvidenceItem(
        keyword=keyword,
        required_or_preferred=required_or_preferred,
        evidence_tier="missing",
        real_evidence="",
        allowed_placement="do not claim",
        strength="missing",
        planned_placement="analysis snapshot only",
    )


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


def _keywords_from_lines(lines: list[str], fallback_keywords: list[str]) -> list[str]:
    found: list[str] = []
    for keyword in fallback_keywords:
        if any(keyword.lower() in line.lower() for line in lines):
            found.append(keyword)
    if found:
        return found
    return fallback_keywords[:8]


def _tier_lookup(normalized_keyword: str, profile: Profile) -> tuple[str, str]:
    for tier, source in [("A", profile.tier_a), ("B", profile.tier_b)]:
        for term, display in source.items():
            if _term_matches(term, normalized_keyword):
                return tier, display
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
