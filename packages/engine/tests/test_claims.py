from __future__ import annotations

from ats_engine.models import Profile
from ats_engine.validation.claims import validate_claims
from conftest import WRAPPED_RESUME_TEXT, sample_profile


def test_tier_c_cannot_appear_in_experience_bullets(profile: Profile) -> None:
    text = "Professional Experience\n- Built FastAPI services.\nEducation"
    assert any("Tier C" in error for error in validate_claims(text, profile))


def test_tier_c_may_appear_in_working_knowledge_line(profile: Profile) -> None:
    text = "Technical Skills\nWorking knowledge: FastAPI, GraphQL\nProfessional Experience\n- Built Python pipelines.\nEducation"
    assert not any("Tier C" in error for error in validate_claims(text, profile))


def test_unsupported_metric_rejected(profile: Profile) -> None:
    errors = validate_claims("Reduced latency by 99% for 1 million users.", profile)
    assert any("unsupported" in error for error in errors)


def test_tier_b_skill_is_not_flagged_by_summary_production_word(profile: Profile) -> None:
    text = (
        "Professional Summary\n"
        "Software engineer with production software delivery experience.\n"
        "Technical Skills\n"
        "Data and BI: data visualization, Power BI\n"
        "Professional Experience\n"
        "- Built Python pipelines.\n"
        "Education"
    )
    assert not any("data visualization" in error for error in validate_claims(text, profile))


def test_official_titles_are_not_altered(profile: Profile) -> None:
    text = "\\resumeSubheading{Acme Corp}{Remote}{Product Manager}{2020 to 2023}"
    assert any("official title altered" in error for error in validate_claims(text, profile))


def test_selected_experience_heading_is_not_treated_as_employer(profile: Profile) -> None:
    output = (
        "\\section{Professional Experience}\n"
        "\\resumeSubHeadingListStart\n"
        "\\resumeSubheading{Selected Experience}{}{}{}\n"
        "\\resumeItemListStart\n"
        "\\resumeItem{Built Python pipelines.}\n"
        "\\resumeItemListEnd\n"
        "\\resumeSubHeadingListEnd\n"
        "\\section{Education}\n"
    )
    errors = validate_claims(output, profile)
    assert "invented or unsupported employer: selected experience" not in errors


def test_true_invented_employer_is_still_blocked(profile: Profile) -> None:
    output = (
        "\\section{Professional Experience}\n"
        "\\resumeSubHeadingListStart\n"
        "\\resumeSubheading{Fake Labs}{Remote}{Software Engineer}{2021 to 2024}\n"
        "\\resumeSubHeadingListEnd\n"
        "\\section{Education}\n"
    )
    assert any("invented or unsupported employer: fake labs" in error for error in validate_claims(output, profile))


def test_retired_email_is_flagged() -> None:
    profile = sample_profile()
    errors = validate_claims("Contact me at old@example.com", profile)
    assert any("retired email used" in error for error in errors)


def test_candidates_own_scale_claims_are_supported_evidence() -> None:
    profile = sample_profile()
    profile.raw_markdown = WRAPPED_RESUME_TEXT
    output = "Professional Experience\n- Maintained 100% uptime serving millions of users.\nEducation"
    errors = validate_claims(output, profile)
    assert not any("unsupported" in error for error in errors)


def test_metrics_not_in_resume_are_flagged() -> None:
    profile = sample_profile()
    profile.raw_markdown = WRAPPED_RESUME_TEXT
    errors = validate_claims("Increased revenue by 300% for 5 million customers.", profile)
    assert any("300%" in error for error in errors)
