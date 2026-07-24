from __future__ import annotations

from ats_engine.evidence.transfer import transfer_capability
from ats_engine.kit.orchestrator import generate_application_kit
from ats_engine.models import ContactInfo, Experience, Profile

"""Bounded evidence-to-capability transfer + a realistic 50/50 dev/test fixture.

A full-stack engineer with genuine testing/quality signals applying to a role
that is ~50% development and ~50% testing should have that testing capability
surfaced honestly (as an umbrella phrase), while named tools the candidate does
not have (Selenium, performance testing) remain honest gaps.
"""

# A full-stack engineer whose bullets show real testing/quality signals.
DEV_TEST_RESUME = (
    "Sam Rivera\n"
    "sam@example.com | linkedin.com/in/samrivera\n"
    "PROFESSIONAL SUMMARY\n"
    "Full-stack software engineer building web applications end to end.\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Nimbus Apps Remote\n"
    "Software Engineer 2019 - 2024\n"
    "- Built React and Node.js web features and REST APIs for a SaaS platform\n"
    "- Wrote unit tests and integration tests for core services and resolved defects\n"
    "- Performed code reviews and maintained CI/CD quality gates for releases\n"
    "- Debugged production issues and validated releases before deployment\n"
    "EDUCATION\n"
    "State University\n"
    "Bachelor of Computer Science 2015 - 2019\n"
)

# A role that is ~50% development, ~50% testing, plus named tools the candidate lacks.
DEV_TEST_JD = (
    "Software Development Engineer in Test\n"
    "Required qualifications: JavaScript, React, Node.js, REST APIs, unit testing, "
    "integration testing, test automation, CI/CD\n"
    "Preferred qualifications: Selenium, performance testing\n"
    "Responsibilities: build web features, write automated tests, perform test automation, "
    "resolve defects, run CI/CD quality gates\n"
)


def _profile(bullets: list[str], skills: dict[str, str] | None = None) -> Profile:
    return Profile(
        contact=ContactInfo(name="Sam Rivera"),
        retired_emails=[],
        role_identities=["Software Engineer"],
        tier_a=skills or {},
        tier_b={},
        tier_c={},
        adjacency={},
        experiences=[Experience(company="Nimbus", title="Engineer", location="", dates="2019 - 2024", bullets=bullets)],
        education=[],
        certifications=[],
        supported_metrics=[],
    )


# --------------------------------------------------------------------------- #
# Unit-level transfer policy
# --------------------------------------------------------------------------- #
def test_testing_transfer_requires_a_real_signal() -> None:
    with_signal = _profile(["Wrote unit tests and resolved defects"])
    without_signal = _profile(["Built dashboards and pipelines"])
    assert transfer_capability("test automation", with_signal) == "software testing and quality practices"
    assert transfer_capability("unit testing", with_signal) == "software testing and quality practices"
    assert transfer_capability("test automation", without_signal) is None


def test_named_test_tool_never_transfers() -> None:
    with_signal = _profile(["Wrote unit tests and integration tests"])
    # Named frameworks/practices must remain gaps, never invented by transfer.
    assert transfer_capability("selenium", with_signal) is None
    assert transfer_capability("performance testing", with_signal) is None
    assert transfer_capability("cypress", with_signal) is None


def test_transfer_does_not_fire_for_unrelated_keyword() -> None:
    with_signal = _profile(["Wrote unit tests"])
    assert transfer_capability("kubernetes", with_signal) is None


# --------------------------------------------------------------------------- #
# End-to-end 50/50 development-and-testing fixture
# --------------------------------------------------------------------------- #
def test_dev_and_test_role_surfaces_testing_without_fabrication() -> None:
    kit = generate_application_kit(
        resume_text=DEV_TEST_RESUME,
        job_description=DEV_TEST_JD,
        use_llm=False,
        include_resume=True,
        include_job_fit=True,
    )
    assert kit.resume is not None and kit.resume.validation.fatal is False
    assert kit.job_fit is not None

    adjacent = {value.lower() for value in kit.job_fit.adjacent_capabilities}
    gaps = {value.lower() for value in kit.job_fit.genuine_gaps}

    # Testing capability is recognized as transferable, not a gap.
    assert {"unit testing", "integration testing", "test automation"} & adjacent

    # Named tools the candidate lacks remain honest gaps and are never fabricated.
    assert "selenium" in gaps
    assert "performance testing" in gaps
    resume_lower = kit.resume.text.lower()
    assert "selenium" not in resume_lower
    assert "performance testing" not in resume_lower

    # The truthful umbrella phrase is surfaced in the resume; development evidence
    # (React, Node.js, REST) stays prominent.
    assert "software testing and quality practices" in resume_lower
    assert "react" in resume_lower
    assert "rest" in resume_lower


def test_transfer_lifts_alignment_but_not_via_fabrication() -> None:
    # Same candidate; a JD with the same dev requirements but no testing terms.
    dev_only_jd = (
        "Full-Stack Software Engineer\n"
        "Required qualifications: JavaScript, React, Node.js, REST APIs, CI/CD\n"
        "Responsibilities: build web features\n"
    )
    with_testing = generate_application_kit(
        resume_text=DEV_TEST_RESUME,
        job_description=DEV_TEST_JD,
        use_llm=False,
        include_resume=True,
        include_job_fit=True,
    )
    dev_only = generate_application_kit(
        resume_text=DEV_TEST_RESUME,
        job_description=dev_only_jd,
        use_llm=False,
        include_resume=True,
        include_job_fit=True,
    )
    assert with_testing.match_report is not None and dev_only.match_report is not None
    # Alignment reflects the transferable testing coverage the testing-heavy JD asks for.
    assert with_testing.match_report.alignment_score > 0

    # Repetition of a keyword never changes the keyword-match score.
    stuffed_resume = DEV_TEST_RESUME + "\n- testing testing testing testing testing"
    stuffed = generate_application_kit(
        resume_text=stuffed_resume,
        job_description=DEV_TEST_JD,
        use_llm=False,
        include_resume=True,
        include_job_fit=True,
    )
    assert stuffed.match_report is not None
    assert stuffed.match_report.original_ats_match.score == with_testing.match_report.original_ats_match.score
