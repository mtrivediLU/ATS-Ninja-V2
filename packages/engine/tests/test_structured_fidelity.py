"""Focused contract tests for structured, calibrated fidelity validation."""

from __future__ import annotations

from dataclasses import replace

from ats_engine.validation.calibration import (
    CalibrationKey,
    apply_calibration,
    calibrate_identity,
    suppression_audit,
)
from ats_engine.validation.fidelity import (
    BulletPair,
    bullet_fidelity_findings,
    contains_fact,
    extract_named_entities,
    validate_raw_source_findings,
)
from ats_engine.validation.severity import (
    CAL_FALSE_POSITIVE,
    FIDELITY_MISSING_ORIGINAL_METRIC,
    FIDELITY_RAW_BULLET_CONTENT_LOST,
    FIDELITY_UNSUPPORTED_NAMED_ENTITY,
    ValidationFinding,
    ValidationSeverity,
    is_fatal_validation_error,
    partition_validation_errors,
)


def test_named_entities_respect_punctuation_boundaries_and_shared_canonicalizer() -> None:
    source_line = (
        'Tata Consultancy Services - AICMSE: ZoomInfo; M-Files | "Northwind Partners" (Acme Holdings) / Fabrikam Group'
    )

    entities = extract_named_entities(source_line)

    assert {
        "Tata Consultancy Services",
        "AICMSE",
        "ZoomInfo",
        "M-Files",
        "Northwind Partners",
        "Acme Holdings",
        "Fabrikam Group",
    }.issubset(entities)
    assert "Tata Consultancy Services AICMSE" not in entities
    assert all(contains_fact(source_line, entity) for entity in entities)
    # The comparison path uses the same canonicalizer for extracted entities
    # and source lines, including equivalent typography for hyphenated brands.
    assert contains_fact("M–Files", "M-Files")

    slash_acronyms = extract_named_entities("CI/CD & Reliability")
    assert "CI" not in slash_acronyms
    assert "CD" not in slash_acronyms
    assert bullet_fidelity_findings("CI/CD & Reliability", "CI/CD & Reliability") == ()


def test_raw_bullet_retention_scans_experience_only() -> None:
    source = """Professional Experience
- Built billing reporting for finance users.
Technical Skills
- Python
Education
- Dean's List
Certifications
- Microsoft Certified: Power BI Data Analyst Associate
"""
    candidate_with_only_experience = """Professional Experience
- Built billing reporting for finance users.
"""

    assert validate_raw_source_findings(source, candidate_with_only_experience) == ()

    findings = validate_raw_source_findings(source, "Professional Experience\n")

    assert any(finding.code == FIDELITY_RAW_BULLET_CONTENT_LOST for finding in findings)
    assert all(finding.source_span.startswith("experience:") for finding in findings)


def test_structured_finding_calibration_is_exact_and_cannot_hide_fact_deletion() -> None:
    source = "Built Power BI dashboards for Tata Consultancy Services; reduced report time by 30%."
    candidate = "Built Power BI dashboards for Fabrikam Analytics."
    findings = bullet_fidelity_findings(
        source,
        candidate,
        source_text=source,
        source_span="experience:lines:7",
    )

    assert all(isinstance(finding, ValidationFinding) for finding in findings)
    assert all(finding.fact and finding.source_span and finding.detail for finding in findings)
    false_positive = next(finding for finding in findings if finding.code == FIDELITY_UNSUPPORTED_NAMED_ENTITY)
    deletion = next(finding for finding in findings if finding.code == FIDELITY_MISSING_ORIGINAL_METRIC)
    assert deletion.severity is ValidationSeverity.FATAL

    profile = calibrate_identity([false_positive])
    assert profile.contains(false_positive)
    assert suppression_audit(profile) == (FIDELITY_UNSUPPORTED_NAMED_ENTITY,)
    assert CalibrationKey.from_finding(false_positive) in profile.entries

    calibrated = apply_calibration(
        findings,
        profile,
        fact_is_present=lambda fact: contains_fact(candidate, fact),
    )
    calibrated_false_positive = next(finding for finding in calibrated if finding.fact == false_positive.fact)
    calibrated_deletion = next(finding for finding in calibrated if finding.fact == deletion.fact)

    assert calibrated_false_positive.code == CAL_FALSE_POSITIVE
    assert calibrated_false_positive.original_code == FIDELITY_UNSUPPORTED_NAMED_ENTITY
    assert calibrated_false_positive.severity is ValidationSeverity.WARN
    assert calibrated_false_positive.fact == false_positive.fact
    assert calibrated_false_positive.source_span == false_positive.source_span
    assert calibrated_false_positive.detail == false_positive.detail
    # A reviewed unrelated false positive cannot downgrade a genuine source
    # deletion from the same candidate output.
    assert calibrated_deletion.code == FIDELITY_MISSING_ORIGINAL_METRIC
    assert calibrated_deletion.severity is ValidationSeverity.FATAL
    assert is_fatal_validation_error(calibrated_deletion)
    assert not is_fatal_validation_error(calibrated_false_positive)

    fatal, warnings = partition_validation_errors(calibrated)
    assert calibrated_deletion in fatal
    assert calibrated_false_positive in warnings

    wrong_span = replace(false_positive, source_span="candidate:line:99")
    assert (
        apply_calibration(
            [wrong_span],
            profile,
            fact_is_present=lambda fact: contains_fact(candidate, fact),
        )[0].code
        == FIDELITY_UNSUPPORTED_NAMED_ENTITY
    )


def test_exact_same_fact_calibration_cannot_hide_a_later_deletion() -> None:
    source = "Reduced reporting time by 30%."
    deleted = "Reduced reporting time."
    deletion = next(finding for finding in bullet_fidelity_findings(source, deleted) if finding.fact == "30")
    exact_calibration = calibrate_identity([deletion])

    # Even an exact four-field calibration record fails closed without current
    # candidate-presence evidence.
    assert apply_calibration([deletion], exact_calibration)[0].severity is ValidationSeverity.FATAL

    guarded = bullet_fidelity_findings(
        source,
        deleted,
        calibrations=exact_calibration,
    )
    same_fact = next(finding for finding in guarded if finding.fact == "30")
    assert same_fact.code == FIDELITY_MISSING_ORIGINAL_METRIC
    assert same_fact.severity is ValidationSeverity.FATAL


def test_missing_paired_responsibility_bullet_is_fatal_even_when_a_sibling_overlaps() -> None:
    source = """Professional Experience
- Prepared weekly compliance reports for leadership.
- Prepared weekly compliance reports for customers.
"""
    candidate = """Professional Experience
- Prepared weekly compliance reports for customers.
"""
    findings = validate_raw_source_findings(
        source,
        candidate,
        bullet_pairs=(
            BulletPair(
                original="Prepared weekly compliance reports for leadership.",
                candidate="",
                location="experience:0:bullet:0",
            ),
            BulletPair(
                original="Prepared weekly compliance reports for customers.",
                candidate="Prepared weekly compliance reports for customers.",
                location="experience:0:bullet:1",
            ),
        ),
    )

    assert any(
        finding.code == FIDELITY_RAW_BULLET_CONTENT_LOST
        and finding.severity is ValidationSeverity.FATAL
        and "leadership" in finding.fact.casefold()
        for finding in findings
    )


def test_legacy_fidelity_strings_use_reviewed_code_mapping_not_a_blanket_marker() -> None:
    assert is_fatal_validation_error("resume: fidelity: missing original metric: 30%")
    assert not is_fatal_validation_error("resume: fidelity: observational prose mismatch")
