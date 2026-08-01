"""Regression coverage for deterministic, one-to-one proposal diagnostics."""

from __future__ import annotations

from ats_engine.generation.diagnostics import GateCode, ProposalStatus
from ats_engine.generation.integration_planner import plan_placements_with_inventory
from ats_engine.generation.pipeline import run_pipeline
from ats_engine.kit import application_kit_from_dict, application_kit_to_dict, generate_application_kit
from ats_engine.models import Mode
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import build_profile

RESUME = """Jordan Rivera
jordan.rivera@example.com
Professional Summary
Data engineer focused on reliable reporting.
Technical Skills
Python, SQL, APIs
Professional Experience
Northstar Analytics
Data Engineer
2022 - Present
- Built Python data pipelines and SQL reporting APIs.
Education
Bachelor of Computer Science
"""
JD = """Job Title: Data Engineer
Required qualifications:
- Python
- SQL
- Data pipelines
- APIs
"""


def _trace():
    result = run_pipeline(resume_text=RESUME, job_description=JD, default_mode=Mode.RESUME, use_llm=False)
    return result.metadata["optimization_trace"]


def test_every_planner_action_has_one_terminal_record() -> None:
    profile = build_profile(RESUME)
    jd_profile = parse_jd(JD, profile=profile, tailoring_v2=True)
    actions, inventory = plan_placements_with_inventory(
        result_links := _trace_plan_links(),
        profile,
        jd_profile,
    )
    trace = _trace()
    proposals = trace.diagnostics.proposals

    assert len(actions) == len(inventory) == len(proposals)
    assert len({proposal.id for proposal in proposals}) == len(proposals)
    assert all(isinstance(proposal.status, ProposalStatus) for proposal in proposals)
    assert all(
        proposal.gate_code is None or isinstance(proposal.gate_code, GateCode)
        for proposal in proposals
        if proposal.status is ProposalStatus.REJECTED
    )
    assert result_links


def test_proposal_ids_are_stable_across_identical_runs() -> None:
    first = _trace().diagnostics.proposals
    second = _trace().diagnostics.proposals

    assert [proposal.id for proposal in first] == [proposal.id for proposal in second]
    assert first == second


def test_diagnostics_round_trip_and_old_trace_default() -> None:
    kit = generate_application_kit(
        resume_text=RESUME,
        job_description=JD,
        default_mode=Mode.RESUME,
        use_llm=False,
        include_job_fit=False,
        include_interview_prep=False,
        include_linkedin_outreach=False,
    )
    data = application_kit_to_dict(kit)
    restored = application_kit_from_dict(data)

    assert restored is not None and restored.match_report is not None and kit.match_report is not None
    assert restored.match_report.optimization_trace.diagnostics == kit.match_report.optimization_trace.diagnostics

    old_data = application_kit_to_dict(kit)
    assert isinstance(old_data.get("match_report"), dict)
    trace = old_data["match_report"].get("optimization_trace")
    assert isinstance(trace, dict)
    trace.pop("diagnostics", None)
    old_restored = application_kit_from_dict(old_data)
    assert old_restored is not None and old_restored.match_report is not None
    assert old_restored.match_report.optimization_trace.diagnostics.proposals == ()


def _trace_plan_links():
    result = run_pipeline(resume_text=RESUME, job_description=JD, default_mode=Mode.RESUME, use_llm=False)
    assert result.resume_plan is not None
    return result.resume_plan.evidence_links
