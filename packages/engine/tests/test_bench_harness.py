"""Tests for the deterministic, fixture-discovering benchmark harness."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from ats_engine.bench import discover_cases, format_report, load_external_scores, run_all, run_case
from ats_engine.generation.pipeline import run_pipeline
from ats_engine.models import Mode


@cache
def _all_results():
    """Run the expensive real-fixture corpus only once in this test module."""
    return run_all()


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
    results = _all_results()
    assert format_report(results) == format_report(results)

    crowdplat = next(case for case in discover_cases() if case.name == "crowdplat_web_scraper")
    expected = next(result for result in results if result.name == crowdplat.name)
    assert run_case(crowdplat) == expected


def test_external_score_import_and_unclipped_negative_gap_closure() -> None:
    cases = {case.name: case for case in discover_cases()}
    latentview = load_external_scores(cases["latentview_bi_ai"].directory)
    crowdplat = load_external_scores(cases["crowdplat_web_scraper"].directory)

    assert latentview is not None
    assert latentview.manual_gap_closure == -0.25
    assert crowdplat is not None
    assert crowdplat.manual is None
    assert crowdplat.manual_gap_closure is None


def test_cgi_targeting_clause_no_longer_self_inflicts_a_stuffing_block() -> None:
    """Regression guard for a self-inflicted, pre-existing defect.

    ``_source_content_plan``'s engine-authored targeting clause echoes the JD
    title ("... Java + Angular ...") into the candidate's own summary, which
    used to push a term already near its stuffing ceiling over it -- and then
    every placement proposal was rejected because of a repetition the
    candidate never created. This held the CGI fixture at zero accepted
    actions across three consecutive engine steps regardless of policy. Fixed
    by excluding that clause from the text anti-stuffing measurement counts
    (``optimizer._without_targeting``); this must not regress back to zero.
    """
    result = next(result for result in _all_results() if result.name == "cgi_fullstack_java_angular")
    accepted = result.diagnostics.proposals_by_status.get("accepted", 0)
    assert accepted > 0, (
        f"CGI fixture accepted {accepted} proposals; expected > 0. "
        f"rejections_by_gate={dict(result.diagnostics.rejections_by_gate)}"
    )
    assert "stuffing" not in result.diagnostics.rejections_by_gate or (
        result.diagnostics.rejections_by_gate["stuffing"] < len(result.diagnostics.proposals)
    ), "every proposal was rejected as stuffing again -- the targeting-clause self-inflicted block has returned"


def test_crowdplat_placement_reinforcement_recovers_step2_accepted_action_count() -> None:
    """Regression guard for CrowdPlat's accepted-action count under pareto.

    PRAMANA's own ``_placement_bonus`` rewards a term reinforced in both
    skills and a bullet, but that bonus never reaches ``keyword_score`` (and
    therefore never reaches ``pramana_coverage``), so the pareto policy's
    original three objectives structurally could not see it -- it rejected
    every action legacy accepted on that basis alone as a flat,
    zero-objective-movement candidate, dropping this fixture's accepted count
    from Step 2's 8 to 1. Fixed by giving pareto a fourth objective,
    ``ScoreVector.placement_reinforcement`` (reused from
    ``PramanaScore.placement_bonus``, not recomputed). This must not regress
    below Step 2's count.
    """
    cases = {case.name: case for case in discover_cases()}
    case = cases["crowdplat_web_scraper"]
    resume_text = case.source_resume.read_text(encoding="utf-8")
    job_description = case.job_description.read_text(encoding="utf-8")

    result = run_pipeline(
        resume_text=resume_text, job_description=job_description, default_mode=Mode.RESUME, use_llm=False
    )
    trace = result.metadata["optimization_trace"]
    assert len(trace.accepted_actions) >= 8, (
        f"CrowdPlat accepted {len(trace.accepted_actions)} actions "
        f"({trace.accepted_actions!r}); expected at least Step 2's 8."
    )
