from __future__ import annotations

from ats_engine.config import EngineSettings
from ats_engine.generation.pipeline import run_pipeline
from ats_engine.models import Mode
from ats_engine.parsing.jd_requirements import extract_requirements
from ats_engine.parsing.vocab import (
    aliases_for,
    certification_implications,
    normalize_term,
    vocabulary_entry,
)


def test_extract_requirements_is_phrase_first_and_rejects_generic_noise() -> None:
    jd = """
    Chiefs of Ontario
    IT Specialist – Economic Development

    Responsibilities:
    - Develop Power BI data models (DAX, Power Query, star schema design) and Power BI Service workspaces.
    - Build multi-source data pipelines from Excel datasets and ESRI ArcGIS visuals with geocoding.

    Required Qualifications:
    - Experience with Power BI, data modelling, data governance, M-Files, and document management.
    - Knowledge of audit logging, access controls, OCAP, and cybersecurity.

    Preferred Qualifications:
    - SharePoint experience and excellent communication.

    Salary range $80,000. We are an equal opportunity employer.
    PM-V&C, plan B, C-suite technical support systems information related environment COO FNBD economic portal.
    """

    requirements = extract_requirements(jd)
    canonical = {requirement.canonical for requirement in requirements}

    assert {
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
    } <= canonical
    assert not canonical & {
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

    by_canonical = {requirement.canonical: requirement for requirement in requirements}
    assert by_canonical["power bi"].weight == 3.0
    assert by_canonical["power query"].section == "responsibility"
    assert by_canonical["communication"].weight == 0.5


def test_phrase_overlap_and_soft_weight_cap_are_deterministic() -> None:
    jd = """
    Required Qualifications:
    - Power BI Service workspaces and row-level security.
    - Excellent communication, stakeholder communication, and collaboration.
    """

    requirements = extract_requirements(jd)
    canonical = [requirement.canonical for requirement in requirements]

    assert "power bi service" in canonical
    assert "power bi" not in canonical
    assert "business intelligence" not in canonical
    soft_weight = sum(requirement.weight for requirement in requirements if requirement.kind == "soft")
    total_weight = sum(requirement.weight for requirement in requirements)
    assert soft_weight / total_weight <= 0.15


def test_vocab_normalizes_variants_and_certification_implications_are_narrow() -> None:
    assert normalize_term("Data Modeling") == "data modelling"
    assert vocabulary_entry("data modeling") == vocabulary_entry("data modelling")
    assert "data modeling" in aliases_for("data modelling")
    assert set(certification_implications("Microsoft Certified (PL-300)")) == {
        "power bi desktop",
        "dax",
        "power query",
        "data modelling",
        "power bi service",
    }
    assert certification_implications("AZ-900") == ("azure",)
    assert "azure devops" not in certification_implications("AZ-900")


def test_tier_c_requirement_keeps_source_skill_heading_and_is_labeled_conservatively() -> None:
    result = run_pipeline(
        resume_text=(
            "Taylor Chen\n"
            "TECHNICAL SKILLS\n"
            "Kubernetes\n"
            "PROFESSIONAL EXPERIENCE\n"
            "Cedar Labs Toronto, ON\n"
            "Data Analyst 2022 - 2024\n"
            "- Built SQL reports.\n"
        ),
        job_description=("Job Title: Platform Analyst\nCompany: Beacon\nRequired qualifications:\n- Kubernetes\n"),
        default_mode=Mode.RESUME,
        settings=EngineSettings(tailoring_v2=True),
        use_llm=False,
    )

    assert result.resume_plan is not None
    assert result.resume_plan.skill_groups == [("Skills", ["Kubernetes (Working Knowledge)"])]
    assert result.resume_plan.summary == "Data Analyst. Targeting Platform Analyst opportunities."
    assert "Skills: Kubernetes (Working Knowledge)" in result.resume_text
