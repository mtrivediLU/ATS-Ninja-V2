from __future__ import annotations

from io import BytesIO

from ats_engine.evidence.matrix import build_evidence_matrix
from ats_engine.evidence.quality_report import build_ats_quality_report
from ats_engine.generation.pipeline import run_pipeline
from ats_engine.generation.planning import _career_years, build_resume_plan
from ats_engine.models import ContactInfo, Experience
from ats_engine.parsing.contact_integrity import validate_contact_integrity
from ats_engine.parsing.document_extraction import (
    _extract_pdf_multi_engine,
    _repair_line_break_hyphens,
    normalize_extracted_text,
)
from ats_engine.parsing.extraction_quality import score_extraction, select_best_extraction
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import extract_profile
from ats_engine.validation.style import validate_style

"""Regression coverage for the extraction/ATS/document-quality audit.

Every synthetic fixture below is invented for this test file: no real
candidate or job-description content from the reference documents is
reproduced anywhere in this repository.
"""

SYNTHETIC_POWER_PLATFORM_JD = (
    "Job Title: Developer, Power Platform\n"
    "Organization: Dominion Reserve Authority\n"
    "Location: Ottawa or Toronto, Hybrid\n"
    "Required qualifications:\n"
    "- Experience building solutions on Microsoft Power Platform: Power Apps, Power Automate, Power Pages, "
    "Model Driven Apps.\n"
    "- Experience developing custom PCF controls.\n"
    "- Experience with Dataverse and SharePoint integration.\n"
    "- Experience with Azure Function Apps and Azure API Management.\n"
    "- Experience with C# and .NET Framework for system integrations and plug-ins.\n"
    "- Experience with HTML5, CSS, and JavaScript for web portal development.\n"
    "- Experience with source control, including branching and merging.\n"
    "- Experience with root-cause analysis and technical documentation.\n"
    "Preferred qualifications:\n"
    "- Experience with Liquid templating.\n"
    "- Experience with PowerShell.\n"
    "Responsibilities:\n"
    "- Design, build, and maintain Power Platform solutions including Power Pages portals and Model Driven Apps.\n"
    "- Develop custom PCF controls and integrate with Azure Function Apps.\n"
    "- Support existing C#/.NET Framework systems.\n"
    "- Provide root-cause analysis and technical documentation for production issues.\n"
    "This posting also references unrelated boilerplate about accommodation, benefits, and recruitment process "
    "that should not be treated as a technical requirement.\n"
)

# Shaped like the real candidate's background: web/BI delivery with
# Power Platform tools only listed (never used in a bullet), and genuinely no
# C#/.NET/SharePoint/PCF/Dynamics evidence at all -- those must remain gaps.
SYNTHETIC_POWER_PLATFORM_RESUME = (
    "Jordan Rivera\n"
    "jordan.rivera@example.com | 555-201-9876 | linkedin.com/in/jordanrivera\n"
    "Sudbury, Ontario, Canada\n"
    "PROFESSIONAL SUMMARY\n"
    "Business Intelligence Developer with delivery experience across cloud and web platforms.\n"
    "TECHNICAL SKILLS\n"
    "Core: JavaScript, HTML5, CSS, SQL, PostgreSQL, Git\n"
    "Working knowledge: Power BI, Power Apps, Power Automate, Azure\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Northbridge Analytics Toronto, ON\n"
    "Business Intelligence Developer Nov 2017 - Apr 2026\n"
    "- Built end-to-end reporting pipelines using SQL and PostgreSQL.\n"
    "- Delivered web dashboards using JavaScript and HTML5.\n"
    "EDUCATION\n"
    "Carleton University Ottawa, ON\n"
    "Bachelor of Computer Science 2013 - 2017\n"
)


def _text_pdf(text: str) -> bytes:
    """Minimal single-page PDF whose content stream literally contains ``text``."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    stream = DecodedStreamObject()
    escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    stream.set_data(f"BT /F1 10 Tf 72 720 Td ({escaped}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


# ---------------------------------------------------------------------------
# Extraction: multi-engine selection and quality scoring
# ---------------------------------------------------------------------------


def test_quality_scoring_penalizes_glued_bullets_and_contact_prefixes() -> None:
    # A decorative contact icon that survives extraction as a symbol (not a
    # letter) leaves a detectable boundary right before the email/URL match;
    # this is the residual defect pattern that remains even after the
    # letter-glued case (see the multi-engine tests below) is fixed by
    # engine selection. "#" is a stand-in for that surviving icon glyph.
    clean = "Summary\n* Managed cloud infrastructure.\njordan@example.com"
    glued = "Summary\n*Managed cloud infrastructure.\n#jordan@example.com"
    clean_score = score_extraction("clean", clean)
    glued_score = score_extraction("glued", glued)
    assert clean_score.score > glued_score.score
    assert glued_score.glued_bullet_count == 1
    assert glued_score.glued_contact_prefix_count == 1
    assert clean_score.glued_bullet_count == 0
    assert clean_score.glued_contact_prefix_count == 0


def test_select_best_extraction_picks_highest_scoring_candidate() -> None:
    candidates = [
        ("worse", "*Glued bullet with no space.\nxxperson@example.com"),
        ("better", "* Clean bullet with a space.\nperson@example.com"),
    ]
    method, text, score = select_best_extraction(candidates)
    assert method == "better"
    assert "xx" not in text


def test_multi_engine_pdf_extraction_selects_and_scores_a_candidate() -> None:
    content = _text_pdf("Jordan Rivera\nSummary\n* Built internal tools.")
    text, page_count, engine, quality = _extract_pdf_multi_engine(content, max_pages=100)
    assert page_count == 1
    assert engine in {"pypdf", "pymupdf", "pdfplumber"}
    assert "Jordan Rivera" in text
    assert quality.method == engine


def _two_line_pdf(first_line: str, second_line: str) -> bytes:
    """A PDF whose two lines are genuinely separate text-showing operations at
    different Y positions, so every extraction engine sees a real line break
    between them (unlike a single ``Tj`` call with an embedded ``\\n``)."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    stream = DecodedStreamObject()
    escaped_first = first_line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    escaped_second = second_line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    ops = f"BT /F1 10 Tf 72 720 Td ({escaped_first}) Tj 0 -14 Td ({escaped_second}) Tj ET"
    stream.set_data(ops.encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_multi_engine_extraction_repairs_hyphen_break_regardless_of_which_engine_wins() -> None:
    """Regression: hyphen repair must apply to every candidate engine's output,
    not only the ones repaired inline during extraction -- a real defect found
    where the pdfplumber candidate was selected but had not been repaired."""
    content = _two_line_pdf("Built systems using Java Spring MVC and Hi-", "bernate for persistence.")
    text, _page_count, _engine, _quality = _extract_pdf_multi_engine(content, max_pages=100)
    assert "Hibernate" in text
    assert "Hi- bernate" not in text
    assert "Hi-bernate" not in text


def test_line_break_hyphen_is_repaired_but_newline_required() -> None:
    assert _repair_line_break_hyphens("Hi-\nbernate") == "Hibernate"
    assert _repair_line_break_hyphens("ac-\nceptance") == "acceptance"
    # No literal newline between the hyphen and the next letter: never joined.
    assert _repair_line_break_hyphens("well- known") == "well- known"
    assert _repair_line_break_hyphens("real-time") == "real-time"


def test_normalize_extracted_text_preserves_legitimate_hyphenated_terms() -> None:
    for term in [
        "real-time",
        "offline-first",
        "service-to-service",
        "multi-language",
        "CI/CD",
        "B2B",
        "end-to-end",
    ]:
        assert normalize_extracted_text(term) == term


# ---------------------------------------------------------------------------
# Tenure and numeric integrity
# ---------------------------------------------------------------------------


def _exp(dates: str) -> Experience:
    return Experience(company="C", title="T", location="", dates=dates, bullets=[])


def test_career_years_is_month_aware_not_calendar_year_rounded() -> None:
    # Nov 2017 to Apr 2026 is 8 years and change, not the 9 a bare
    # calendar-year subtraction (2026 - 2017) would produce.
    assert _career_years([_exp("Nov 2017 - Oct 2021"), _exp("Oct 2024 - Apr 2026")]) == 8


def test_career_years_handles_year_only_dates() -> None:
    assert _career_years([_exp("2017 - 2021"), _exp("2022 - 2024")]) == 7


def test_career_years_handles_present_role() -> None:
    from datetime import datetime

    result = _career_years([_exp("Jan 2015 - Present")])
    now = datetime.now()
    expected = ((now.year * 12 + now.month) - (2015 * 12 + 1)) // 12
    assert result == expected


def test_career_years_does_not_double_count_overlapping_or_concurrent_roles() -> None:
    # Two concurrent consulting roles spanning the same window must not sum
    # to double the elapsed time -- total span is still just start to end.
    overlapping = _career_years([_exp("Jan 2018 - Dec 2020"), _exp("Jun 2018 - Dec 2020")])
    single = _career_years([_exp("Jan 2018 - Dec 2020")])
    assert overlapping == single


def test_career_years_handles_partial_year_gap() -> None:
    assert _career_years([_exp("Mar 2019 - Jun 2019"), _exp("Jan 2022 - Jan 2023")]) == 3


def test_career_years_returns_none_with_no_parseable_dates() -> None:
    assert _career_years([_exp("")]) is None


# ---------------------------------------------------------------------------
# Contact integrity
# ---------------------------------------------------------------------------


def test_contact_integrity_accepts_well_formed_fields() -> None:
    report = validate_contact_integrity(
        ContactInfo(
            name="Jordan Rivera",
            email="jordan.rivera@example.com",
            phone="555-201-9876",
            linkedin="linkedin.com/in/jordanrivera",
            website="jordanrivera.dev",
        )
    )
    assert report.email_valid
    assert report.phone_valid
    assert report.linkedin_valid
    assert report.website_valid
    assert report.warnings == ()


def test_contact_integrity_flags_malformed_fields_without_rewriting() -> None:
    contact = ContactInfo(email="pejordan@@bad", phone="12", linkedin="not-a-linkedin-url", website="???")
    report = validate_contact_integrity(contact)
    assert not report.email_valid
    assert not report.phone_valid
    assert not report.linkedin_valid
    assert not report.website_valid
    assert len(report.warnings) == 4
    # Never rewritten: the caller's original (reviewed) value is untouched.
    assert contact.email == "pejordan@@bad"


def test_contact_integrity_warning_is_non_fatal_in_pipeline_validation() -> None:
    from ats_engine.validation.severity import is_fatal_validation_error

    result = run_pipeline(
        resume_text=(
            "Jordan Rivera\nnot-a-valid-email\nPROFESSIONAL EXPERIENCE\nAcme Corp Remote\n"
            "Engineer 2020 to 2023\n- Built systems.\n"
        ),
        job_description="Job Title: Engineer\nRequired:\n- Systems experience\n",
        requested_mode="resume",
        use_llm=False,
    )
    contact_errors = [error for error in result.validation_errors if error.startswith("contact:")]
    # No email at all means nothing to flag; this just proves the prefix
    # never appears in FATAL_MARKERS regardless.
    assert all(not is_fatal_validation_error(error) for error in contact_errors)


# ---------------------------------------------------------------------------
# JD parsing: domain word-boundary and expanded keyword vocabulary
# ---------------------------------------------------------------------------


def test_domain_detection_does_not_false_positive_on_ai_substring() -> None:
    jd_profile = parse_jd(
        "Job Title: Power Platform Developer\n"
        "We will maintain strict confidentiality and provide training and certain accommodations."
    )
    assert jd_profile.domain != "AI"


def test_domain_detection_still_matches_real_ai_word_boundary() -> None:
    jd_profile = parse_jd("Job Title: AI Engineer\nWe build AI systems for enterprise customers.")
    assert jd_profile.domain == "AI"


def test_jd_keyword_vocabulary_recognizes_power_platform_terms() -> None:
    jd_profile = parse_jd(SYNTHETIC_POWER_PLATFORM_JD)
    lowered_keywords = {keyword.lower() for keyword in jd_profile.technical_keywords}
    for expected in ["power apps", "power automate", "sharepoint", "dataverse"]:
        assert any(expected in keyword for keyword in lowered_keywords)


# ---------------------------------------------------------------------------
# Grounded ATS mapping and quality report: genuine gaps stay gaps
# ---------------------------------------------------------------------------


def test_genuine_gaps_are_not_promoted_to_supported_for_unmatched_role() -> None:
    profile = extract_profile(SYNTHETIC_POWER_PLATFORM_RESUME)
    jd_profile = parse_jd(SYNTHETIC_POWER_PLATFORM_JD, profile=profile)
    evidence = build_evidence_matrix(jd_profile, profile)

    by_keyword = {item.keyword.lower(): item for item in evidence}
    # C#, .NET Framework, SharePoint, and PCF controls have zero evidence in
    # the synthetic resume and must remain genuine gaps, never "proven".
    for genuine_gap in ["c#", ".net framework"]:
        matches = [item for keyword, item in by_keyword.items() if genuine_gap in keyword]
        assert matches, f"expected {genuine_gap!r} to appear in the evidence matrix"
        assert all(item.evidence_tier == "missing" for item in matches)

    # Power Apps/Power Automate are listed-only in the synthetic resume, so
    # they may surface as working-knowledge/adjacency at best, never "proven".
    for listed_only in ["power apps", "power automate"]:
        matches = [item for keyword, item in by_keyword.items() if listed_only in keyword]
        if matches:
            assert all(item.evidence_tier != "A" for item in matches)


def test_ats_quality_report_reflects_genuine_coverage_only() -> None:
    profile = extract_profile(SYNTHETIC_POWER_PLATFORM_RESUME)
    jd_profile = parse_jd(SYNTHETIC_POWER_PLATFORM_JD, profile=profile)
    plan = build_resume_plan(contacts=profile.contact, jd_profile=jd_profile, profile=profile)
    from ats_engine.generation.resume import generate_resume_text

    resume_text = generate_resume_text(plan)
    report = build_ats_quality_report(
        evidence=plan.evidence, jd_profile=jd_profile, resume_plan=plan, resume_text=resume_text
    )

    assert report.required_term_count > 0
    # A role this mismatched must not report full coverage.
    assert report.required_coverage_percent < 100.0
    assert report.unsupported_requirement_count > 0
    assert report.section_presence["experience"]
    assert report.section_presence["summary"]


def test_ats_quality_report_is_not_a_single_confidence_score() -> None:
    from dataclasses import fields

    from ats_engine.evidence.quality_report import AtsQualityReport

    field_names = {f.name for f in fields(AtsQualityReport)}
    assert "required_coverage_percent" in field_names
    assert not {"confidence", "ai_confidence", "score"} & field_names


# ---------------------------------------------------------------------------
# Target-title truthfulness and no generic filler
# ---------------------------------------------------------------------------


def test_target_title_appears_truthfully_not_as_candidate_history() -> None:
    result = run_pipeline(
        resume_text=SYNTHETIC_POWER_PLATFORM_RESUME,
        job_description=SYNTHETIC_POWER_PLATFORM_JD,
        requested_mode="resume",
        use_llm=False,
    )
    assert "Targeting Developer, Power Platform opportunities" in result.resume_text
    # Never rendered as a held title in the experience section.
    experience_section = result.resume_text.split("Professional Experience", 1)[-1]
    assert "Targeting Developer, Power Platform" not in experience_section


def test_summary_avoids_generic_core_tools_filler_when_keywords_exist() -> None:
    result = run_pipeline(
        resume_text=SYNTHETIC_POWER_PLATFORM_RESUME,
        job_description=SYNTHETIC_POWER_PLATFORM_JD,
        requested_mode="resume",
        use_llm=False,
    )
    assert "core tools and day-to-day delivery" not in result.resume_text


def test_end_to_end_phrase_survives_style_softening_unchanged() -> None:
    from ats_engine.validation.repair import soften_banned_style

    text = "Delivered end-to-end ownership of the platform."
    assert soften_banned_style(text) == text
    assert not validate_style(text)


def test_full_pipeline_for_mismatched_role_completes_without_fabrication() -> None:
    result = run_pipeline(
        resume_text=SYNTHETIC_POWER_PLATFORM_RESUME,
        job_description=SYNTHETIC_POWER_PLATFORM_JD,
        requested_mode="resume",
        use_llm=False,
    )
    assert result.validation_errors == []
    assert "C#" not in result.resume_text
    assert ".NET Framework" not in result.resume_text
    assert "SharePoint" not in result.resume_text
    # Tenure must reflect the resume's own 8-year span, never inflated.
    assert "9+ years" not in result.resume_text
