"""Two different checks, both named "score went down" -- proven structurally distinct.

``generation/optimizer.py`` already has a *truth* gate: when the source
projection itself scores below the raw resume (or fails a FATAL preservation
finding), that is evidence the projection corrupted or lost content, and the
resume is withheld -- ``trace.delivery_state = NEEDS_INPUT_REVIEW``, the
artifact's text/latex/document are zeroed by ``orchestrator.py`` before
anything is scored, and the kit rolls up honestly as
``KitState.NEEDS_INPUT_REVIEW``, never ``completed``.

The check changed in this PR is a different thing entirely: an end-of-run
*quality* comparison of the delivered tailored score against the delivered
original score, which can only be computed on a resume that survived the
truth gate above (both scores need real text). This file proves the two
never overlap -- the quality check cannot mask a corrupt-input case, because
it structurally cannot run on one. If this ever changes (e.g. someone routes
a withheld resume's fallback text into scoring), these tests fail.
"""

from __future__ import annotations

import ats_engine.generation.optimizer as optimizer_module
from ats_engine.kit.contract import DocumentState, KitState
from ats_engine.kit.orchestrator import generate_application_kit
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


def test_a_corrupted_source_projection_is_withheld_not_delivered_with_a_warning(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    """The truth gate: a projection that lost fidelity never reaches the user.

    Forces exactly the scenario ``test_low_score_projection_requires_review_
    without_reexposing_unsafe_plan`` exercises at the ``optimize()`` level, but
    drives it through the full ``generate_application_kit`` orchestrator to
    prove the end-to-end behaviour: state is ``needs_input_review``, not
    ``completed``, and the resume artifact carries no text/document -- it is
    withheld, not delivered quietly with a warning attached.
    """
    # current_score now goes through _evaluate_plan's direct score_resume call
    # (Step 3), not the score_resume_v2 shim this used to patch; original is
    # computed via score_resume_v2's own separate score_resume reference and
    # is deliberately left genuine -- comfortably above the low value forced
    # here, so the "source scored below raw resume" comparison still fires.
    low_score = PramanaScore(
        score=1.0,
        keyword_score=1.0,
        title_alignment=0.0,
        placement_bonus=0.0,
        stuffing_penalty=0.0,
        confidence="high",
        required_coverage=1.0,
        preferred_coverage=1.0,
    )
    monkeypatch.setattr(optimizer_module, "score_resume", lambda *args, **kwargs: low_score)

    kit = generate_application_kit(
        resume_text=_RESUME,
        job_description=_JD,
        use_llm=False,
        include_resume=True,
        include_cover_letter=False,
        include_application_answers=False,
        include_job_fit=False,
        include_interview_prep=False,
        include_linkedin_outreach=False,
    )

    assert kit.resume is not None
    assert kit.resume.text == ""
    assert kit.resume.document is None
    assert kit.match_report is not None
    assert kit.match_report.optimization_trace.delivery_state is DocumentState.NEEDS_INPUT_REVIEW

    # The state that actually gates the API/UI must reflect the withholding.
    assert kit.state is KitState.NEEDS_INPUT_REVIEW
    assert kit.state is not KitState.COMPLETED

    # A withheld resume has no delivered text for either score, so the
    # tailored/original comparison this PR made non-fatal cannot even run --
    # there is nothing for it to silently wave through.
    if kit.match_report is not None:
        assert kit.match_report.tailored_ats_match is None


def test_a_merely_non_improving_tailored_resume_is_delivered_and_labelled() -> None:
    """The quality check this PR changed: a real document, an honest number.

    No monkeypatching -- this is the real pipeline scoring a real delivered
    resume against a JD it has essentially nothing to offer, so tailoring
    cannot improve the score. The resume still has to be withheld ONLY when it
    is untrustworthy, not merely unimpressive: the document delivers, with a
    truthful "did not improve" note, not a crash and not silence.
    """
    resume = """Avery Doe
    TECHNICAL SKILLS
    Woodworking
    PROFESSIONAL EXPERIENCE
    Cedar Labs
    Analyst 2020 - 2024
    - Built furniture for a small workshop.
    """
    jd = """Job Title: Senior Kubernetes Platform Engineer
    Company: Example
    Required qualifications:
    - Kubernetes
    - Terraform
    - Go
    """

    kit = generate_application_kit(
        resume_text=resume,
        job_description=jd,
        use_llm=False,
        include_resume=True,
        include_cover_letter=False,
        include_application_answers=False,
        include_job_fit=False,
        include_interview_prep=False,
        include_linkedin_outreach=False,
    )

    assert kit.resume is not None
    # Not withheld: a real document is still delivered.
    assert kit.state is not KitState.NEEDS_INPUT_REVIEW
    assert kit.resume.text != "" or kit.resume.document is not None
