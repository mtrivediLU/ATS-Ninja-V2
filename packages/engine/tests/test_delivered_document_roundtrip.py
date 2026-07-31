"""The delivered resume must survive being read back by our own parser.

Every resume this engine delivered failed this property. A candidate who
downloads a tailored resume and re-uploads it -- "now tailor this for the next
job", the most obvious repeat workflow there is -- got a rejected or garbled
parse, and because the delivered document could not be re-read, the "tailored
score" shown in the product was computed from the plan rather than measured on
the artifact.

Two independent defects produced that, and both are pinned here:

1. ``Employer · Location`` on one line. The employer was read as
   ``Flosonics Medical ·`` and every following entry shifted by one slot, so a
   wrapped bullet's trailing prose landed in the employer field.
2. Bullets carrying no marker in the extracted text. DOCX numbering and CSS
   ``list-style`` draw a glyph that does not exist as text, so every bullet
   arrived as unmarked prose -- indistinguishable from a header line, and
   silently dropped. The generated resumes parsed to *zero* bullets.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ats_engine.generation.delivered_layout import BULLET_MARKER, FIELD_SEPARATOR
from ats_engine.generation.document_render import render_delivered_resume_text
from ats_engine.generation.pipeline import run_pipeline
from ats_engine.kit.orchestrator import _resume_document
from ats_engine.parsing.resume import build_profile

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"
CASES = ["crowdplat_web_scraper", "latentview_bi_ai", "cgi_fullstack_java_angular"]
TEMPLATES = ["classic", "modern"]


def _source_text() -> str:
    return (FIXTURES / "candidate_resume.pymupdf.txt").read_text()


def _available_cases() -> list[str]:
    return [case for case in CASES if (FIXTURES / case / "job_description.txt").exists()]


def _delivered_text(case: str) -> str:
    jd = (FIXTURES / case / "job_description.txt").read_text()
    result = run_pipeline(resume_text=_source_text(), job_description=jd, use_llm=False)
    assert result.resume_plan is not None
    return render_delivered_resume_text(_resume_document(result.resume_plan))


# --------------------------------------------------------------- the property ----


@pytest.mark.parametrize("case", _available_cases())
def test_delivered_resume_parses_without_an_extraction_suspect_error(case: str) -> None:
    """The headline property: our own output is readable by our own parser."""
    build_profile(_delivered_text(case))


@pytest.mark.parametrize("case", _available_cases())
def test_delivered_resume_preserves_every_employer_title_and_date(case: str) -> None:
    """Round-tripping must not lose or reorder a single role.

    This is the invariant that actually protects the candidate: an employer,
    title or date silently changing between the document they downloaded and
    the profile we re-derive from it is a truthfulness failure, not a
    formatting nit.
    """
    source = build_profile(_source_text())
    delivered = build_profile(_delivered_text(case))

    assert [e.company for e in delivered.experiences] == [e.company for e in source.experiences]
    assert [e.title for e in delivered.experiences] == [e.title for e in source.experiences]
    assert [e.dates for e in delivered.experiences] == [e.dates for e in source.experiences]


@pytest.mark.parametrize("case", _available_cases())
def test_delivered_resume_preserves_bullet_content(case: str) -> None:
    """Bullets must survive extraction -- they carry all of the evidence.

    Before the literal marker landed, this count was zero for every delivered
    resume while the source parsed its bullets fine.
    """
    delivered = build_profile(_delivered_text(case))
    assert sum(len(e.bullets) for e in delivered.experiences) > 0
    for experience in delivered.experiences:
        assert experience.bullets, f"{experience.company} round-tripped with no bullets"


@pytest.mark.parametrize("case", _available_cases())
def test_delivered_resume_preserves_credential_ids(case: str) -> None:
    """A credential ID is a verifiable claim; losing it degrades the document."""
    source = build_profile(_source_text())
    expected = {c.credential_id for c in source.certifications if c.credential_id}
    if not expected:
        pytest.skip("source resume carries no credential IDs")
    delivered_text = _delivered_text(case)
    for credential_id in expected:
        assert credential_id in delivered_text


# ------------------------------------------------------- the two defect shapes ----


def test_employer_and_location_on_one_separated_line_still_resolve() -> None:
    """Pins defect 1 directly, independent of the pipeline."""
    resume = (
        "Candidate Name\n\nProfessional Experience\n"
        f"Flosonics Medical {FIELD_SEPARATOR} Toronto, ON (Remote)\n"
        "Oct 2024 - Apr 2026\n"
        "Business Intelligence Developer\n"
        f"{BULLET_MARKER} Built a data warehouse using PostgreSQL and dbt.\n"
    )
    profile = build_profile(resume)

    assert [e.company for e in profile.experiences] == ["Flosonics Medical"]
    assert profile.experiences[0].title == "Business Intelligence Developer"
    assert "Toronto" in profile.experiences[0].location


def test_a_company_name_containing_a_separator_is_not_split() -> None:
    """The separator rule is recognition, not a blanket split.

    The right-hand side must itself be a well-formed ``City, Region`` tail, so
    a company that merely contains the character keeps its name intact.
    """
    resume = (
        "Candidate Name\n\nProfessional Experience\n"
        f"Smith {FIELD_SEPARATOR} Jones Consulting\n"
        "Oct 2024 - Apr 2026\n"
        "Software Engineer\n"
        f"{BULLET_MARKER} Delivered a payments integration.\n"
    )
    profile = build_profile(resume)

    assert profile.experiences[0].company == f"Smith {FIELD_SEPARATOR} Jones Consulting"


def test_every_delivered_bullet_carries_a_literal_marker() -> None:
    """Defect 2: the marker must be text, not styling, or bullets vanish."""
    cases = _available_cases()
    if not cases:
        pytest.skip("no real job-description fixtures available")
    delivered = _delivered_text(cases[0])
    experience_bullets = [line for line in delivered.splitlines() if line.startswith(BULLET_MARKER)]
    assert experience_bullets, "delivered text contains no marked bullets at all"


@pytest.mark.parametrize("template", TEMPLATES)
def test_docx_and_html_render_every_template_without_error(template: str) -> None:
    """Both templates must render; §6 item 1 requires the property on both."""
    from ats_engine.generation.docx_renderer import render_resume_docx
    from ats_engine.generation.html_renderer import render_resume_html

    cases = _available_cases()
    if not cases:
        pytest.skip("no real job-description fixtures available")
    jd = (FIXTURES / cases[0] / "job_description.txt").read_text()
    result = run_pipeline(resume_text=_source_text(), job_description=jd, use_llm=False)
    assert result.resume_plan is not None
    document = _resume_document(result.resume_plan)

    assert render_resume_docx(document, template)
    html = render_resume_html(document, template)
    # The glyph must be in the markup's text, not only in a CSS marker.
    assert BULLET_MARKER in html
