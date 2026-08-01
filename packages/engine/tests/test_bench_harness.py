"""Tests for the deterministic, fixture-discovering benchmark harness."""

from __future__ import annotations

from pathlib import Path

from ats_engine.bench import discover_cases, format_report, load_external_scores, run_all


def test_harness_discovers_all_qualified_fixture_directories() -> None:
    root = Path(__file__).parent / "fixtures" / "real_extraction"
    expected = sorted(
        directory.name
        for directory in root.iterdir()
        if directory.is_dir()
        and (directory / "job_description.txt").is_file()
        and (directory / "resume_ats_ninja.pymupdf.txt").is_file()
    )
    assert [case.name for case in discover_cases()] == expected


def test_harness_report_is_byte_identical_across_runs() -> None:
    assert format_report(run_all()) == format_report(run_all())


def test_external_score_import_and_unclipped_negative_gap_closure() -> None:
    cases = {case.name: case for case in discover_cases()}
    latentview = load_external_scores(cases["latentview_bi_ai"].directory)
    crowdplat = load_external_scores(cases["crowdplat_web_scraper"].directory)

    assert latentview is not None
    assert latentview.manual_gap_closure == -0.25
    assert crowdplat is not None
    assert crowdplat.manual is None
    assert crowdplat.manual_gap_closure is None
