from __future__ import annotations

from ats_engine.generation.pipeline import run_pipeline
from ats_engine.parsing.document_extraction import normalize_extracted_text
from ats_engine.parsing.resume import extract_profile
from conftest import BASIC_JD

"""Regression coverage for the PDF-upload Resume-withholding defect.

Root cause: PDF text extraction can place a bullet glyph directly against its
text ("*Managed cloud infrastructure") with no literal space character, since
the visual gap is glyph positioning rather than a space codepoint. The
heuristic bullet detector required a trailing space, so those bullets were
read as plain header text instead of being attached to their employer. The
resume generator then silently dropped any employer left with zero bullets,
while completeness validation still counted it against the source profile,
producing a false "resume has fewer experience entries than source" failure
and Resume withholding — independent of whether the input arrived via Paste,
PDF, or DOCX.
"""

_NO_SPACE_BULLET_RESUME = (
    "Jordan Rivera\n"
    "555-201-9876 | jordan@example.com\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Acme Corp Remote\n"
    "Software Engineer 2022 to 2024\n"
    "*Built Python and SQL data pipelines for the finance team.\n"
    "*Reduced processing time by 40% across nightly jobs.\n"
    "Beta Retail Group Ottawa, ON\n"
    "Data Analyst 2018 to 2020\n"
    "*Built SQL reporting used by a team of 12 analysts.\n"
)

_BULLETLESS_ENTRY_RESUME = (
    "Jordan Rivera\n"
    "555-201-9876 | jordan@example.com\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Acme Corp Remote\n"
    "Software Engineer 2022 to 2024\n"
    "- Built Python and SQL data pipelines for the finance team.\n"
    "- Reduced processing time by 40% across nightly jobs.\n"
    "Beta Retail Group Ottawa, ON\n"
    "Data Analyst 2018 to 2020\n"
    "- Built SQL reporting used by a team of 12 analysts.\n"
    "Legacy Systems Inc Toronto, ON\n"
    "Junior Developer 2016 to 2018\n"
    "EDUCATION\n"
    "Carleton University Ottawa, ON\n"
    "Bachelor of Computer Science 2012 - 2016\n"
)


def test_heuristic_parser_attaches_bullets_with_no_space_after_marker() -> None:
    """`_is_bullet` must recognize "*text" (no gap), not just "* text"."""
    profile = extract_profile(_NO_SPACE_BULLET_RESUME)

    assert len(profile.experiences) == 2
    acme, beta = profile.experiences
    assert acme.company == "Acme Corp Remote"
    assert len(acme.bullets) == 2
    assert any("Built Python" in bullet for bullet in acme.bullets)
    assert any("Reduced processing time" in bullet for bullet in acme.bullets)
    assert beta.company == "Beta Retail Group Ottawa, ON"
    assert len(beta.bullets) == 1
    assert "Built SQL reporting" in beta.bullets[0]


def test_full_pipeline_with_no_space_bullets_is_not_withheld() -> None:
    """End-to-end: the exact defect chain (extraction -> generation -> completeness)
    must no longer produce a false withholding for glued bullet markers."""
    result = run_pipeline(
        resume_text=_NO_SPACE_BULLET_RESUME,
        job_description=BASIC_JD,
        requested_mode="resume",
        use_llm=False,
    )
    assert result.validation_errors == []
    assert "Acme Corp Remote" in result.resume_text
    assert "Beta Retail Group Ottawa, ON" in result.resume_text


def test_experience_entry_with_zero_bullets_is_not_dropped() -> None:
    """A verified employer with no bullets (header/dates only) must still be
    rendered, not silently discarded by `_select_experience`."""
    profile = extract_profile(_BULLETLESS_ENTRY_RESUME)
    assert len(profile.experiences) == 3
    bulletless = [entry for entry in profile.experiences if entry.company.startswith("Legacy Systems")]
    assert len(bulletless) == 1
    assert bulletless[0].bullets == []

    result = run_pipeline(
        resume_text=_BULLETLESS_ENTRY_RESUME,
        job_description=BASIC_JD,
        requested_mode="resume",
        use_llm=False,
    )
    assert result.validation_errors == []
    assert "Acme Corp Remote" in result.resume_text
    assert "Beta Retail Group Ottawa, ON" in result.resume_text
    assert "Legacy Systems Inc" in result.resume_text


def test_is_bullet_still_rejects_a_bare_marker_with_no_text() -> None:
    """The widened regex must not treat a lone marker (or marker + only
    whitespace) as a bullet."""
    profile = extract_profile(
        "Jordan Rivera\nPROFESSIONAL EXPERIENCE\nAcme Corp Remote\nSoftware Engineer 2022 to 2024\n-\n- \n"
    )
    assert profile.experiences
    assert profile.experiences[0].bullets == []


def test_document_extraction_inserts_space_after_glued_bullet_marker() -> None:
    normalized = normalize_extracted_text("*Managed cloud infrastructure across two regions.\n- Also fine already.")
    lines = normalized.splitlines()
    assert lines[0] == "* Managed cloud infrastructure across two regions."
    assert lines[1] == "- Also fine already."


def test_document_extraction_does_not_touch_numeric_leading_hyphen() -> None:
    """A leading "-5%"-style token must not be mistaken for a glued bullet."""
    normalized = normalize_extracted_text("-5% quarter-over-quarter change\nwell-known framework")
    assert normalized.splitlines()[0] == "-5% quarter-over-quarter change"
    assert "well-known framework" in normalized


def test_genuinely_incomplete_resume_is_still_caught_by_completeness_validation() -> None:
    """A real generation defect that drops an employer WITH bullets from the
    rendered resume text must still fail completeness validation — the fix
    only stops the false positive, it does not weaken the real check."""
    from ats_engine.models import ContactInfo, JDProfile, Mode, ParsedInput, PipelineResult
    from ats_engine.validation.completeness import validate_completeness

    profile = extract_profile(_NO_SPACE_BULLET_RESUME)
    assert len(profile.experiences) == 2

    # Simulate a rendered resume that only kept the first employer.
    truncated_resume_text = (
        "Candidate Header\n"
        "Professional Summary\nExperienced engineer.\n\n"
        "Technical Skills\nGeneral: SQL, Python\n\n"
        "Professional Experience\n"
        "Company: Acme Corp Remote | Title: Software Engineer | Dates: 2022 to 2024\n"
        "- Built Python and SQL data pipelines for the finance team.\n"
        "- Reduced processing time by 40% across nightly jobs.\n\n"
        "Education\n"
        "Certifications\n"
    )
    parsed_input = ParsedInput(
        resume_text=_NO_SPACE_BULLET_RESUME,
        job_description=BASIC_JD,
        contacts=ContactInfo(),
        questions=[],
        logistics={},
        mode=Mode.RESUME,
    )
    result = PipelineResult(parsed_input=parsed_input, jd_profile=JDProfile())
    result.resume_text = truncated_resume_text
    errors = validate_completeness(result, profile)
    assert any("experience entries" in error for error in errors)
