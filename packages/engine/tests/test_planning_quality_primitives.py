"""Unit coverage for evidence-backed headline and summary planning primitives."""

from __future__ import annotations

from ats_engine.generation.planning import _headline, rewrite_summary
from ats_engine.models import Certification, ContactInfo, EvidenceLink, JDProfile, Profile, RequirementTerm
from ats_engine.validation.style import validate_style


def _requirement(
    canonical: str,
    *,
    kind: str,
    category: str,
    weight: float = 3.0,
) -> RequirementTerm:
    return RequirementTerm(
        canonical=canonical,
        surface=canonical.title(),
        aliases=(),
        kind=kind,
        section="required",
        weight=weight,
        ngram=len(canonical.split()),
        category=category,
        jd_evidence_line=f"- {canonical}",
    )


def _link(requirement: RequirementTerm, tier: str, span: str = "Built source-backed work.") -> EvidenceLink:
    return EvidenceLink(
        requirement=requirement,
        tier=tier,
        resume_span=span,
        resume_location="experience:0:bullet:0" if tier == "A" else "certification",
        match_type="exact" if tier == "A" else "cert_implies",
        surface_to_use=requirement.surface,
        max_placement="summary",
    )


def _profile() -> Profile:
    return Profile(
        contact=ContactInfo(),
        retired_emails=[],
        role_identities=["Data Analyst"],
        tier_a={},
        tier_b={},
        tier_c={"kubernetes": "Kubernetes"},
        adjacency={},
        experiences=[],
        education=[],
        certifications=[Certification(name="Microsoft Certified: Power BI Data Analyst Associate (PL-300)")],
        supported_metrics=["40%", "team of four engineers"],
        source_summary="Data Analyst who reduced manual reporting time by 40% for a team of four engineers.",
    )


def test_headline_uses_only_direct_or_certified_multiword_tool_methodology_phrases() -> None:
    power_bi = _requirement("power bi service", kind="tool", category="bi_analytics")
    governance = _requirement("data governance", kind="methodology", category="security_governance", weight=2.0)
    power_query = _requirement("power query", kind="tool", category="bi_analytics")
    communication = _requirement("stakeholder communication", kind="soft", category="communication")
    business_requirements = _requirement("business requirements", kind="skill", category="business_analysis")
    sql = _requirement("sql", kind="tool", category="database")
    tier_b = _requirement("data visualization", kind="tool", category="bi_analytics")
    links = [
        _link(communication, "A"),
        _link(business_requirements, "A"),
        _link(sql, "A"),
        _link(tier_b, "B"),
        _link(power_query, "cert", "Microsoft Certified (PL-300)"),
        _link(governance, "A"),
        _link(power_bi, "A"),
    ]

    headline = _headline(JDProfile(title="Target Role"), "Data Analyst", [], links)

    assert headline == "Data Analyst | Power Bi Service, Data Governance, Power Query"
    assert "Communication" not in headline
    assert "Business Requirements" not in headline
    assert "SQL" not in headline
    assert "Data Visualization" not in headline


def test_rewrite_summary_preserves_source_facts_and_excludes_tier_c_terms() -> None:
    profile = _profile()
    power_bi = _requirement("power bi service", kind="tool", category="bi_analytics")
    data_governance = _requirement("data governance", kind="methodology", category="security_governance")
    kubernetes = _requirement("kubernetes", kind="tool", category="platform")
    power_query = _requirement("power query", kind="tool", category="bi_analytics")
    links = [
        _link(power_bi, "A"),
        _link(data_governance, "A"),
        _link(kubernetes, "C", "Kubernetes"),
        _link(power_query, "cert", "Microsoft Certified: Power BI Data Analyst Associate (PL-300)"),
    ]
    jd_profile = JDProfile(title="BI Developer - Fixed Term")

    first = rewrite_summary("Data Analyst", profile, jd_profile, links, years_span=5)
    second = rewrite_summary("Data Analyst", profile, jd_profile, links, years_span=5)

    assert first == second
    assert "reduced manual reporting time by 40% for a team of four engineers" in first
    assert "Power Bi Service" in first
    assert "Data Governance" in first
    assert "Microsoft PL-300 certified" in first
    assert "Targeting BI Developer - Fixed Term opportunities." in first
    assert "Kubernetes" not in first
    assert "—" not in first and "–" not in first and "--" not in first
    assert "  " not in first
    assert validate_style(first) == []
