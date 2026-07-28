from __future__ import annotations

from types import SimpleNamespace

from ats_engine.models import Certification, ContactInfo, Education, Experience, Profile
from ats_engine.validation.fidelity import BulletPair, bullet_fidelity_errors, validate_resume_fidelity
from ats_engine.validation.stuffing import validate_resume_stuffing

SOURCE_BULLET = (
    "Architected Cloud SQL Auth Proxy for a team of four engineers; "
    "maintained 100% uptime for Mission-Critical Reporting."
)
RAW_RESUME = f"""Alex Example
Professional Experience
Flosonics Medical | Data Engineer | Toronto, ON (Remote) | 2020 - Present
- {SOURCE_BULLET}
Education
University of Toronto | Toronto, ON | BSc Computer Science | 2015 - 2019
Certifications
Microsoft Certified: Power BI Data Analyst Associate | Credential ID PL-300
"""


def _profile() -> Profile:
    return Profile(
        contact=ContactInfo(location="Toronto, ON (Remote)", work_mode="remote"),
        retired_emails=[],
        role_identities=["Data Engineer"],
        tier_a={},
        tier_b={},
        tier_c={},
        adjacency={},
        experiences=[
            Experience(
                company="Flosonics Medical",
                title="Data Engineer",
                location="Toronto, ON (Remote)",
                dates="2020 - Present",
                bullets=[SOURCE_BULLET],
            )
        ],
        education=[
            Education(
                institution="University of Toronto",
                location="Toronto, ON",
                degree="BSc Computer Science",
                dates="2015 - 2019",
            )
        ],
        certifications=[
            Certification(
                name="Microsoft Certified: Power BI Data Analyst Associate",
                credential_id="PL-300",
            )
        ],
        supported_metrics=["100%"],
        raw_markdown=RAW_RESUME,
    )


def test_resume_fidelity_preserves_profile_and_raw_source_facts() -> None:
    errors = validate_resume_fidelity(
        RAW_RESUME,
        RAW_RESUME,
        profile=_profile(),
        bullet_pairs=[BulletPair(original=SOURCE_BULLET, candidate=SOURCE_BULLET, location="experience[0].bullet[0]")],
    )

    assert errors == []


def test_resume_fidelity_flags_missing_remote_credential_and_metric() -> None:
    rendered = RAW_RESUME.replace("Toronto, ON (Remote)", "Toronto, ON").replace("PL-300", "").replace("100%", "")

    errors = validate_resume_fidelity(RAW_RESUME, rendered, profile=_profile())

    assert any("remote work mode" in error for error in errors)
    assert any("credential ID" in error for error in errors)
    assert any("metric" in error for error in errors)


def test_bullet_fidelity_preserves_terminal_team_and_named_entity_facts() -> None:
    candidate = "Architected Cloud SQL Auth Proxy for services."

    errors = bullet_fidelity_errors(SOURCE_BULLET, candidate, source_text=RAW_RESUME)

    assert any("team fact" in error for error in errors)
    assert any("named entity" in error for error in errors)
    assert any("terminal clause" in error for error in errors)


def test_bullet_fidelity_allows_source_scoped_term_but_rejects_new_entity() -> None:
    source = f"{RAW_RESUME}\nPower BI service dashboards"
    candidate = f"{SOURCE_BULLET} Used Power BI Service with Fabrikam Analytics."

    errors = bullet_fidelity_errors(SOURCE_BULLET, candidate, source_text=source)

    assert any("unsupported named entity" in error and "Fabrikam Analytics" in error for error in errors)
    assert not any("Power BI" in error for error in errors)


def test_raw_source_bullet_loss_is_detected_when_profile_omits_it() -> None:
    """Raw glyph bullets remain a fidelity source even after parser loss."""
    profile = _profile()
    profile.experiences[0].bullets = []
    rendered = RAW_RESUME.replace(f"- {SOURCE_BULLET}\n", "")

    errors = validate_resume_fidelity(
        RAW_RESUME,
        rendered,
        profile=profile,
        # A stale parsed-pair view cannot override the delivered-text diff.
        bullet_pairs=[BulletPair(original=SOURCE_BULLET, candidate=SOURCE_BULLET)],
    )

    assert any("raw source bullet" in error and "content not retained" in error for error in errors)
    assert any("raw source bullet" in error and "terminal clause facts" in error for error in errors)


def test_raw_source_bullet_keeps_uppercase_orphan_continuation() -> None:
    raw = (
        "Professional Experience\n"
        "- Developed integrations for Google\n"
        "Cloud SQL Auth Proxy, configuring secure database connectivity for reporting.\n"
    )
    preserved = (
        "Professional Experience\n"
        "- Developed integrations for Google Cloud SQL Auth Proxy, configuring secure database connectivity for reporting.\n"
    )
    lost_continuation = "Professional Experience\n- Developed integrations for Google\n"

    assert validate_resume_fidelity(raw, preserved) == []
    errors = validate_resume_fidelity(raw, lost_continuation)
    assert any("raw source bullet" in error and "content not retained" in error for error in errors)


def test_rendered_text_stuffing_api_uses_action_terms() -> None:
    action = SimpleNamespace(term="Power BI")

    errors = validate_resume_stuffing("Power BI Power BI Power BI Power BI Power BI", [action])

    assert any("requirement 'power bi' appears 5 times" in error for error in errors)


def test_structured_stuffing_checks_summary_bullet_and_skill_budgets() -> None:
    requirements = ["Power BI", "Power Query", "DAX", "Excel", "ArcGIS", "M-Files"]
    errors = validate_resume_stuffing(
        summary="Power BI Power Query DAX Excel ArcGIS M-Files",
        bullets=["Built Power BI reports with Power Query, DAX, and Excel."],
        skill_groups=[("Analytics", ["Power BI", "Power BI"])],
        source_skill_groups=[("Analytics", ["Power BI"])],
        requirements=requirements,
    )

    assert any("summary uses 6" in error for error in errors)
    assert any("bullet 1 uses 4" in error for error in errors)
    assert any("skills repeat requirement 'power bi'" in error for error in errors)
