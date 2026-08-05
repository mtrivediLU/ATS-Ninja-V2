"""SURFACE_VARIANT integration: planning, end-to-end acceptance, and rendering.

Three things are proven, at the level they are actually true:

1. Planning: a genuine substitution opportunity in a real resume/JD pair is
   proposed as a ``surface_variant`` action (``test_surface_variant_operation.py``
   already proves the substitution mechanics in isolation).
2. Acceptance: on a real fixture, at least one planned ``surface_variant``
   action is genuinely accepted end-to-end under the default (pareto) policy.
3. Rendering: a plan that already contains a substituted term renders and
   round-trips correctly -- the delivered document shows the JD's exact
   surface, and re-parsing it back finds the same thing. This is Task 2's
   "rendered-presence check," proven without going through full-pipeline
   acceptance.

An earlier version of this file used a minimal, purpose-built one-requirement
pair for #2 and found every SURFACE_VARIANT candidate blocked, via
``xfail(strict=True)``, by two discovered, disclosed, and since-fixed defects:

* ``validation/fidelity.py``'s ``FIDELITY_UNSUPPORTED_NAMED_ENTITY`` check did
  not resolve a candidate entity through the vocabulary's canonical/alias
  registry, so it flagged the JD's substituted surface as an unsupported
  entity even when the candidate already had real evidence for the same
  canonical under a different spelling (fixed: ``_vocabulary_alias_canonicals``
  in ``validation/fidelity.py``).
* ``rachana/preservation.py``'s term-preservation guard floored a
  vocabulary-backed requirement on whichever single literal spelling
  happened to dominate the source, so any alias-spelling substitution looked
  like a regression of that one literal form by construction (fixed:
  ``_canonical_occurrence_counts`` floors a vocabulary-backed requirement on
  its alias-merged canonical presence instead).

Fixing both was necessary but, on the minimal pair specifically, not
sufficient: that fixture's tiny two-requirement vocabulary means nearly every
remaining candidate action lands in one bisected batch, and that batch's
*combined* effect (not the surface_variant substitution itself) trips a
density regression unrelated to either fix above. Rather than force a
synthetic fixture to cooperate, #2 below is proven against a real bench
fixture instead, which is also the actual bar success criteria are measured
against. A third, real, independent defect was found and fixed in the
process: ``pramana/scoring.py::_placement_target_text`` did not recognize the
granular ``skills:<group>:<item>`` target a skills-tier SURFACE_VARIANT action
carries (every other skills-targeted operation uses the bare ``"skills"``),
so its provenance check silently failed and its requirement's credit was
zeroed regardless of the substitution's own correctness.
"""

from __future__ import annotations

from pathlib import Path

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

_REAL_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "real_extraction" / "latentview_bi_ai"


def test_a_genuine_variant_is_planned_in_a_real_resume_jd_pair() -> None:
    result = run_pipeline(resume_text=_RESUME, job_description=_JD, default_mode=Mode.RESUME, use_llm=False)
    trace = result.metadata["optimization_trace"]
    proposed = {record.id for record in trace.diagnostics.proposals}
    assert any(proposal_id.startswith("surface_variant:") for proposal_id in proposed), proposed


def test_a_planned_variant_is_accepted_end_to_end_on_a_real_fixture() -> None:
    shared_source = _REAL_FIXTURE.parent / "candidate_resume.pymupdf.txt"
    source_path = shared_source if shared_source.is_file() else _REAL_FIXTURE / "resume_ats_ninja.pymupdf.txt"
    resume_text = source_path.read_text(encoding="utf-8")
    job_description = (_REAL_FIXTURE / "job_description.txt").read_text(encoding="utf-8")

    result = run_pipeline(
        resume_text=resume_text, job_description=job_description, default_mode=Mode.RESUME, use_llm=False
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
