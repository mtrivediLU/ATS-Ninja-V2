from __future__ import annotations

from dataclasses import dataclass

from ats_engine.models import Profile
from ats_engine.parsing.resume import term_in_text, term_in_text_affirmative

"""Bounded, reviewable evidence-to-capability transfer.

A candidate can hold a capability a job description names even when their resume
uses different wording. A full-stack engineer who writes automated tests,
reviews code, resolves defects, and runs CI/CD quality gates has genuine
*software testing and quality* capability, even without the exact phrase "test
automation" or a named framework.

This module recognizes that transfer **deterministically and conservatively**:

- Transfer is allowed only for a small, explicit set of umbrella capabilities,
  each with an explicit list of the JD terms it can cover and the candidate
  evidence signals that permit it. Nothing here is free-form LLM inference.
- A transfer never invents a specific tool. Named tools/frameworks (Selenium,
  Cypress, JUnit, Mockito, performance/security testing, ...) are listed as
  ``forbidden_specifics`` and are never produced by transfer — they remain honest
  gaps unless the resume states them directly.
- Transfer yields a truthful *umbrella* phrase ("software testing and quality
  practices"), preserving the candidate's real scope and seniority. Downstream it
  is treated as an adjacency (transferable, not direct): it lifts the evidence-
  based role-alignment score and is surfaced in the skills section, but it does
  **not** earn strict keyword-match credit for the exact JD term, so no score is
  inflated by a capability the candidate does not directly demonstrate.
"""


@dataclass(frozen=True, slots=True)
class CapabilityTransfer:
    umbrella: str
    jd_terms: frozenset[str]
    evidence_signals: frozenset[str]
    forbidden_specifics: frozenset[str]


CAPABILITY_TRANSFERS: tuple[CapabilityTransfer, ...] = (
    CapabilityTransfer(
        umbrella="software testing and quality practices",
        jd_terms=frozenset(
            {
                "testing",
                "software testing",
                "software quality",
                "quality assurance",
                "qa",
                "quality engineering",
                "unit testing",
                "unit tests",
                "integration testing",
                "integration tests",
                "api testing",
                "test automation",
                "automated testing",
                "automated tests",
                "test cases",
                "regression testing",
                "test-driven development",
                "tdd",
                "test coverage",
            }
        ),
        evidence_signals=frozenset(
            {
                "unit test",
                "unit tests",
                "integration test",
                "integration tests",
                "api test",
                "test",
                "tests",
                "tested",
                "testing",
                "test-driven",
                "debug",
                "debugging",
                "defect",
                "defects",
                "bug",
                "bugfix",
                "code review",
                "code reviews",
                "ci/cd",
                "cicd",
                "continuous integration",
                "release validation",
                "quality gate",
                "quality gates",
            }
        ),
        # Named tools/practices that must never be produced by transfer.
        forbidden_specifics=frozenset(
            {
                "selenium",
                "cypress",
                "playwright",
                "junit",
                "testng",
                "mockito",
                "jmeter",
                "postman",
                "soapui",
                "appium",
                "cucumber",
                "robot framework",
                "performance testing",
                "load testing",
                "security testing",
                "penetration testing",
            }
        ),
    ),
)


def transfer_capability(normalized_keyword: str, profile: Profile) -> str | None:
    """Return a truthful umbrella phrase when ``normalized_keyword`` is a bounded,
    evidence-supported transferable capability; otherwise ``None``.

    Deterministic and conservative: a named tool never transfers, and the
    umbrella is granted only when the candidate's own bullets or skills carry an
    explicit capability signal (word-boundary matched, affirmative in bullets).
    """
    term = normalized_keyword.strip().lower()
    for transfer in CAPABILITY_TRANSFERS:
        if term in transfer.forbidden_specifics:
            return None
        if term not in transfer.jd_terms:
            continue
        if _has_signal(transfer, profile):
            return transfer.umbrella
    return None


def _has_signal(transfer: CapabilityTransfer, profile: Profile) -> bool:
    skills_text = " ".join(
        [
            *profile.tier_a.keys(),
            *profile.tier_a.values(),
            *profile.tier_b.keys(),
            *profile.tier_b.values(),
            *profile.tier_c.keys(),
            *profile.tier_c.values(),
        ]
    ).lower()
    for signal in transfer.evidence_signals:
        if any(
            term_in_text_affirmative(signal, bullet)
            for experience in profile.experiences
            for bullet in experience.bullets
        ):
            return True
        if term_in_text(signal, skills_text):
            return True
    return False


__all__ = ["CAPABILITY_TRANSFERS", "CapabilityTransfer", "transfer_capability"]
