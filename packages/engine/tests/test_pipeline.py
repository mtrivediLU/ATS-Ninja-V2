from __future__ import annotations

from ats_engine.generation.pipeline import run_pipeline
from ats_engine.validation.output_format import validate_cover_letter_word_count
from conftest import BASIC_JD, SYNTHETIC_JD, SYNTHETIC_RESUME, WRAPPED_RESUME_TEXT


def test_cover_letter_word_count_is_280_to_320() -> None:
    result = run_pipeline(
        resume_text=(
            "Jordan Rivera\njordan@example.com\n555-201-9876\n\n"
            "Experience\nAcme Corp Remote\nSoftware Engineer 2020 to 2023\n"
            "- Built Python and SQL data pipelines.\n"
        ),
        job_description=BASIC_JD,
        requested_mode="resume and cover letter",
        use_llm=False,
    )
    assert result.cover_letter_plan is not None
    assert 280 <= result.cover_letter_plan.word_count <= 320
    assert not validate_cover_letter_word_count(result.cover_letter_text)


def test_full_pipeline_with_resume_containing_banned_words_and_scale_claims() -> None:
    result = run_pipeline(
        resume_text=WRAPPED_RESUME_TEXT,
        job_description=BASIC_JD,
        requested_mode="resume and cover letter",
        use_llm=False,
    )
    assert result.resume_text
    assert result.cover_letter_text
    # Every truth-grounding, completeness, style, and structural gate passed.
    assert result.validation_errors == []


def test_synthetic_bi_resume_jd_regression_keeps_complete_profile() -> None:
    """Deterministic regression: the tailored resume must preserve every employer,
    key skill, education, and certification from a complete multi-role resume,
    with no fabricated claims and no logistics field leakage."""
    result = run_pipeline(
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        requested_mode="resume and cover letter",
        use_llm=False,
    )

    assert result.validation_errors == []
    for company in [
        "Northwind Medical",
        "Ridgeline Labs",
        "City of Springfield",
        "Vertex Software",
        "Prairie Research Centre",
        "Global Systems Consulting",
    ]:
        assert company in result.resume_text
    for skill in ["Power BI", "Tableau", "SQL", "PostgreSQL", "dbt", "ETL/ELT"]:
        assert skill in result.resume_text
    assert "Education" in result.resume_text
    assert "Certifications" in result.resume_text
    assert "BI Certified: Data Analyst Associate (PL-300)" in result.resume_text
    # Logistics labels must not leak into the rendered resume as empty fields.
    assert "Work Authorization:" not in result.resume_text
    assert "Relocation:" not in result.resume_text
    # Cover letter coherence guards.
    assert "I also the candidate" not in result.cover_letter_text
    assert "Based in Senior Software Engineer" not in result.cover_letter_text
    assert not validate_cover_letter_word_count(result.cover_letter_text)


def test_default_mode_applies_when_no_explicit_request() -> None:
    from ats_engine.models import Mode

    result = run_pipeline(
        resume_text=WRAPPED_RESUME_TEXT,
        job_description=BASIC_JD,
        requested_mode="",
        default_mode=Mode.RESUME_AND_COVER,
        use_llm=False,
    )
    assert result.resume_text
    assert result.cover_letter_text


def test_questions_mode_produces_grounded_answers() -> None:
    result = run_pipeline(
        resume_text=WRAPPED_RESUME_TEXT,
        job_description="",
        questions_text="Are you legally eligible to work in Canada?\n\nWhy do you want this role?",
        use_llm=False,
    )
    assert result.answer_plan is not None
    assert len(result.answer_plan.answers) == 2
    assert result.answers_text.startswith("**Q1:")
    assert result.validation_errors == []
