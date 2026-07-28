"""Certification integrity and the Immutable Fact Set.

These are the facts an employer can verify with one phone call: employers,
titles, dates, degrees, certifications, and credential IDs. The PRAMANA/RACHANA
work order makes them non-negotiable -- a missing element is fatal and a *new*
element is fatal, because a new element is fabrication. There is deliberately
no calibration, suppression, or severity tier here.

The certification tests below encode a bug that was reproduced on `main`
before any fix: `fixtures/real_extraction/candidate_resume.pymupdf.txt`
contains four certifications, each written as a four-line block --

    Microsoft Certified: Azure Fundamentals (AZ-900)
    2024
    Credential ID: TEST-CRED-002
    Verify

-- but the heuristic parser consumed one *line* at a time. The name line
produced a certification with no ID; the year and `Credential ID:` lines
stripped to empty and were dropped, discarding the ID; and `Verify` (the
anchor text of the credential hyperlink) survived as a phantom certification.
The observed result was eight certifications, four of them named `Verify`,
with `credential_id` empty on every one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ats_engine.parsing.resume import build_profile
from ats_engine.rachana.facts import ImmutableFactSet, build_fact_set, fact_set_violations

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"

EXPECTED_CERTIFICATIONS = (
    ("Salesforce Certified Agentforce Specialist (AI-201)", "TEST-CRED-001", "2025"),
    ("Microsoft Certified: Azure Fundamentals (AZ-900)", "TEST-CRED-002", "2024"),
    ("Microsoft Certified: Power BI Data Analyst Associate (PL-300)", "TEST-CRED-003", "2024"),
    ("Microsoft Certified: Power Platform Developer Associate (PL-400)", "TEST-CRED-004", "2024"),
)


@pytest.fixture(scope="module")
def real_profile():
    return build_profile((FIXTURES / "candidate_resume.pymupdf.txt").read_text())


def test_exactly_four_certifications_are_parsed(real_profile) -> None:
    """Four certifications in the source means four in the profile, never eight."""
    assert len(real_profile.certifications) == 4


def test_no_certification_is_created_from_hyperlink_anchor_text(real_profile) -> None:
    """`Verify` is the anchor text of a credential link, not a credential."""
    names = [certification.name for certification in real_profile.certifications]
    assert "Verify" not in names
    for name in names:
        assert name.strip(), "a certification must never be created with an empty name"


def test_every_credential_id_survives_parsing(real_profile) -> None:
    """A credential ID is opaque and unguessable, so losing one is unrecoverable."""
    parsed = {certification.name: certification.credential_id for certification in real_profile.certifications}
    for name, credential_id, _year in EXPECTED_CERTIFICATIONS:
        assert parsed.get(name) == credential_id


def test_certification_names_and_dates_are_exact(real_profile) -> None:
    parsed = {certification.name: certification.date for certification in real_profile.certifications}
    for name, _credential_id, year in EXPECTED_CERTIFICATIONS:
        assert parsed.get(name) == year


@pytest.mark.parametrize("_name, credential_id, _year", EXPECTED_CERTIFICATIONS)
def test_credential_ids_reach_the_immutable_fact_set(real_profile, _name, credential_id, _year) -> None:
    assert credential_id in build_fact_set(real_profile).credential_ids


# --------------------------------------------------------------- fact set ----


def test_fact_set_is_equal_to_itself(real_profile) -> None:
    """Determinism: the same profile must always yield the same facts."""
    assert build_fact_set(real_profile) == build_fact_set(real_profile)


def test_identical_fact_sets_report_no_violations(real_profile) -> None:
    facts = build_fact_set(real_profile)
    assert fact_set_violations(facts, facts) == []


def test_a_dropped_fact_is_a_violation(real_profile) -> None:
    """Fact loss -- the failure mode that deleted four credential IDs in production."""
    source = build_fact_set(real_profile)
    rendered = ImmutableFactSet(
        **{
            **source.as_dict(),
            "credential_ids": frozenset(list(source.credential_ids)[1:]),
        }
    )
    violations = fact_set_violations(source, rendered)
    assert violations, "dropping a credential ID must be reported"
    assert any("credential_id" in violation.field for violation in violations)
    assert all(violation.kind == "lost" for violation in violations)


def test_an_invented_fact_is_a_violation(real_profile) -> None:
    """Fabrication -- a fact present in the output that was never in the source."""
    source = build_fact_set(real_profile)
    rendered = ImmutableFactSet(
        **{
            **source.as_dict(),
            "employers": frozenset({*source.employers, "Acme Corporation"}),
        }
    )
    violations = fact_set_violations(source, rendered)
    assert violations, "inventing an employer must be reported"
    assert any(violation.kind == "invented" for violation in violations)


def test_metrics_are_captured_from_bullets(real_profile) -> None:
    """Every number in a bullet is a checkable claim, so every number is a fact."""
    metrics = build_fact_set(real_profile).metrics
    assert "100%" in metrics
