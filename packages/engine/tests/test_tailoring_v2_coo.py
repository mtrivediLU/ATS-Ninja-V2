"""Authoritative deterministic regression coverage for the COO IT Specialist case.

The fixture deliberately includes hostile-but-realistic resume layout features
(orphan wrapped text, a hyphenated wrap, single-letter languages, certification
identifiers, and source wording that must not be softened).  It is synthetic:
the candidate identity, contact data, dates, and bullet wording are test data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ats_engine.config import EngineSettings
from ats_engine.evidence.resolver import resolve_requirements
from ats_engine.generation.integration_planner import plan_placements
from ats_engine.kit.change_actions import ChangeAction, apply_change_actions
from ats_engine.kit.contract import ChangeType
from ats_engine.kit.orchestrator import generate_application_kit
from ats_engine.kit.serialization import application_kit_to_dict
from ats_engine.models import ContactInfo, EvidenceLink, JDProfile, Profile, RequirementTerm
from ats_engine.parsing.jd_requirements import extract_requirements
from ats_engine.parsing.resume import extract_profile
from ats_engine.scoring.ats_v2 import score_resume_v2
from ats_engine.validation.fidelity import BulletPair, validate_resume_fidelity

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "coo_it_specialist"
EMPLOYERS = (
    "Northstar Medical Systems",
    "Harborline Analytics",
    "City of Northbridge",
    "Cedar Peak Software",
    "Meridian Research Centre",
    "Global Systems Consulting",
)
TITLES = (
    "Senior Software Engineer",
    "Software Engineer",
    "Application Developer",
    "Software Engineer",
    "Data Analyst",
    "Systems Analyst",
)
DATES = ("2021 - Present", "2019 - 2021", "2017 - 2019", "2015 - 2017", "2013 - 2015", "2011 - 2013")
REQUIRED_TERMS = {
    "power query",
    "star schema",
    "power bi service",
    "excel",
    "geocoding",
    "esri arcgis",
    "m-files",
    "data governance",
    "dax",
    "power bi",
    "data modelling",
    "multi-source data pipelines",
}
GENERIC_NOISE = {
    "technical",
    "support",
    "systems",
    "information",
    "related",
    "environment",
    "c",
    "coo",
    "fnbd",
    "economic",
    "portal",
}


def _read_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def resume_text() -> str:
    return _read_fixture("resume.txt")


@pytest.fixture(scope="module")
def job_description() -> str:
    return _read_fixture("job_description.txt")


@pytest.fixture(scope="module")
def profile(resume_text: str):  # type: ignore[no-untyped-def]
    # Avoid a cached profile obscuring parser regressions in this fixture test.
    return extract_profile(resume_text)


@pytest.fixture(scope="module")
def requirements(job_description: str) -> list[RequirementTerm]:
    return extract_requirements(job_description)


@pytest.fixture(scope="module")
def links(requirements: list[RequirementTerm], profile, resume_text: str):  # type: ignore[no-untyped-def]
    return resolve_requirements(requirements, profile, resume_text)


@pytest.fixture(scope="module")
def coo_kit(resume_text: str, job_description: str):  # type: ignore[no-untyped-def]
    return generate_application_kit(
        resume_text=resume_text,
        job_description=job_description,
        include_resume=True,
        include_cover_letter=False,
        include_application_answers=False,
        include_job_fit=False,
        include_interview_prep=False,
        include_linkedin_outreach=False,
        settings=EngineSettings(tailoring_v2=True),
        use_llm=False,
    )


def test_fixture_parses_all_source_structure_without_orphan_employers(profile) -> None:  # type: ignore[no-untyped-def]
    assert tuple(experience.company for experience in profile.experiences) == EMPLOYERS
    assert tuple(experience.title for experience in profile.experiences) == TITLES
    assert tuple(experience.dates for experience in profile.experiences) == DATES
    assert profile.experiences[0].location == "Harbor City, ON (Remote)"
    assert not profile.extraction_warnings

    minax = next(experience for experience in profile.experiences if experience.company == "Cedar Peak Software")
    assert any(
        "Cloud SQL Auth Proxy, configuring secure communication between services." in bullet for bullet in minax.bullets
    )
    sudbury = next(experience for experience in profile.experiences if experience.company == "City of Northbridge")
    assert any("Zoom-Info and Lead Forensics" in bullet for bullet in sudbury.bullets)

    source_skills = [item for _heading, items in profile.source_skill_groups for item in items]
    assert "CSS3" in source_skills
    assert "CSS3." not in source_skills
    assert not any("pragmatic use" in item.casefold() for item in source_skills)


def test_rejecting_a_coo_summary_rewrite_restores_source_and_keeps_v2_floor(
    coo_kit, resume_text: str, job_description: str
) -> None:  # type: ignore[no-untyped-def]
    assert coo_kit.resume is not None and coo_kit.match_report is not None
    summary = next(
        record
        for record in coo_kit.resume.change_ledger
        if record.change_type is ChangeType.SUMMARY and record.operation.value == "rewritten"
    )
    result = apply_change_actions(
        kit=coo_kit,
        resume_text=resume_text,
        job_description=job_description,
        actions=[ChangeAction(summary.id, "reject")],
        expected_revision=coo_kit.revision,
    )

    assert result.ok, result.errors
    assert result.kit.resume is not None and result.kit.match_report is not None
    assert summary.original_text in result.kit.resume.document.summary
    assert result.kit.resume.validation.fatal is False
    assert result.kit.match_report.score_basis == "pramana"
    assert result.kit.match_report.tailored_ats_match is not None
    assert result.kit.match_report.tailored_ats_match.score >= result.kit.match_report.original_ats_match.score


def test_fixture_extracts_only_real_phrase_requirements(
    requirements: list[RequirementTerm],
) -> None:
    canonical = {requirement.canonical for requirement in requirements}
    assert REQUIRED_TERMS <= canonical
    assert not GENERIC_NOISE & canonical


def test_fixture_resolver_uses_normalized_and_certificate_provenance(
    links: list[EvidenceLink],
) -> None:
    by_term = {link.requirement.canonical: link for link in links}

    assert by_term["data modelling"].tier == "C"
    assert by_term["data modelling"].match_type == "variant_spelling"
    assert by_term["dax"].tier == "cert"
    assert by_term["power query"].tier == "cert"
    assert "PL-300" in by_term["dax"].resume_span
    assert "PL-300" in by_term["power query"].resume_span
    assert by_term["power bi"].tier == "A"
    assert by_term["esri arcgis"].tier == "A"
    assert by_term["m-files"].tier == "missing"
    assert by_term["ocap"].tier == "missing"


def test_fixture_end_to_end_optimizes_without_losing_source_facts(
    coo_kit,
    profile,
    resume_text: str,  # type: ignore[no-untyped-def]
) -> None:
    assert coo_kit.validation.passed
    assert coo_kit.resume is not None
    assert not coo_kit.resume.validation.fatal
    assert coo_kit.match_report is not None
    assert coo_kit.match_report.score_basis == "pramana"
    assert coo_kit.match_report.tailored_ats_match is not None

    report = coo_kit.match_report
    # PRAMANA's placement bonus caps at 4.0 (was 5.0 under ats_v2's boolean
    # formula) per the work order's literal "placement 0..4" spec, which alone
    # narrows this fixture's margin from >=15.0 to an observed, verified
    # +14.84 (32.28 -> 47.12) -- still a large, credible improvement (8/21 to
    # 11/21 required matches plus preferred), not a regression.
    assert report.tailored_ats_match.score >= report.original_ats_match.score + 14.0
    assert report.keywords_surfaced_by_tailoring
    assert {"m-files", "ocap"} <= set(report.optimization_trace.unreachable_terms)

    candidate_text = coo_kit.resume.text
    assert candidate_text
    for fact in (*EMPLOYERS, *TITLES, *DATES, "Harbor City, ON (Remote)", "team of four engineers", "100% uptime"):
        assert fact in candidate_text
    for credential_id in ("MS-30001", "MS-40002", "AZ-90003", "SF-10004"):
        assert credential_id in candidate_text
    for source_wording in (
        "Architected Power BI dashboards with ESRI ArcGIS visuals for clinical operations reporting.",
        "Streamlined quality checks for Mission-Critical Reporting, maintaining 100% uptime for a team of four engineers.",
    ):
        assert source_wording in candidate_text
    assert "M-Files" not in candidate_text
    assert "OCAP" not in candidate_text

    original_bullets = [
        BulletPair(original=bullet, candidate=bullet, location=f"experience:{exp_index}:bullet:{bullet_index}")
        for exp_index, experience in enumerate(profile.experiences)
        for bullet_index, bullet in enumerate(experience.bullets)
    ]
    assert validate_resume_fidelity(resume_text, candidate_text, profile=profile, bullet_pairs=original_bullets) == []


def test_fixture_job_priorities_never_surface_generic_unigrams(coo_kit) -> None:  # type: ignore[no-untyped-def]
    assert coo_kit.match_report is not None
    themes = [priority.theme.casefold().strip() for priority in coo_kit.match_report.job_priorities]
    assert themes
    assert not GENERIC_NOISE & set(themes)
    assert "c" not in themes


def test_fixture_deterministic_output_is_byte_stable(resume_text: str, job_description: str) -> None:
    common = {
        "resume_text": resume_text,
        "job_description": job_description,
        "include_resume": True,
        "include_cover_letter": False,
        "include_application_answers": False,
        "include_job_fit": False,
        "include_interview_prep": False,
        "include_linkedin_outreach": False,
        "settings": EngineSettings(tailoring_v2=True),
        "use_llm": False,
    }
    first = generate_application_kit(**common)
    second = generate_application_kit(**common)
    assert json.dumps(application_kit_to_dict(first), sort_keys=True) == json.dumps(
        application_kit_to_dict(second), sort_keys=True
    )


def test_adversarial_jd_append_and_stuffing_cannot_raise_the_score(
    resume_text: str,
    job_description: str,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
) -> None:
    baseline = score_resume_v2(resume_text, requirements, links, source_resume_text=resume_text, tailored=True)
    appended = score_resume_v2(
        f"{resume_text}\n\n{job_description}",
        requirements,
        links,
        source_resume_text=resume_text,
        tailored=True,
    )
    assert appended.score == baseline.score
    assert appended.matched_keywords == baseline.matched_keywords

    stuffed = score_resume_v2(
        f"{resume_text}\n" + ("Power BI " * 40),
        requirements,
        links,
        source_resume_text=resume_text,
    )
    unstuffed = score_resume_v2(resume_text, requirements, links, source_resume_text=resume_text)
    assert stuffed.matched_keywords == unstuffed.matched_keywords
    assert stuffed.score < unstuffed.score


def test_adversarial_missing_or_adjacent_terms_never_become_candidate_claims() -> None:
    # Keep the fixture's real ArcGIS experience out of this isolated QGIS
    # transfer case; the point is that a related source tool is not strict
    # ArcGIS evidence and therefore cannot authorize a candidate claim.
    qgis_only = Profile(
        contact=ContactInfo(),
        retired_emails=[],
        role_identities=[],
        tier_a={},
        tier_b={},
        tier_c={"qgis": "QGIS"},
        adjacency={},
        experiences=[],
        education=[],
        certifications=[],
        supported_metrics=[],
        raw_markdown="Technical Skills\nGeospatial: QGIS",
        source_skill_groups=[("Geospatial", ["QGIS"])],
    )
    requirements = extract_requirements("Required Qualifications:\n- Terraform and ESRI ArcGIS experience.")
    links = resolve_requirements(requirements, qgis_only, qgis_only.raw_markdown)
    by_term = {link.requirement.canonical: link for link in links}

    assert by_term["terraform"].tier == "missing"
    assert by_term["esri arcgis"].tier == "adjacency"
    actions = plan_placements(links, profile, JDProfile())
    assert all(action.term.casefold() not in {"terraform", "esri arcgis"} for action in actions)


def test_adversarial_certification_and_single_letter_boundaries(profile, resume_text: str) -> None:  # type: ignore[no-untyped-def]
    azure_devops = extract_requirements("Required Qualifications:\n- Azure DevOps experience.")
    azure_link = resolve_requirements(azure_devops, profile, resume_text)[0]
    assert azure_link.requirement.canonical == "azure devops"
    assert azure_link.tier == "missing"

    traps = extract_requirements(
        "Required Qualifications:\n- PM-V&C planning, plan B review, C-suite stakeholder work, and R&D awareness."
    )
    canonical = {term.canonical for term in traps}
    assert not canonical & {"b", "c", "r", "r d", "pm", "coo"}

    british = extract_requirements("Required Qualifications:\n- data modelling.")
    american = extract_requirements("Required Qualifications:\n- data modeling.")
    british_link = resolve_requirements(british, profile, resume_text)[0]
    american_link = resolve_requirements(american, profile, resume_text)[0]
    assert (british_link.tier, british_link.match_type) == ("C", "variant_spelling")
    assert (american_link.tier, american_link.match_type) == ("C", "variant_spelling")


@pytest.mark.parametrize(
    ("source_fragment", "wrapped_fragment"),
    (
        (
            "Architected Power BI dashboards with ESRI ArcGIS visuals for clinical operations reporting.",
            "Architected Power BI dashboards with ESRI ArcGIS visuals for clinical\noperations reporting.",
        ),
        (
            "Streamlined quality checks for Mission-Critical Reporting, maintaining 100% uptime for a team of four engineers.",
            "Streamlined quality checks for Mission-Critical Reporting, maintaining 100% uptime\nfor a team of four engineers.",
        ),
        (
            "Developed data ingestion services in Python and Google\nCloud SQL Auth Proxy, configuring secure communication between services.",
            "Developed data ingestion services in Python and Google Cloud SQL\nAuth Proxy, configuring secure communication between services.",
        ),
    ),
)
def test_wrapped_line_fuzz_preserves_the_employer_set(
    resume_text: str, source_fragment: str, wrapped_fragment: str
) -> None:
    assert source_fragment in resume_text
    rewrapped = resume_text.replace(source_fragment, wrapped_fragment)
    parsed = extract_profile(rewrapped)
    assert {experience.company for experience in parsed.experiences} == set(EMPLOYERS)
