"""Phase 0 instrumentation: every planner proposal reaches a terminal status.

``_finalize_diagnostics`` originally asserted
``isinstance(record.status, ProposalStatus)`` -- true for every member of the
enum, including ``NOT_EVALUATED`` itself, so the check could never fail. The
invariant the docstring actually claims (every planner-emitted proposal
reaches exactly one terminal disposition) was unenforced: a run that returns
before the evaluation loop starts leaves every planner-proposed action
sitting at ``NOT_EVALUATED`` forever, and nothing caught it.

This forces exactly that early-return branch -- the same
``score_resume_v2`` monkeypatch ``test_tailoring_v2_safety_fallback.py``
uses to make the source projection score below the raw resume -- with a
resume/JD pair that gives the planner at least one real action to propose,
so the assertion below is not vacuously true over an empty list.
"""

from __future__ import annotations

import ats_engine.generation.optimizer as optimizer_module
from ats_engine.evidence.resolver import resolve_requirements
from ats_engine.generation.diagnostics import GateCode, ProposalStatus
from ats_engine.generation.optimizer import optimize
from ats_engine.generation.planning import build_resume_plan
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import build_profile
from ats_engine.scoring.ats_v2 import AtsScoreV2

_RESUME = """Avery Doe
TECHNICAL SKILLS
Python
PROFESSIONAL EXPERIENCE
Cedar Labs
Analyst 2020 - 2024
- Built Python reports for finance users.
"""

_JD = """Job Title: Python Analyst
Company: Example
Required qualifications:
- Python
"""


def test_every_planner_proposal_reaches_a_terminal_status_on_early_return(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    profile = build_profile(_RESUME)
    jd_profile = parse_jd(_JD, profile=profile, tailoring_v2=True)
    links = resolve_requirements(jd_profile.requirements, profile, _RESUME)
    base_plan = build_resume_plan(
        contacts=profile.contact,
        jd_profile=jd_profile,
        profile=profile,
        provider=None,
    )

    # Forces "source projection scored below raw resume" -- the early return
    # that fires before the evaluation loop ever schedules a proposal.
    scores = iter(
        (
            AtsScoreV2(score=80.0, base_score=80.0, density_penalty=0.0, placement_bonus=0.0),
            AtsScoreV2(score=79.0, base_score=79.0, density_penalty=0.0, placement_bonus=0.0),
        )
    )
    monkeypatch.setattr(optimizer_module, "score_resume_v2", lambda *args, **kwargs: next(scores))

    _plan, trace = optimize(profile, jd_profile, jd_profile.requirements, links, base_plan)

    assert "requires review" in trace.rejected_actions[0].reason  # confirms the early-return branch fired
    assert trace.diagnostics.proposals, "the planner must have proposed at least one action for this fixture"
    assert all(record.status is not ProposalStatus.NOT_EVALUATED for record in trace.diagnostics.proposals)
    assert all(record.gate_code is GateCode.RUN_CONCLUDED_BEFORE_EVALUATION for record in trace.diagnostics.proposals)
