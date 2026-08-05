"""SURFACE_VARIANT integration: planning, rendering, and one honest, measured
gap between the two.

Two things are proven directly, at the level they are actually true:

1. Planning: a genuine substitution opportunity in a real resume/JD pair is
   proposed as a ``surface_variant`` action (``test_surface_variant_operation.py``
   already proves the substitution mechanics in isolation).
2. Rendering: a plan that already contains a substituted term renders and
   round-trips correctly -- the delivered document shows the JD's exact
   surface, and re-parsing it back finds the same thing. This is Task 2's
   "rendered-presence check," proven without going through full-pipeline
   acceptance.

Between those two sits a discovered, disclosed gap, marked ``xfail(strict=True)``
so it stays visible rather than silently passing or silently skipped: on every
case checked -- three real fixtures plus this file's own minimal, controlled
one-requirement pair -- the *general* named-entity fidelity check
(``validation/fidelity.py::bullet_fidelity_findings``, ``FIDELITY_UNSUPPORTED_NAMED_ENTITY``)
rejects a surface_variant candidate outright: it flags the JD's substituted
surface as an unsupported entity because that literal string search
(``_contains_fact``) does not know ``ReactJS`` is a registered vocabulary
alias of ``React``, which the candidate already has real, tier-A evidence for.
This is a real interaction with an existing, unrelated, widely-shared hard
gate, not a bug in this operation -- and per the brief's own instruction
("if a legitimate operation is blocked by a fact gate, report it rather than
loosening the gate"), it is reported here and not patched around. Teaching
that check vocabulary-alias awareness is a plausible fix; it is out of this
change's scope because it touches a validator every other LLM-rewrite path
also depends on.
"""

from __future__ import annotations

import pytest

from ats_engine.config import EngineSettings
from ats_engine.generation.delivered_layout import BULLET_MARKER
from ats_engine.generation.document_render import render_delivered_resume_text
from ats_engine.generation.pipeline import run_pipeline
from ats_engine.kit.orchestrator import _resume_document
from ats_engine.models import Mode
from ats_engine.parsing.resume import build_profile

_RESUME = """Avery Doe
TECHNICAL SKILLS
React
PROFESSIONAL EXPERIENCE
Cedar Labs
Frontend Developer 2020 - 2024
- Built dashboards using React and Redux for enterprise clients.
- Led a migration to a component-based architecture.
"""

_JD = """Job Title: Frontend Developer
Company: Example
Required qualifications:
- ReactJS
- Redux
"""

_UNSUPPORTED_NAMED_ENTITY_XFAIL_REASON = (
    "Discovered and disclosed, not a regression: validation/fidelity.py's "
    "FIDELITY_UNSUPPORTED_NAMED_ENTITY check does not know a JD surface is a "
    "registered vocabulary alias of an already-evidenced candidate term, so it "
    "rejects every surface_variant candidate checked (three real fixtures plus "
    "this minimal pair) as an unsupported entity. Not fixed here: it is a "
    "pre-existing, widely-shared general validator, and the brief explicitly "
    "says to report a gate blocking a legitimate operation rather than loosen it."
)


def test_a_genuine_variant_is_planned_in_a_real_resume_jd_pair() -> None:
    result = run_pipeline(resume_text=_RESUME, job_description=_JD, default_mode=Mode.RESUME, use_llm=False)
    trace = result.metadata["optimization_trace"]
    proposed = {record.id for record in trace.diagnostics.proposals}
    assert any(proposal_id.startswith("surface_variant:") for proposal_id in proposed), proposed


@pytest.mark.xfail(reason=_UNSUPPORTED_NAMED_ENTITY_XFAIL_REASON, strict=True)
def test_the_planned_variant_is_accepted_end_to_end() -> None:
    settings = EngineSettings(optimizer_policy="pareto", llm_cache_enabled=False)
    result = run_pipeline(
        resume_text=_RESUME,
        job_description=_JD,
        default_mode=Mode.RESUME,
        use_llm=False,
        settings=settings,
    )
    trace = result.metadata["optimization_trace"]
    surface_variant_actions = [action for action in trace.accepted_actions if action.startswith("surface_variant:")]
    assert surface_variant_actions, f"expected a surface_variant action to be accepted, got {trace.accepted_actions}"


def test_a_substituted_term_renders_and_survives_the_delivered_round_trip() -> None:
    """Task 2's rendered-presence check, proven at the rendering layer directly:
    a plan that already contains the substituted surface (as acceptance would
    produce it, were it not blocked by the gate documented above) delivers
    and re-parses correctly."""
    result = run_pipeline(resume_text=_RESUME, job_description=_JD, default_mode=Mode.RESUME, use_llm=False)
    assert result.resume_plan is not None
    plan = result.resume_plan
    plan.experience[0].bullets[0] = plan.experience[0].bullets[0].replace("React", "ReactJS")

    delivered_text = render_delivered_resume_text(_resume_document(plan))
    assert "ReactJS" in delivered_text
    assert f"{BULLET_MARKER} Built dashboards using ReactJS and Redux" in delivered_text

    reparsed = build_profile(delivered_text)
    reparsed_bullets = [bullet for experience in reparsed.experiences for bullet in experience.bullets]
    assert any("ReactJS" in bullet for bullet in reparsed_bullets)
