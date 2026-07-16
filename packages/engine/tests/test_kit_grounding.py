from __future__ import annotations

import pytest

from ats_engine.kit.contract import EVIDENCE_EXCERPT_MAX_CHARS, ArtifactKind, ClaimStatus, ClaimType
from ats_engine.kit.grounding import EvidenceContext, build_evidence_context, ground_text
from ats_engine.models import JDProfile
from ats_engine.parsing.resume import build_profile
from conftest import ADVERSARIAL_RESUME

"""Direct grounding-gate tests (Steps 14 and 15).

These exercise the truth gate at the unit level: they prove that each claim
extractor correctly removes an unsupported claim, preserves a supported one, and
records a structured disposition — independent of the full pipeline.
"""


def _context() -> EvidenceContext:
    profile = build_profile(ADVERSARIAL_RESUME)
    if not profile.raw_markdown:
        profile.raw_markdown = ADVERSARIAL_RESUME
    jd = JDProfile(title="AI Engineer", company="Vantage Analytics")
    return build_evidence_context(profile, jd)


def _ground(text: str, granularity: str = "prose") -> tuple[str, list[tuple[str, str, str]]]:
    outcome = ground_text(
        text,
        artifact=ArtifactKind.ANSWERS,
        context=_context(),
        id_prefix="t",
        granularity=granularity,
    )
    claims = [(claim.claim_type.value, claim.status.value, claim.text) for claim in outcome.claims]
    return outcome.clean_text, claims


def _statuses(claims: list[tuple[str, str, str]], claim_type: ClaimType) -> list[str]:
    return [status for ctype, status, _ in claims if ctype == claim_type.value]


# --------------------------------------------------------------------------- #
# Each fabrication type is removed (unit level)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "sentence,forbidden,claim_type",
    [
        ("I worked at Google on their ranking systems.", "google", ClaimType.EMPLOYER),
        ("I served as Chief Technology Officer there.", "chief technology officer", ClaimType.TITLE),
        ("I lifted conversion by 88% that year.", "88%", ClaimType.METRIC),
        ("I cut spend by $5 million in one year.", "5 million", ClaimType.MONETARY),
        ("I managed a team of 30 engineers on it.", "30 engineers", ClaimType.TEAM_SIZE),
        ("I am an expert in Rust and Haskell.", "rust", ClaimType.SKILL),
        ("I hold the CISSP certification now.", "cissp", ClaimType.CERTIFICATION),
        ("I completed a PhD in Physics that decade.", "phd", ClaimType.EDUCATION),
        ("I have 14 years of professional experience.", "14 years", ClaimType.TENURE),
    ],
)
def test_unsupported_claim_is_removed_and_recorded(sentence: str, forbidden: str, claim_type: ClaimType) -> None:
    clean, claims = _ground(f"This is fine. {sentence} This is also fine.")
    assert forbidden not in clean.lower()
    assert "this is fine" in clean.lower()  # surrounding safe content survives
    assert ClaimStatus.REPAIRED.value in _statuses(claims, claim_type)


# --------------------------------------------------------------------------- #
# Supported claims survive (Step 14 positive control at unit level)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "sentence,expected",
    [
        ("At Northstar Analytics I built the reporting stack.", "northstar analytics"),
        ("I reduced manual reporting time by 30% last year.", "30%"),
        ("I am proficient in Python for data work.", "python"),
        ("I hold a Bachelor of Computer Science degree.", "bachelor"),
    ],
)
def test_supported_claim_is_preserved(sentence: str, expected: str) -> None:
    clean, _claims = _ground(sentence)
    assert expected in clean.lower()


def test_supported_metric_is_marked_supported() -> None:
    _clean, claims = _ground("I reduced manual reporting time by 30% overall.")
    assert ClaimStatus.SUPPORTED.value in _statuses(claims, ClaimType.METRIC)


# --------------------------------------------------------------------------- #
# Gap ladder / adjacency (Step 15)
# --------------------------------------------------------------------------- #
def test_adjacent_tool_cannot_be_claimed_as_expertise() -> None:
    # The candidate never used Rust; adjacency must not let AI claim expertise.
    clean, claims = _ground("I have deep expertise in Rust for production services.")
    assert "rust" not in clean.lower()
    assert ClaimStatus.REPAIRED.value in _statuses(claims, ClaimType.SKILL)


def test_working_knowledge_cannot_become_multi_year_experience() -> None:
    clean, _claims = _ground("I have 12 years of hands-on Kubernetes in production.")
    assert "12 years" not in clean.lower()


def test_genuine_gap_cannot_be_written_as_a_credential() -> None:
    clean, _claims = _ground("I am an AWS Certified Solutions Architect.")
    assert "aws certified" not in clean.lower()


def test_naming_the_target_company_is_allowed() -> None:
    # Naming the JD's company is targeting, not a false history claim.
    clean, claims = _ground("I am excited about the role at Vantage Analytics.")
    assert "vantage analytics" in clean.lower()
    assert _statuses(claims, ClaimType.EMPLOYER) in ([], [ClaimStatus.SUPPORTED.value])


# --------------------------------------------------------------------------- #
# Bounded, privacy-conscious evidence excerpts
# --------------------------------------------------------------------------- #
def test_evidence_excerpts_are_bounded() -> None:
    _clean, _claims = _ground("I reduced manual reporting time by 30% overall.")
    outcome = ground_text(
        "I reduced manual reporting time by 30% overall.",
        artifact=ArtifactKind.ANSWERS,
        context=_context(),
        id_prefix="t",
    )
    for claim in outcome.claims:
        for ref in claim.evidence:
            assert len(ref.excerpt) <= EVIDENCE_EXCERPT_MAX_CHARS


def test_span_granularity_keeps_the_line_but_drops_the_value() -> None:
    # Bullet-style redaction: keep the bullet, remove only the fabricated value.
    clean, _claims = _ground("Built dashboards at Google for the team.", granularity="span")
    assert "google" not in clean.lower()
    assert "built dashboards" in clean.lower()
