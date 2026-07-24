from __future__ import annotations

from dataclasses import dataclass

from ats_engine.models import Profile
from ats_engine.parsing.resume import term_in_text, term_in_text_affirmative

"""Bounded, reviewable, requirement-specific evidence-to-capability transfer.

A candidate can hold a capability a job description names even when their resume
uses different wording. A developer who *writes unit tests* genuinely has unit-
testing capability even without the exact phrase "unit testing". But that same
developer does **not** automatically have *integration testing*, *API testing*,
*test automation*, or *regression testing* capability just because they reviewed
code or maintained a CI/CD pipeline.

The earlier design used a single umbrella whose *any* signal activated *every*
testing JD term, so one generic signal (e.g. "code review") could earn adjacency
credit against five distinct requirements and inflate role alignment. This module
replaces that with a **granular, requirement-specific** policy:

- Transfer is decided per JD requirement. Each requirement carries its own,
  explicit list of the candidate evidence signals that legitimately support *it*
  (word-boundary matched, affirmative in bullets). "Code review" supports the
  *code review* and general *software quality* requirements only; it never
  satisfies unit/integration/API/regression testing or test automation.
- A transfer never invents a specific tool. Named tools/frameworks (Selenium,
  Cypress, JUnit, Mockito, JMeter, performance/load/security testing, ...) are
  ``FORBIDDEN_SPECIFICS`` and are never produced by transfer — they remain honest
  gaps unless the resume states them directly.
- A transfer yields a truthful *umbrella* phrase, preserving the candidate's real
  scope and seniority. Downstream it is treated as an adjacency (transferable, not
  direct): it lifts the evidence-based role-alignment score and is surfaced in the
  skills section, but it does **not** earn strict keyword-match credit for the
  exact JD term, so no score is inflated by a capability not directly shown.

Nothing here is free-form inference: a requirement transfers only when the
candidate's own bullets or skills carry an explicit, listed signal for that exact
requirement.
"""


# Named tools/frameworks/specialized testing types that must NEVER be produced by
# transfer, regardless of any generic quality signal. They remain honest gaps
# unless the candidate's resume states them directly (handled by tier lookup).
FORBIDDEN_SPECIFICS: frozenset[str] = frozenset(
    {
        "selenium",
        "cypress",
        "playwright",
        "junit",
        "testng",
        "mockito",
        "jest",
        "pytest",
        "mocha",
        "jasmine",
        "karma",
        "jmeter",
        "postman",
        "soapui",
        "appium",
        "cucumber",
        "robot framework",
        "performance testing",
        "load testing",
        "stress testing",
        "security testing",
        "penetration testing",
        "accessibility testing",
        "mobile testing",
    }
)


@dataclass(frozen=True, slots=True)
class CapabilityTransfer:
    """One requirement-specific transfer rule.

    ``jd_terms`` are the normalized JD requirement phrases this rule can cover;
    ``evidence_signals`` are the specific candidate signals that legitimately
    support *this* requirement. The rule fires only when one of its own signals is
    present — a signal listed on a different rule never activates this one.
    """

    requirement: str
    umbrella: str
    jd_terms: frozenset[str]
    evidence_signals: frozenset[str]
    confidence: str


@dataclass(frozen=True, slots=True)
class TransferMatch:
    """A concrete, reviewable transfer decision for a single JD requirement."""

    requirement: str
    jd_term: str
    umbrella: str
    evidence_signal: str
    evidence_source: str  # "experience bullet" | "skills"
    confidence: str
    reason: str
    allowed_placement: str


_QUALITY_UMBRELLA = "software testing and quality practices"

# Requirement-specific rules. Order matters only for determinism when a JD term
# is (unusually) listed on two rules; the first match wins.
CAPABILITY_TRANSFERS: tuple[CapabilityTransfer, ...] = (
    # General software quality: a broad quality signal legitimately supports a
    # generic "quality assurance"/"software quality" requirement. It deliberately
    # does NOT list bare "testing"/"software testing" as JD terms, so a code-review
    # signal can never satisfy a specific testing requirement through this rule.
    CapabilityTransfer(
        requirement="general software quality",
        umbrella=_QUALITY_UMBRELLA,
        jd_terms=frozenset({"software quality", "quality assurance", "qa", "quality engineering"}),
        evidence_signals=frozenset(
            {
                "code review",
                "code reviews",
                "peer review",
                "unit test",
                "unit tests",
                "integration test",
                "integration tests",
                "automated test",
                "automated tests",
                "regression test",
                "regression tests",
                "tested",
                "testing",
                "debug",
                "debugged",
                "debugging",
                "defect",
                "defects",
                "ci/cd",
                "cicd",
                "continuous integration",
                "quality gate",
                "quality gates",
                "release validation",
                "validated releases",
                "validated release",
            }
        ),
        confidence="medium",
    ),
    CapabilityTransfer(
        requirement="code review",
        umbrella="code review and peer feedback",
        jd_terms=frozenset({"code review", "code reviews", "peer review", "peer reviews"}),
        evidence_signals=frozenset({"code review", "code reviews", "peer review", "peer reviews", "reviewed code"}),
        confidence="high",
    ),
    CapabilityTransfer(
        requirement="debugging and defect resolution",
        umbrella="debugging and defect resolution",
        jd_terms=frozenset({"debugging", "defect resolution", "defect management", "troubleshooting", "bug fixing"}),
        evidence_signals=frozenset(
            {
                "debug",
                "debugged",
                "debugging",
                "defect",
                "defects",
                "bug",
                "bugs",
                "bugfix",
                "troubleshoot",
                "troubleshooting",
                "root cause",
                "resolved defects",
            }
        ),
        confidence="high",
    ),
    CapabilityTransfer(
        requirement="release validation",
        umbrella="release validation",
        jd_terms=frozenset({"release validation", "release testing", "uat", "user acceptance testing"}),
        evidence_signals=frozenset(
            {"release validation", "validated release", "validated releases", "release testing", "user acceptance"}
        ),
        confidence="medium",
    ),
    CapabilityTransfer(
        requirement="unit testing",
        umbrella=_QUALITY_UMBRELLA,
        jd_terms=frozenset({"unit testing", "unit tests", "unit test", "unit-testing"}),
        evidence_signals=frozenset({"unit test", "unit tests", "unit-test", "unit-tests", "unit testing"}),
        confidence="high",
    ),
    CapabilityTransfer(
        requirement="integration testing",
        umbrella=_QUALITY_UMBRELLA,
        jd_terms=frozenset({"integration testing", "integration tests", "integration test"}),
        evidence_signals=frozenset(
            {"integration test", "integration tests", "integration testing", "end-to-end test", "end-to-end tests"}
        ),
        confidence="high",
    ),
    CapabilityTransfer(
        requirement="api testing",
        umbrella="API testing",
        jd_terms=frozenset({"api testing", "api tests", "api test"}),
        evidence_signals=frozenset(
            {"api test", "api tests", "tested api", "tested apis", "tested the api", "tested rest", "api testing"}
        ),
        confidence="medium",
    ),
    CapabilityTransfer(
        requirement="test automation",
        umbrella="test automation",
        jd_terms=frozenset({"test automation", "automated testing", "automated tests", "automation testing"}),
        evidence_signals=frozenset(
            {"automated test", "automated tests", "test automation", "automation framework", "automated testing"}
        ),
        confidence="medium",
    ),
    CapabilityTransfer(
        requirement="regression testing",
        umbrella="regression testing",
        jd_terms=frozenset({"regression testing", "regression tests", "regression test"}),
        evidence_signals=frozenset({"regression test", "regression tests", "regression testing"}),
        confidence="medium",
    ),
    CapabilityTransfer(
        requirement="ci/cd quality gates",
        umbrella="CI/CD delivery",
        jd_terms=frozenset({"ci/cd", "cicd", "continuous integration", "continuous delivery", "continuous deployment"}),
        evidence_signals=frozenset(
            {
                "ci/cd",
                "cicd",
                "continuous integration",
                "continuous delivery",
                "continuous deployment",
                "build pipeline",
                "deployment pipeline",
            }
        ),
        confidence="medium",
    ),
)


def transfer_match(normalized_keyword: str, profile: Profile) -> TransferMatch | None:
    """Return a reviewable :class:`TransferMatch` for ``normalized_keyword`` when a
    bounded, requirement-specific, evidence-supported transfer applies; else ``None``.

    A named tool never transfers. A requirement transfers only when the candidate's
    own bullets or skills carry one of *that requirement's* explicit signals.
    """
    term = normalized_keyword.strip().lower()
    if not term or term in FORBIDDEN_SPECIFICS:
        return None
    for rule in CAPABILITY_TRANSFERS:
        if term not in rule.jd_terms:
            continue
        found = _find_signal(rule, profile)
        if found is None:
            continue
        signal, source = found
        return TransferMatch(
            requirement=rule.requirement,
            jd_term=term,
            umbrella=rule.umbrella,
            evidence_signal=signal,
            evidence_source=source,
            confidence=rule.confidence,
            reason=(
                f"The candidate's {source} shows '{signal}', which demonstrates the "
                f"{rule.requirement} capability this requirement asks for, using different wording."
            ),
            allowed_placement="umbrella capability phrasing in skills or summary; never a specific tool",
        )
    return None


def transfer_capability(normalized_keyword: str, profile: Profile) -> str | None:
    """Return the truthful umbrella phrase for a supported transferable requirement,
    or ``None``. Thin wrapper over :func:`transfer_match` for callers that only need
    the placement phrase (e.g. the evidence matrix)."""
    match = transfer_match(normalized_keyword, profile)
    return match.umbrella if match is not None else None


def _find_signal(rule: CapabilityTransfer, profile: Profile) -> tuple[str, str] | None:
    """Return ``(signal, source)`` for the first of this rule's signals the
    candidate genuinely demonstrates, or ``None``.

    Deterministic: signals are checked in sorted order so the reported evidence is
    stable across runs.
    """
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
    for signal in sorted(rule.evidence_signals):
        if any(
            term_in_text_affirmative(signal, bullet)
            for experience in profile.experiences
            for bullet in experience.bullets
        ):
            return signal, "experience bullet"
        if term_in_text(signal, skills_text):
            return signal, "skills"
    return None


__all__ = [
    "CAPABILITY_TRANSFERS",
    "FORBIDDEN_SPECIFICS",
    "CapabilityTransfer",
    "TransferMatch",
    "transfer_capability",
    "transfer_match",
]
