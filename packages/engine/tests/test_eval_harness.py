from __future__ import annotations

from ats_engine.eval import CASES, run_all, run_case

"""Gate the Phase 2A quality-evaluation harness.

The deterministic path must never fabricate, so every case must have zero
truth-grounding violations and must preserve its expected real facts.
"""


def test_every_eval_case_has_zero_truth_grounding_violations() -> None:
    for result in run_all():
        assert result.truth_violations == [], f"{result.name}: {result.truth_violations}"


def test_every_eval_case_preserves_expected_supported_facts() -> None:
    for result in run_all():
        assert result.missing_supported == [], f"{result.name}: {result.missing_supported}"


def test_every_eval_case_produces_a_versioned_kit_with_requested_artifacts() -> None:
    for result in run_all():
        assert result.schema_ok, result.name
        assert result.artifact_present, result.name


def test_cases_cover_the_intended_scenarios() -> None:
    names = {case.name for case in CASES}
    assert {
        "strongly-aligned",
        "partially-aligned",
        "genuine-gaps",
        "adjacent-skills",
        "sparse-resume",
        "metric-rich",
    } <= names


def test_run_case_is_deterministic() -> None:
    case = CASES[0]
    assert run_case(case).preserved == run_case(case).preserved
