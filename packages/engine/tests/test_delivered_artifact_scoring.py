"""The tailored score must be a measurement of the artifact, not of the plan.

Before this, the kit scored ``resume_artifact.text`` -- a labelled wire format
("Company: X | Location: Y | Title: Z") consumed by the LaTeX renderer, which
no delivered document has ever looked like. The number shown to the candidate
was therefore a projection of what the engine intended to produce, and nothing
in the system could observe what it actually produced. These tests pin the
score to the delivered text and would fail if it ever drifts back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ats_engine.evidence.resolver import resolve_requirements
from ats_engine.generation.document_render import (
    render_delivered_resume_text,
    render_resume_text_from_document,
)
from ats_engine.kit.orchestrator import generate_application_kit
from ats_engine.parsing.resume import build_profile
from ats_engine.pramana.requirements import extract_requirements
from ats_engine.pramana.scoring import score_resume

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"
CASES = ["crowdplat_web_scraper", "latentview_bi_ai", "cgi_fullstack_java_angular"]


def _available_cases() -> list[str]:
    return [case for case in CASES if (FIXTURES / case / "job_description.txt").exists()]


def _kit(case: str):
    return generate_application_kit(
        resume_text=(FIXTURES / "candidate_resume.pymupdf.txt").read_text(),
        job_description=(FIXTURES / case / "job_description.txt").read_text(),
        use_llm=False,
    )


@pytest.mark.parametrize("case", _available_cases())
def test_reported_tailored_score_equals_a_fresh_score_of_the_delivered_text(case: str) -> None:
    """§5 item 2, asserted exactly: reported == recomputed-from-delivered."""
    kit = _kit(case)
    if kit.match_report is None or kit.match_report.tailored_ats_match is None:
        pytest.skip("kit produced no tailored match score")
    assert kit.resume is not None and kit.resume.document is not None

    delivered_text = render_delivered_resume_text(kit.resume.document)
    jd_text = (FIXTURES / case / "job_description.txt").read_text()
    requirements = extract_requirements(jd_text)
    links = resolve_requirements(requirements, build_profile(delivered_text), delivered_text)
    recomputed = score_resume(delivered_text, requirements, links)

    assert kit.match_report.tailored_ats_match.score == pytest.approx(recomputed.score, abs=0.01)


@pytest.mark.parametrize("case", _available_cases())
def test_the_scored_text_is_the_delivered_layout_not_the_latex_wire_format(case: str) -> None:
    """A guard against silently reverting to scoring the plan.

    The two renderings are textually distinguishable: the delivered layout
    never emits the labelled ``Company:``/``Title:`` field prefixes that the
    LaTeX wire format is built from.
    """
    kit = _kit(case)
    assert kit.resume is not None and kit.resume.document is not None

    delivered = render_delivered_resume_text(kit.resume.document)
    wire_format = render_resume_text_from_document(kit.resume.document)

    assert "Company:" in wire_format and "Title:" in wire_format
    assert "Company:" not in delivered
    assert "Title:" not in delivered


@pytest.mark.parametrize("case", _available_cases())
def test_the_delivered_text_that_gets_scored_is_itself_parseable(case: str) -> None:
    """Scoring text that cannot be re-parsed would put us back where we started."""
    kit = _kit(case)
    assert kit.resume is not None and kit.resume.document is not None

    profile = build_profile(render_delivered_resume_text(kit.resume.document))

    assert profile.experiences
    assert sum(len(e.bullets) for e in profile.experiences) > 0
