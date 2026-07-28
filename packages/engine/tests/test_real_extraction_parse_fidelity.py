"""Real-extraction parse fidelity: employer identity and wrapped-bullet retention.

Every test in this file runs against `fixtures/real_extraction/candidate_resume.pymupdf.txt`
-- the byte-for-byte raw PyMuPDF extraction of a real resume PDF, contact-redacted only
(name/phone/email/LinkedIn/portfolio -> placeholders; the four certification credential IDs
also replaced with placeholder IDs of the same shape, a privacy hardening beyond the letter
of the redaction spec since this repository is public). Every employer, title, date, location,
education line, certification, and metric below is exactly what real extraction produced.

This file exists because three previous rounds of parser fixes were each validated only
against a hand-written fixture (now `fixtures/synthetic_shapes/`) that never reproduced the
real PDF's actual line shapes -- multi-line Company/Location/Title/Dates headers, hyphen
wraps, glued words, glyph artifacts -- so the underlying bug (the resume parser silently
replacing every employer with a city name, and a digit-leading wrapped bullet continuation
being dropped) survived all three rounds undetected.

The `candidate_resume.pdf` binary fixture named in the PR spec was attempted via PyMuPDF
redaction (`page.add_redact_annot(..., text=...)` + `apply_redactions()`) and rejected: it
reflows/corrupts exactly the contact-block line structure the spec requires preserved (the
inserted replacement text and even some surrounding icon glyphs end up on different lines
than the original extraction, defeating the fixture's whole purpose of proving the code
handles what real extraction actually produces). Per the spec's own explicit fallback
("If regenerating a redacted PDF is not practical, skip the PDF and test from the text
fixture, and say so in the PR description"), only the `.pymupdf.txt` text fixture is
committed; there is no PDF-path (multi-engine `extract_resume_document`) integration test
here, only the text-based `build_profile` parser path.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from docx import Document as ReadDocument

from ats_engine.generation.docx_renderer import render_resume_docx
from ats_engine.kit.contract import ArtifactKind, DocumentState
from ats_engine.kit.orchestrator import generate_application_kit
from ats_engine.parsing.resume import PROFILE_CACHE_VERSION, build_profile
from ats_engine.validation.fidelity import extract_named_entities

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
REAL_TEXT_PATH = FIXTURE_ROOT / "real_extraction" / "candidate_resume.pymupdf.txt"
JD_ROOT = FIXTURE_ROOT / "synthetic_shapes"

EXPECTED_EMPLOYERS = (
    "Flosonics Medical",
    "LoopX",
    "City of Greater Sudbury",
    "Minax Inc.",
    "Mineral Exploration Research Centre",
    "Tata Consultancy Services (TCS)",
)
EXPECTED_TITLES = (
    "Business Intelligence Developer",
    "Software Development Consultant",
    "Business Intelligence Analyst",
    "Lead Software Developer",
    "Research Associate (Data & ML)",
    "Lead Software Engineer",
)
EXPECTED_DATES = (
    "Oct 2024 - Apr 2026",
    "Jun 2024 - Jul 2025",
    "May 2024 - Aug 2024",
    "Oct 2023 - May 2024",
    "Mar 2022 - Jul 2023",
    "Nov 2017 - Oct 2021",
)
DELIVERED_STATES = {DocumentState.GENERATED, DocumentState.GENERATED_WITH_FALLBACK}


def _real_extraction_text() -> str:
    return REAL_TEXT_PATH.read_text(encoding="utf-8")


def _jd_text(case: str) -> str:
    return (JD_ROOT / case / "job_description.txt").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. Employer identity -- the core regression.
# --------------------------------------------------------------------------- #
def test_real_extraction_yields_exact_employers_titles_and_dates_in_order() -> None:
    profile = build_profile(_real_extraction_text())
    assert tuple(exp.company for exp in profile.experiences) == EXPECTED_EMPLOYERS
    assert tuple(exp.title for exp in profile.experiences) == EXPECTED_TITLES
    assert tuple(exp.dates for exp in profile.experiences) == EXPECTED_DATES
    locations = {"Toronto, ON (Remote)", "Sudbury, ON", "Mumbai, India"}
    for experience in profile.experiences:
        assert experience.company not in locations, f"employer equals a location: {experience.company!r}"


def _real_extraction_kit(case: str = "coo_it_specialist"):
    return generate_application_kit(
        resume_text=_real_extraction_text(),
        job_description=_jd_text(case),
        use_llm=False,
        include_resume=True,
        include_cover_letter=True,
        include_application_answers=False,
        include_job_fit=False,
        include_interview_prep=False,
        include_linkedin_outreach=False,
    )


# --------------------------------------------------------------------------- #
# 2. Location captured, not discarded -- into the profile AND every rendered form.
# --------------------------------------------------------------------------- #
def test_location_survives_into_document_latex_and_docx() -> None:
    profile = build_profile(_real_extraction_text())
    first = profile.experiences[0]
    assert first.company == "Flosonics Medical"
    assert "Toronto, ON" in first.location
    assert "(Remote)" in first.location

    kit = _real_extraction_kit()
    assert kit.resume is not None and kit.resume.document is not None
    assert "Toronto, ON" in kit.resume.text
    assert "(Remote)" in kit.resume.text
    assert "Toronto" in kit.resume.latex

    docx_bytes = render_resume_docx(kit.resume.document, "classic")
    docx_text = "\n".join(p.text for p in ReadDocument(BytesIO(docx_bytes)).paragraphs)
    assert "Toronto, ON" in docx_text
    assert "(Remote)" in docx_text


# --------------------------------------------------------------------------- #
# 3. Metric retention -- the wrapped-bullet-continuation regression.
# --------------------------------------------------------------------------- #
def test_100_percent_metric_survives_in_tcs_bullet_and_rendered_document() -> None:
    profile = build_profile(_real_extraction_text())
    tcs = next(exp for exp in profile.experiences if exp.company == "Tata Consultancy Services (TCS)")
    assert any("100%" in bullet and "uptime" in bullet for bullet in tcs.bullets)

    kit = _real_extraction_kit()
    assert kit.resume is not None
    assert "100%" in kit.resume.text


@pytest.mark.parametrize("case", ("coo_it_specialist", "claimsecure_it_admin"))
def test_missing_100_percent_metric_finding_never_appears(case: str) -> None:
    kit = generate_application_kit(
        resume_text=_real_extraction_text(),
        job_description=_jd_text(case),
        use_llm=False,
        include_resume=True,
        include_cover_letter=True,
        include_application_answers=False,
        include_job_fit=False,
        include_interview_prep=False,
        include_linkedin_outreach=False,
    )
    assert kit.resume is not None
    for error in kit.resume.validation.errors:
        assert "missing source metric: 100%" not in error, error
    assert kit.validation is not None
    for error in kit.validation.errors:
        assert "missing source metric: 100%" not in error, error


# --------------------------------------------------------------------------- #
# 4 & 5. Delivery invariant on the real input, both job descriptions.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("case", ("coo_it_specialist", "claimsecure_it_admin"))
def test_real_extraction_delivers_a_complete_kit_with_monotone_ats_v2_score(case: str) -> None:
    kit = generate_application_kit(
        resume_text=_real_extraction_text(),
        job_description=_jd_text(case),
        use_llm=False,
        include_resume=True,
        include_cover_letter=True,
        include_application_answers=False,
        include_job_fit=False,
        include_interview_prep=False,
        include_linkedin_outreach=False,
    )
    assert kit.resume is not None and kit.resume.text
    assert kit.cover_letter is not None and kit.cover_letter.text
    assert kit.delivery_reports[ArtifactKind.RESUME].state in DELIVERED_STATES
    assert kit.match_report is not None
    assert kit.match_report.original_ats_match is not None
    assert kit.match_report.tailored_ats_match is not None
    assert kit.match_report.tailored_ats_match.score >= kit.match_report.original_ats_match.score
    for employer in EXPECTED_EMPLOYERS:
        assert employer in kit.resume.text


# --------------------------------------------------------------------------- #
# 6. Wrap-repair correctness.
# --------------------------------------------------------------------------- #
def test_hyphen_and_glued_word_artifacts_do_not_survive_into_the_rendered_resume() -> None:
    from ats_engine.parsing.document_extraction import _repair_hyphen_wraps, normalize_extracted_text

    normalized = normalize_extracted_text(_repair_hyphen_wraps(_real_extraction_text()))
    kit = generate_application_kit(
        resume_text=normalized,
        job_description=_jd_text("coo_it_specialist"),
        use_llm=False,
        include_resume=True,
        include_cover_letter=False,
        include_application_answers=False,
        include_job_fit=False,
        include_interview_prep=False,
        include_linkedin_outreach=False,
    )
    assert kit.resume is not None
    text = kit.resume.text

    for artifact in ("Zoom-Info", "stake-holders", "specifi-cations", "opera-tional", "non- technical"):
        assert artifact not in text, f"unrepaired artifact survived: {artifact!r}"

    assert "ZoomInfo" in text
    assert extract_named_entities("Salesforce, HubSpot, ZoomInfo, and Lead Forensics") == (
        "HubSpot",
        "ZoomInfo",
        "Lead Forensics",
    )


# --------------------------------------------------------------------------- #
# 7. Glued-word allowlist and named transforms.
# --------------------------------------------------------------------------- #
_ALLOWLISTED_TOKENS = (
    "PostgreSQL",
    "JavaScript",
    "PowerShell",
    "ArcGIS",
    "SharePoint",
    "GitHub",
    "DevOps",
    "MySQL",
    "SQLite",
    "IoT",
    "iOS",
)


@pytest.mark.parametrize("token", _ALLOWLISTED_TOKENS)
def test_allowlisted_single_tokens_round_trip_unchanged(token: str) -> None:
    from ats_engine.parsing.document_extraction import _repair_glued_skill_words

    line = f"Skills: {token}, Python, SQL"
    assert token in _repair_glued_skill_words(line)


def test_named_glued_word_transforms() -> None:
    from ats_engine.parsing.document_extraction import _repair_glued_skill_words

    fixed = _repair_glued_skill_words(
        "Databases&DataEngineering: PostgreSQL,MSSQLServer, ETL/ELTPipelines, DataWarehousing, DataModeling"
    )
    assert "Databases & Data Engineering" in fixed
    assert "MS SQL Server" in fixed
    assert "ETL/ELT Pipelines" in fixed
    assert "Data Warehousing" in fixed
    assert "Data Modeling" in fixed


def test_bulleted_glued_label_is_fixed_without_touching_the_rest_of_the_bullet() -> None:
    from ats_engine.parsing.document_extraction import _repair_glued_skill_words

    fixed = _repair_glued_skill_words("• BI&DataGovernance: BuiltService-BasedBudgetingsystems standards")
    assert fixed.startswith("• BI & Data Governance:")
    assert "BuiltService-BasedBudgetingsystems standards" in fixed


# --------------------------------------------------------------------------- #
# 8. Header-shape corpus: the employer must never equal a location.
# --------------------------------------------------------------------------- #
_HEADER_SHAPE_CASES = {
    "four_line": (
        "Cedar Ridge Systems\nToronto, ON (Remote)\nSoftware Engineer\nJanuary 2020 - December 2021\n"
        "- Built dashboards.\n"
    ),
    "three_line_no_location": (
        "Cedar Ridge Systems\nSoftware Engineer\nJanuary 2020 - December 2021\n- Built dashboards.\n"
    ),
    "pipe_form": (
        "Cedar Ridge Systems | Toronto, ON\nSoftware Engineer\nJanuary 2020 - December 2021\n- Built dashboards.\n"
    ),
    "comma_one_liner": ("Cedar Ridge Systems, Toronto, ON\nJanuary 2020 - December 2021\n- Built dashboards.\n"),
    "title_city_st": (
        "Cedar Ridge Systems\nSoftware Engineer, Toronto, ON\nJanuary 2020 - December 2021\n- Built dashboards.\n"
    ),
    "bare_remote": (
        "Cedar Ridge Systems\nRemote\nSoftware Engineer\nJanuary 2020 - December 2021\n- Built dashboards.\n"
    ),
    "no_location_at_all": (
        "Cedar Ridge Systems\nSoftware Engineer\nJanuary 2020 - December 2021\n- Built dashboards.\n"
    ),
}


@pytest.mark.parametrize("shape", sorted(_HEADER_SHAPE_CASES))
def test_header_shape_corpus_never_assigns_a_location_as_the_employer(shape: str) -> None:
    resume_text = "Alex Morgan\nalex@example.test\nPROFESSIONAL EXPERIENCE\n" + _HEADER_SHAPE_CASES[shape]
    profile = build_profile(resume_text)
    assert profile.experiences, f"no experience entry parsed for shape {shape!r}"
    entry = profile.experiences[0]
    assert entry.company == "Cedar Ridge Systems", f"shape {shape!r}: company={entry.company!r}"
    assert entry.company not in {"Toronto, ON", "Toronto, ON (Remote)", "Remote"}


# --------------------------------------------------------------------------- #
# 10. Cache-version guard.
# --------------------------------------------------------------------------- #
def test_profile_cache_version_was_bumped_for_this_parser_change() -> None:
    assert PROFILE_CACHE_VERSION != "profile-v7-provider-source-floor"
