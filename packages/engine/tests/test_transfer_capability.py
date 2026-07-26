from __future__ import annotations

from ats_engine.evidence.transfer import transfer_capability, transfer_match
from ats_engine.kit.orchestrator import generate_application_kit
from ats_engine.models import ContactInfo, Experience, Profile

"""Granular, requirement-specific evidence-to-capability transfer.

A developer who *writes unit tests* genuinely has unit-testing capability even
without the exact phrase, and that should surface honestly. But a single generic
signal (a code review, a CI/CD pipeline) must never earn adjacency credit against
five separate testing requirements — that inflates role alignment for a capability
the candidate has not demonstrated. Named tools the candidate lacks (Selenium,
performance testing) always remain honest gaps.
"""

_UMBRELLA = "software testing and quality practices"


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
# Direct, requirement-specific evidence supports its own requirement only.
# --------------------------------------------------------------------------- #
def test_unit_test_evidence_supports_unit_testing() -> None:
    profile = _profile(["Wrote unit tests for the payment service"])
    assert transfer_capability("unit testing", profile) == _UMBRELLA
    # ...but not the other distinct testing requirements.
    assert transfer_capability("integration testing", profile) is None
    assert transfer_capability("api testing", profile) is None
    assert transfer_capability("test automation", profile) is None
    assert transfer_capability("regression testing", profile) is None


def test_integration_test_evidence_supports_integration_testing_only() -> None:
    profile = _profile(["Wrote integration tests across services"])
    assert transfer_capability("integration testing", profile) == _UMBRELLA
    assert transfer_capability("unit testing", profile) is None
    assert transfer_capability("test automation", profile) is None


def test_api_test_evidence_supports_api_testing_only() -> None:
    profile = _profile(["Tested REST APIs for the billing platform"])
    assert transfer_capability("api testing", profile) == "API testing"
    assert transfer_capability("unit testing", profile) is None
    assert transfer_capability("regression testing", profile) is None


def test_automated_test_evidence_supports_test_automation() -> None:
    profile = _profile(["Built automated tests for the checkout flow"])
    assert transfer_capability("test automation", profile) == "test automation"
    # Must not invent a framework and must not spill into unit/integration.
    assert transfer_capability("unit testing", profile) is None
    assert transfer_capability("integration testing", profile) is None


def test_regression_evidence_supports_regression_testing() -> None:
    profile = _profile(["Performed regression testing before each release"])
    assert transfer_capability("regression testing", profile) == "regression testing"
    assert transfer_capability("unit testing", profile) is None


# --------------------------------------------------------------------------- #
# Adversarial: a generic quality signal must NOT satisfy specific testing reqs.
# --------------------------------------------------------------------------- #
def test_code_review_alone_does_not_satisfy_testing_requirements() -> None:
    profile = _profile(["Performed code reviews for web application changes"])
    for requirement in (
        "unit testing",
        "integration testing",
        "api testing",
        "test automation",
        "regression testing",
    ):
        assert transfer_capability(requirement, profile) is None, requirement
    # Code review does support the code-review requirement and general quality.
    assert transfer_capability("code review", profile) is not None
    assert transfer_capability("quality assurance", profile) == _UMBRELLA


def test_debugging_alone_does_not_satisfy_unit_testing() -> None:
    profile = _profile(["Debugged production issues and resolved defects"])
    assert transfer_capability("unit testing", profile) is None
    assert transfer_capability("test automation", profile) is None
    assert transfer_capability("debugging", profile) is not None


def test_cicd_alone_does_not_satisfy_integration_testing() -> None:
    profile = _profile(["Maintained CI/CD pipelines for the platform"])
    assert transfer_capability("integration testing", profile) is None
    assert transfer_capability("unit testing", profile) is None
    assert transfer_capability("ci/cd", profile) is not None


def test_one_signal_cannot_multiply_alignment_across_requirements() -> None:
    # Only code review; five separate testing requirements must all stay gaps.
    profile = _profile(["Performed code reviews for web application changes"])
    covered = [
        req
        for req in ("unit testing", "integration testing", "api testing", "test automation", "regression testing")
        if transfer_capability(req, profile) is not None
    ]
    assert covered == []


# --------------------------------------------------------------------------- #
# Named tools always remain gaps; unrelated keywords never transfer.
# --------------------------------------------------------------------------- #
def test_named_test_tool_never_transfers() -> None:
    profile = _profile(["Wrote unit tests and integration tests and automated tests"])
    for tool in ("selenium", "cypress", "playwright", "junit", "performance testing", "load testing"):
        assert transfer_capability(tool, profile) is None, tool


def test_transfer_does_not_fire_for_unrelated_keyword() -> None:
    profile = _profile(["Wrote unit tests"])
    assert transfer_capability("kubernetes", profile) is None
    assert transfer_capability("terraform", profile) is None


# --------------------------------------------------------------------------- #
# Fairness / identity invariance: names, pronouns, cities never change transfer.
# --------------------------------------------------------------------------- #
def test_transfer_is_identity_invariant() -> None:
    base_bullets = ["Wrote unit tests for the service"]
    a = _profile(base_bullets)
    a.contact = ContactInfo(name="Aisha Khan", location="Lagos, Nigeria")
    b = _profile(base_bullets)
    b.contact = ContactInfo(name="John Smith", location="Austin, Texas")
    assert transfer_capability("unit testing", a) == transfer_capability("unit testing", b)


def test_transfer_match_carries_reviewable_fields() -> None:
    profile = _profile(["Wrote unit tests for the payment service"])
    match = transfer_match("unit testing", profile)
    assert match is not None
    assert match.requirement == "unit testing"
    assert match.jd_term == "unit testing"
    assert match.evidence_signal  # a concrete matched signal
    assert match.evidence_source == "experience bullet"
    assert match.confidence in {"high", "medium", "low"}
    assert "unit test" in match.reason.lower()


# --------------------------------------------------------------------------- #
# End-to-end 50/50 development-and-testing fixture.
# --------------------------------------------------------------------------- #
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

DEV_TEST_JD = (
    "Software Development Engineer in Test\n"
    "Required qualifications: JavaScript, React, Node.js, REST APIs, unit testing, "
    "integration testing, test automation, CI/CD\n"
    "Preferred qualifications: Selenium, performance testing\n"
    "Responsibilities: build web features, write automated tests, perform test automation, "
    "resolve defects, run CI/CD quality gates\n"
)


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

    strongest = {value.lower() for value in kit.job_fit.strongest_matches}
    gaps = {value.lower() for value in kit.job_fit.genuine_gaps}

    # The candidate genuinely wrote unit and integration tests.  The V2
    # resolver recognizes these as direct aliases in an experience bullet, so
    # they are proven matches rather than merely transferable adjacency.
    assert {"unit testing", "integration testing"} & strongest
    # The candidate did NOT write automated tests: test automation stays a gap.
    assert "test automation" not in strongest

    # Named tools the candidate lacks remain honest gaps and are never fabricated.
    assert "selenium" in gaps
    assert "performance testing" in gaps
    resume_lower = kit.resume.text.lower()
    assert "selenium" not in resume_lower
    assert "performance testing" not in resume_lower

    # Direct source wording is preserved; development evidence stays prominent.
    assert "unit tests and integration tests" in resume_lower
    assert "react" in resume_lower
    assert "rest" in resume_lower


def test_repetition_never_changes_the_keyword_match_score() -> None:
    baseline = generate_application_kit(
        resume_text=DEV_TEST_RESUME,
        job_description=DEV_TEST_JD,
        use_llm=False,
        include_resume=True,
        include_job_fit=True,
    )
    stuffed_resume = DEV_TEST_RESUME + "\n- testing testing testing testing testing"
    stuffed = generate_application_kit(
        resume_text=stuffed_resume,
        job_description=DEV_TEST_JD,
        use_llm=False,
        include_resume=True,
        include_job_fit=True,
    )
    assert baseline.match_report is not None and stuffed.match_report is not None
    assert stuffed.match_report.original_ats_match.score == baseline.match_report.original_ats_match.score
