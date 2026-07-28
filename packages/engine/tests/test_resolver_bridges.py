"""Conservative source-span regressions for Tailoring Engine resolver bridges."""

from __future__ import annotations

import pytest

from ats_engine.evidence.resolver import resolve_requirements
from ats_engine.models import Certification, ContactInfo, Experience, Profile, RequirementTerm


def _requirement(canonical: str, *, kind: str = "tool", category: str = "data_engineering") -> RequirementTerm:
    return RequirementTerm(
        canonical=canonical,
        surface=canonical.title(),
        aliases=(),
        kind=kind,
        section="required",
        weight=3.0,
        ngram=len(canonical.split()),
        category=category,
        jd_evidence_line=f"- {canonical}",
    )


def _profile(*, bullets: list[str] | None = None, skills: list[str] | None = None) -> Profile:
    source_bullets = bullets or []
    source_skills = skills or []
    return Profile(
        contact=ContactInfo(),
        retired_emails=[],
        role_identities=["Data Engineer"],
        tier_a={},
        tier_b={},
        tier_c={item.casefold(): item for item in source_skills},
        adjacency={},
        experiences=[
            Experience(
                company="Example Data Co.",
                title="Data Engineer",
                location="Remote",
                dates="2022 - 2025",
                bullets=source_bullets,
            )
        ],
        education=[],
        certifications=[
            Certification(
                name="Microsoft Certified: Power BI Data Analyst Associate (PL-300)",
                credential_id="CERT-PL300",
            ),
            Certification(name="Microsoft Certified: Azure Fundamentals (AZ-900)"),
        ],
        supported_metrics=[],
        raw_markdown="source resume boundary",
        source_skill_groups=[("Tools", source_skills)],
    )


def test_curated_bridges_return_typed_links_with_real_source_spans() -> None:
    pipeline_bullet = "Built ETL/ELT pipelines ingesting Salesforce and HubSpot data for reporting."
    dashboard_bullet = "Developed Tableau dashboards for finance users."
    profile = _profile(bullets=[pipeline_bullet, dashboard_bullet], skills=["Git"])
    requirements = [
        _requirement("version control", kind="skill", category="source_control"),
        _requirement("data ingestion", kind="skill"),
        _requirement("multi-source data pipelines", kind="skill"),
        _requirement("dashboards", kind="skill", category="bi_analytics"),
        _requirement("workspaces", category="bi_analytics"),
        _requirement("refresh cycles", kind="methodology", category="bi_analytics"),
        _requirement("azure devops", category="platform"),
    ]

    links = {
        link.requirement.canonical: link for link in resolve_requirements(requirements, profile, profile.raw_markdown)
    }

    version_control = links["version control"]
    assert (version_control.tier, version_control.match_type, version_control.resume_span) == ("C", "bridged", "Git")
    assert version_control.resume_location == "skills:0:0"

    for canonical in ("data ingestion", "multi-source data pipelines"):
        link = links[canonical]
        assert (link.tier, link.match_type, link.resume_span, link.resume_location) == (
            "A",
            "bridged",
            pipeline_bullet,
            "experience:0:bullet:0",
        )

    dashboards = links["dashboards"]
    assert (dashboards.tier, dashboards.match_type, dashboards.resume_span, dashboards.resume_location) == (
        "A",
        "bridged",
        dashboard_bullet,
        "experience:0:bullet:1",
    )

    for canonical in ("workspaces", "refresh cycles"):
        link = links[canonical]
        assert (link.tier, link.match_type, link.resume_location) == ("cert", "bridged", "certification")
        assert link.resume_span == profile.certifications[0].name

    # Azure Fundamentals is source evidence only for Azure itself, never Azure
    # DevOps or deployment experience.
    assert links["azure devops"].tier == "missing"
    assert not links["azure devops"].resume_span


@pytest.mark.parametrize("tool", ("Git", "GitHub", "GitLab", "Bitbucket"))
def test_version_control_bridge_accepts_only_the_curated_source_tools(tool: str) -> None:
    profile = _profile(skills=[tool])
    requirement = _requirement("version control", kind="skill", category="source_control")

    link = resolve_requirements([requirement], profile, profile.raw_markdown)[0]

    assert (link.tier, link.match_type, link.resume_span) == ("C", "bridged", tool)


def test_multi_source_bridge_can_combine_structured_etl_and_source_system_evidence() -> None:
    etl_bullet = "Maintained ETL/ELT jobs for scheduled reporting."
    source_bullet = "Built ingestion pipelines from Salesforce and HubSpot for finance reporting."
    profile = _profile(bullets=[etl_bullet, source_bullet])
    requirement = _requirement("multi-source data pipelines", kind="skill")

    link = resolve_requirements([requirement], profile, profile.raw_markdown)[0]

    assert (link.tier, link.match_type, link.resume_span, link.resume_location) == (
        "A",
        "bridged",
        source_bullet,
        "experience:0:bullet:1",
    )
    assert link.supporting_spans == (etl_bullet, source_bullet)
    assert link.supporting_locations == ("experience:0:bullet:0", "experience:0:bullet:1")


def test_bridges_reject_aspirational_or_insufficient_source_evidence() -> None:
    profile = _profile(
        bullets=[
            "Planning to ingest Salesforce and HubSpot data next quarter.",
            "Maintained ETL jobs for Salesforce reporting.",
            "Reviewed Tableau dashboard requirements with finance users.",
            "No Git experience is listed.",
        ],
        skills=[],
    )
    requirements = [
        _requirement("version control", kind="skill", category="source_control"),
        _requirement("data ingestion", kind="skill"),
        _requirement("multi-source data pipelines", kind="skill"),
        _requirement("dashboards", kind="skill", category="bi_analytics"),
    ]

    links = {
        link.requirement.canonical: link for link in resolve_requirements(requirements, profile, profile.raw_markdown)
    }

    for canonical in ("version control", "data ingestion", "multi-source data pipelines"):
        assert links[canonical].tier == "missing"
        assert links[canonical].match_type == "missing"
        assert not links[canonical].resume_span

    # A non-building Tableau mention may still be shown as an adjacent BI tool
    # by the legacy gap ladder, but it is never promoted to a bridged dashboard
    # claim or an experience-tier match.
    assert links["dashboards"].tier != "A"
    assert links["dashboards"].match_type != "bridged"
