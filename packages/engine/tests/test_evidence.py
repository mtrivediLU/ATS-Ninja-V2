from __future__ import annotations

from ats_engine.evidence.adjacency import find_category
from ats_engine.evidence.matrix import classify_keyword, interview_probability
from ats_engine.models import EvidenceItem, Profile


def test_proven_skill_is_tier_a(profile: Profile) -> None:
    item = classify_keyword("Python", "required", profile)
    assert item.evidence_tier == "A"
    assert item.strength == "strong"


def test_summary_only_skill_is_tier_b(profile: Profile) -> None:
    item = classify_keyword("Power BI", "required", profile)
    assert item.evidence_tier == "B"
    assert item.strength == "medium"


def test_listed_only_skill_is_tier_c_working_knowledge(profile: Profile) -> None:
    item = classify_keyword("FastAPI", "required", profile)
    assert item.evidence_tier == "C"
    assert "Working knowledge" in item.planned_placement


def test_adjacency_phrasing_does_not_become_fake_production_experience(profile: Profile) -> None:
    item = classify_keyword("AWS", "required", profile)
    assert item.evidence_tier == "adjacency"
    assert "Azure" in item.real_evidence
    assert "production" not in item.allowed_placement.lower()


def test_genuine_gap_is_marked_missing_and_not_claimed(profile: Profile) -> None:
    item = classify_keyword("COBOL", "required", profile)
    assert item.evidence_tier == "missing"
    assert item.allowed_placement == "do not claim"
    assert item.real_evidence == ""


def test_find_category_clusters_related_tools() -> None:
    match = find_category("snowflake")
    assert match is not None
    _key, _label, tools = match
    assert "postgresql" in tools


def _item(tier: str, kind: str = "required") -> EvidenceItem:
    return EvidenceItem(
        keyword="x",
        required_or_preferred=kind,
        evidence_tier=tier,
        real_evidence="",
        allowed_placement="",
        strength="",
        planned_placement="",
    )


def test_interview_probability_is_conservative_with_two_missing_required() -> None:
    matrix = [_item("missing"), _item("missing"), _item("A")]
    assert interview_probability(matrix) == 52


def test_interview_probability_is_high_with_full_coverage() -> None:
    matrix = [_item("A"), _item("A"), _item("B")]
    assert interview_probability(matrix) == 91
