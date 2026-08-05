"""Phase 0 instrumentation: every planner proposal reaches a terminal status.

``_finalize_diagnostics`` originally asserted
``isinstance(record.status, ProposalStatus)`` -- true for every member of the
enum, including ``NOT_EVALUATED`` itself, so the check could never fail. The
invariant the docstring actually claims (every planner-emitted proposal
reaches exactly one terminal disposition) was unenforced: a run that returns
before the evaluation loop starts leaves every planner-proposed action
sitting at ``NOT_EVALUATED`` forever, and nothing caught it.

This forces exactly that early-return branch -- the same ``score_resume``
monkeypatch ``test_tailoring_v2_safety_fallback.py`` uses to make the source
projection score below the raw resume -- with a resume/JD pair that gives the
planner at least one real action to propose, so the assertion below is not
vacuously true over an empty list.

Patches ``score_resume`` as imported into ``generation.optimizer``, not the
``score_resume_v2`` compatibility shim: ``optimize()``'s ``_evaluate_plan``
(Step 3) calls PRAMANA directly, through that name, so it can project both
the legacy scalar score and the pareto objective vector from one pass. That
patch only reaches ``current_score`` (via ``_evaluate_plan``); ``original``
is computed through ``score_resume_v2``, which holds its own separate
``score_resume`` reference inside ``scoring/ats_v2.py`` and is deliberately
left genuine here -- a real resume/JD pair's real score is comfortably above
the single low value forced below, so the comparison the early return checks
does not need both sides mocked to fire reliably.
"""

from __future__ import annotations

import ats_engine.generation.optimizer as optimizer_module
from ats_engine.evidence.resolver import resolve_requirements
from ats_engine.generation.diagnostics import GateCode, ProposalStatus
from ats_engine.generation.optimizer import optimize
from ats_engine.generation.planning import build_resume_plan
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import build_profile
from ats_engine.pramana.contract import PramanaScore

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


def _pramana_score(score: float) -> PramanaScore:
    return PramanaScore(
        score=score,
        keyword_score=score,
        title_alignment=0.0,
        placement_bonus=0.0,
        stuffing_penalty=0.0,
        confidence="high",
        required_coverage=1.0,
        preferred_coverage=1.0,
    )


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
    # that fires before the evaluation loop ever schedules a proposal. Any
    # real resume/JD pair's genuine (unmocked) score is comfortably above 1.0.
    monkeypatch.setattr(optimizer_module, "score_resume", lambda *args, **kwargs: _pramana_score(1.0))

    _plan, trace = optimize(profile, jd_profile, jd_profile.requirements, links, base_plan)

    assert "requires review" in trace.rejected_actions[0].reason  # confirms the early-return branch fired
    assert trace.diagnostics.proposals, "the planner must have proposed at least one action for this fixture"
    assert all(record.status is not ProposalStatus.NOT_EVALUATED for record in trace.diagnostics.proposals)
    assert all(record.gate_code is GateCode.RUN_CONCLUDED_BEFORE_EVALUATION for record in trace.diagnostics.proposals)
