from __future__ import annotations

import pytest

from ats_engine.evidence.matrix import build_evidence_matrix, classify_requirement_category
from ats_engine.evidence.quality_report import build_ats_quality_report
from ats_engine.generation.filenames import build_export_filename, sanitize_filename_component
from ats_engine.generation.html_renderer import (
    render_cover_letter_html,
    render_plain_text_html,
    render_resume_html,
)
from ats_engine.generation.planning import build_resume_plan
from ats_engine.kit import generate_application_kit
from ats_engine.kit.contract import (
    CoverLetterDocument,
    ResumeCertificationEntry,
    ResumeDocument,
    ResumeEducationEntry,
    ResumeExperienceEntry,
    ResumeSkillGroup,
)
from ats_engine.models import JDProfile
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import extract_profile

"""Coverage for grounded ATS tailoring (JD segmentation, typed requirement
categories, skill-group prioritization, quality-report warnings) and the
local PDF-download architecture (filenames, HTML rendering). Every fixture
below is invented for this test file: no real candidate or job-description
content is reproduced.
"""

# Deliberately shaped like the real reference posting's structural quirks:
# a metadata-label preamble before the title, a D&I/accommodation section, a
# company name repeated with and without a leading article, a
# "What you will do" section whose bullets mention "business requirements"
# mid-sentence (a trap for heading detection), a "What you need to succeed" /
# "In addition, you have:" required-qualifications pair, a hyphenated
# "Nice-to-have" heading, and a compensation/benefits closing section.
BOILERPLATE_STYLE_JD = (
    "Requisition Number:  88214\n"
    "Position Type:  Permanent\n"
    "Location:  Remote\n"
    "Developer, Automation Platform\n"
    "\n"
    "Equity, Diversity & Inclusion\n"
    "The Company is committed to accommodation for every applicant who chooses to self-identify.\n"
    "\n"
    "About the role\n"
    "The Northwind Company has a mission to modernize how teams work. The Northwind Company builds tools "
    "used by thousands of customers across many industries and regions.\n"
    "\n"
    "What you will do\n"
    "As a Developer, you will support the automation platform used across the company.\n"
    "More specifically, you will:\n"
    "- Analyze, design and implement enhancements to meet business requirements.\n"
    "- Perform technical and root-cause analysis on issues and make recommendations for correction.\n"
    "- Maintain technical documentation for delivered solutions.\n"
    "\n"
    "What you need to succeed\n"
    "You have strong attention to detail and the ability to prioritize multiple tasks.\n"
    "In addition, you have:\n"
    "- Proven experience with C# programming language and .NET Framework.\n"
    "- Experience developing and maintaining HTML5, CSS, JavaScript web applications.\n"
    "- Experience and understanding of source control systems, including advanced branching and merging.\n"
    "\n"
    "Nice-to-have\n"
    "- Experience in writing programming scripts using PowerShell.\n"
    "\n"
    "What you need to know\n"
    "Security level required: be eligible to obtain Secret.\n"
    "\n"
    "What you can expect from us\n"
    "Salaries typically range from $80,000 to $95,000. The Company offers a defined-benefit pension plan and "
    "extra vacation days.\n"
    "We wish to thank all applicants for their interest in this opportunity.\n"
)


def _matrix(**overrides: object) -> list[object]:
    from ats_engine.parsing.resume import empty_profile

    base = {
        "title": "Automation Developer",
        "company": "Northwind Company",
        "required_qualifications": [],
        "preferred_qualifications": [],
        "responsibilities": [],
        "technical_keywords": [],
    }
    base.update(overrides)
    return build_evidence_matrix(JDProfile(**base), empty_profile())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# JD segmentation
# ---------------------------------------------------------------------------


def test_hyphenated_nice_to_have_heading_is_recognized_as_preferred() -> None:
    jd = parse_jd(BOILERPLATE_STYLE_JD)
    assert any("powershell" in line.lower() for line in jd.preferred_qualifications)
    assert not any("powershell" in line.lower() for line in jd.required_qualifications)


def test_what_you_need_to_succeed_heading_is_recognized_as_required() -> None:
    jd = parse_jd(BOILERPLATE_STYLE_JD)
    required_text = " ".join(jd.required_qualifications).lower()
    assert "c#" in required_text
    assert ".net framework" in required_text
    assert "branching and merging" in required_text


def test_mid_sentence_requirements_word_does_not_swallow_responsibilities() -> None:
    jd = parse_jd(BOILERPLATE_STYLE_JD)
    required_text = " ".join(jd.required_qualifications).lower()
    responsibilities_text = " ".join(jd.responsibilities).lower()
    # "...to meet business requirements" must never be mistaken for a
    # "Requirements:" heading and pull every later responsibility bullet
    # (root-cause analysis, technical documentation) into required.
    assert "root-cause" not in required_text
    assert "root-cause" in responsibilities_text


def test_title_extraction_skips_leading_metadata_lines() -> None:
    jd = parse_jd(BOILERPLATE_STYLE_JD)
    assert jd.title == "Developer, Automation Platform"


def test_company_name_repeated_with_and_without_article_resolves_to_clean_name() -> None:
    jd = parse_jd(BOILERPLATE_STYLE_JD)
    assert jd.company == "Northwind Company"


def test_boilerplate_terms_excluded_from_technical_keywords() -> None:
    jd = parse_jd(BOILERPLATE_STYLE_JD)
    lowered_keywords = {keyword.lower() for keyword in jd.technical_keywords}
    assert not lowered_keywords & {"diversity", "accommodation", "pension", "vacation", "northwind", "company"}


def test_organizational_boilerplate_segment_captures_di_and_recruitment_copy() -> None:
    jd = parse_jd(BOILERPLATE_STYLE_JD)
    boilerplate_text = " ".join(jd.organizational_boilerplate).lower()
    assert "accommodation" in boilerplate_text or "diversity" in boilerplate_text


def test_compensation_benefits_segment_is_separated_from_requirements() -> None:
    jd = parse_jd(BOILERPLATE_STYLE_JD)
    compensation_text = " ".join(jd.compensation_benefits).lower()
    assert "pension" in compensation_text or "salaries" in compensation_text
    assert "pension" not in " ".join(jd.required_qualifications).lower()


# ---------------------------------------------------------------------------
# Regression: a required gap keyword spelled with an internal period
# (".NET Framework") and one whose own name contains a generic strength
# word ("user experience" contains "experience") must never cause the
# deterministic, honest JobFit/InterviewPrep/Outreach narrative to be
# mistaken for over-claiming and withheld. Found via a real end-to-end run
# against a Power-Platform-style posting; root cause was two bugs in the
# job_fit/interview_prep/linkedin_outreach validators' clause-matching
# helpers, not in generation.
# ---------------------------------------------------------------------------

GAP_TRAP_JD = (
    "Job Title: Platform Developer\n"
    "Company: Fieldstone Digital Client\n"
    "Required qualifications:\n"
    "- Experience and understanding of source control systems, including advanced branching and merging.\n"
    "- Experience working with business analysts or user experience designers.\n"
    "- Proven experience with C# programming language and .NET Framework.\n"
)

GAP_TRAP_RESUME = (
    "Riley Chen\n"
    "riley.chen@example.com | 555-402-1188 | linkedin.com/in/rileychen\n"
    "Ottawa, Ontario, Canada\n"
    "PROFESSIONAL SUMMARY\n"
    "Platform developer with hands-on delivery experience.\n"
    "TECHNICAL SKILLS\n"
    "Core: Power Automate, JavaScript, HTML5, CSS, PostgreSQL\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Fieldstone Digital Ottawa, ON\n"
    "Platform Developer Jan 2020 - Present\n"
    "- Built automated workflows using Power Automate to replace manual approval processes.\n"
    "- Delivered customer-facing web portals using JavaScript, HTML5, and CSS.\n"
    "EDUCATION\n"
    "Carleton University Ottawa, ON\n"
    "Bachelor of Computer Science 2016 - 2020\n"
)


def test_gap_keyword_with_internal_period_and_self_colliding_name_does_not_withhold_job_fit_or_interview_prep() -> None:
    kit = generate_application_kit(
        resume_text=GAP_TRAP_RESUME,
        job_description=GAP_TRAP_JD,
        default_mode=None,
        include_resume=True,
        include_cover_letter=False,
        include_application_answers=False,
        use_llm=False,
        include_job_fit=True,
        include_interview_prep=True,
        include_linkedin_outreach=True,
    )
    assert kit.job_fit is not None
    assert kit.job_fit.validation.fatal is False, kit.job_fit.validation.errors
    assert kit.interview_prep is not None
    assert kit.interview_prep.validation.fatal is False, kit.interview_prep.validation.errors
    assert kit.linkedin_outreach is not None
    assert kit.linkedin_outreach.validation.fatal is False, kit.linkedin_outreach.validation.errors

    genuine_gaps = {
        item.requirement.lower() for item in kit.job_fit.requirements if item.classification.value == "genuine_gap"
    }
    # ".net" (period-containing) and "user experience" (self-colliding with
    # the generic word "experience") are exactly the two trap shapes; both
    # must still land as honest genuine gaps, not silently disappear.
    assert ".net" in genuine_gaps
    assert "user experience" in genuine_gaps


# ---------------------------------------------------------------------------
# Typed requirement categories
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("keyword", "expected_category"),
    [
        ("power apps", "platform"),
        ("power platform", "platform"),
        ("c#", "programming language"),
        ("python", "programming language"),
        ("azure", "cloud"),
        ("kubernetes", "cloud"),
        ("postgresql", "database"),
        ("dynamics 365", "database"),
        ("html5", "web development"),
        ("git", "source control"),
        ("source control systems", "source control"),
        ("business requirements", "business analysis"),
        ("user experience", "business analysis"),
        ("root-cause analysis", "operations and support"),
        ("technical documentation", "documentation"),
        ("communicate effectively", "communication"),
        ("totally-unrecognized-xyz-tool", "other"),
    ],
)
def test_classify_requirement_category_maps_known_keywords(keyword: str, expected_category: str) -> None:
    assert classify_requirement_category(keyword) == expected_category


def test_evidence_matrix_items_carry_a_category() -> None:
    matrix = _matrix(
        required_qualifications=["Experience with Power Automate and business requirements gathering."],
        technical_keywords=["power automate", "business requirements"],
    )
    categories = {item.keyword: item.category for item in matrix}
    assert categories["power automate"] == "platform"
    assert categories["business requirements"] == "business analysis"


# ---------------------------------------------------------------------------
# Responsibilities as a primary tailoring input
# ---------------------------------------------------------------------------


def test_responsibility_only_keyword_surfaces_as_a_required_requirement() -> None:
    matrix = _matrix(
        required_qualifications=["Experience with C# and .NET Framework."],
        responsibilities=["Perform technical and root-cause analysis on production issues."],
        technical_keywords=["c#", ".net framework", "root-cause analysis"],
    )
    by_keyword = {item.keyword: item for item in matrix}
    assert by_keyword["root-cause analysis"].required_or_preferred == "required"


def test_explicit_preferred_designation_is_never_overridden_by_a_responsibilities_guess() -> None:
    # A trailing catch-all sentence that mentions both a required and a
    # preferred tool in the same breath must never promote the preferred one.
    matrix = _matrix(
        required_qualifications=["Kubernetes container orchestration experience."],
        preferred_qualifications=["Docker containerization is a bonus."],
        responsibilities=["The team uses Kubernetes and Docker across every service."],
        technical_keywords=["kubernetes", "docker"],
    )
    by_keyword = {item.keyword: item for item in matrix}
    assert by_keyword["kubernetes"].required_or_preferred == "required"
    assert by_keyword["docker"].required_or_preferred == "preferred"


# ---------------------------------------------------------------------------
# Skill-group prioritization (Phase 7)
# ---------------------------------------------------------------------------

CANDIDATE_RESUME_FOR_GROUPING = (
    "Riley Chen\n"
    "riley.chen@example.com | 555-402-1188 | linkedin.com/in/rileychen\n"
    "Ottawa, Ontario, Canada\n"
    "PROFESSIONAL SUMMARY\n"
    "Platform developer with hands-on delivery experience.\n"
    "TECHNICAL SKILLS\n"
    "Core: Power Automate, JavaScript, HTML5, CSS, PostgreSQL, Git\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Fieldstone Digital Ottawa, ON\n"
    "Platform Developer Jan 2020 - Present\n"
    "- Built automated workflows using Power Automate to replace manual approval processes.\n"
    "- Delivered customer-facing web portals using JavaScript, HTML5, and CSS.\n"
    "EDUCATION\n"
    "Carleton University Ottawa, ON\n"
    "Bachelor of Computer Science 2016 - 2020\n"
)

CANDIDATE_JD_FOR_GROUPING = (
    "Job Title: Platform Developer\n"
    "Company: Fieldstone Digital Client\n"
    "Required qualifications:\n"
    "- Experience with Power Automate and Power Platform.\n"
    "- Experience with HTML5, CSS, and JavaScript web development.\n"
    "- Experience with PostgreSQL.\n"
    "- Experience with source control systems including Git.\n"
)


def test_skill_groups_place_evidence_backed_categories_before_additional_and_working_knowledge() -> None:
    profile = extract_profile(CANDIDATE_RESUME_FOR_GROUPING)
    jd_profile = parse_jd(CANDIDATE_JD_FOR_GROUPING, profile=profile)
    plan = build_resume_plan(contacts=profile.contact, jd_profile=jd_profile, profile=profile)
    labels = [label for label, _items in plan.skill_groups]
    assert labels, "expected at least one skill group"
    # A category group backed by real JD-matched evidence (Platform &
    # Automation / Web Development) must never be ordered after the
    # catch-all "Additional Skills"/"Working Knowledge" trailing groups.
    trailing_labels = {"Additional Skills", "Working Knowledge"}
    category_labels = [label for label in labels if label not in trailing_labels]
    assert category_labels, "expected at least one evidence-backed category group"
    first_trailing_index = next((index for index, label in enumerate(labels) if label in trailing_labels), len(labels))
    last_category_index = max(labels.index(label) for label in category_labels)
    assert last_category_index < first_trailing_index


def test_skill_groups_never_drop_a_tier_a_skill() -> None:
    profile = extract_profile(CANDIDATE_RESUME_FOR_GROUPING)
    jd_profile = parse_jd(CANDIDATE_JD_FOR_GROUPING, profile=profile)
    plan = build_resume_plan(contacts=profile.contact, jd_profile=jd_profile, profile=profile)
    all_grouped_skills = {skill.lower() for _label, items in plan.skill_groups for skill in items}
    for skill in profile.tier_a.values():
        assert skill.lower() in all_grouped_skills


# ---------------------------------------------------------------------------
# ATS quality report enhancements (Phase 11)
# ---------------------------------------------------------------------------


def test_duplicate_keyword_warning_flags_one_tool_answering_two_jd_keywords() -> None:
    profile = extract_profile(CANDIDATE_RESUME_FOR_GROUPING)
    jd_profile = parse_jd(CANDIDATE_JD_FOR_GROUPING, profile=profile)
    plan = build_resume_plan(contacts=profile.contact, jd_profile=jd_profile, profile=profile)
    evidence = plan.evidence
    # Force two distinct keywords to resolve to the same real evidence text.
    evidence = list(evidence)
    from ats_engine.models import EvidenceItem

    evidence.append(
        EvidenceItem(
            keyword="power platform",
            required_or_preferred="required",
            evidence_tier="A",
            real_evidence="Power Automate",
            allowed_placement="summary, skills, supported bullets",
            strength="strong",
            planned_placement="summary, skills, experience bullet",
            category="platform",
        )
    )
    evidence.append(
        EvidenceItem(
            keyword="power automate",
            required_or_preferred="required",
            evidence_tier="A",
            real_evidence="Power Automate",
            allowed_placement="summary, skills, supported bullets",
            strength="strong",
            planned_placement="summary, skills, experience bullet",
            category="platform",
        )
    )
    report = build_ats_quality_report(
        evidence=evidence, jd_profile=jd_profile, resume_plan=plan, resume_text="Power Automate Power Automate"
    )
    assert any("power automate" in warning.lower() for warning in report.duplicate_keyword_warnings)


def test_generic_language_warning_detects_banned_filler() -> None:
    profile = extract_profile(CANDIDATE_RESUME_FOR_GROUPING)
    jd_profile = parse_jd(CANDIDATE_JD_FOR_GROUPING, profile=profile)
    plan = build_resume_plan(contacts=profile.contact, jd_profile=jd_profile, profile=profile)
    report = build_ats_quality_report(
        evidence=plan.evidence,
        jd_profile=jd_profile,
        resume_plan=plan,
        resume_text="Leveraged core tools to deliver results-driven outcomes.",
    )
    assert "leveraged" in report.generic_language_warnings
    assert "core tools" in report.generic_language_warnings


def test_generic_language_warnings_empty_for_clean_text() -> None:
    profile = extract_profile(CANDIDATE_RESUME_FOR_GROUPING)
    jd_profile = parse_jd(CANDIDATE_JD_FOR_GROUPING, profile=profile)
    plan = build_resume_plan(contacts=profile.contact, jd_profile=jd_profile, profile=profile)
    report = build_ats_quality_report(
        evidence=plan.evidence, jd_profile=jd_profile, resume_plan=plan, resume_text="Built automated workflows."
    )
    assert report.generic_language_warnings == ()


def test_target_title_presence_checks_summary_not_only_headline() -> None:
    profile = extract_profile(CANDIDATE_RESUME_FOR_GROUPING)
    jd_profile = parse_jd(CANDIDATE_JD_FOR_GROUPING, profile=profile)
    plan = build_resume_plan(contacts=profile.contact, jd_profile=jd_profile, profile=profile)
    assert jd_profile.title.lower() in plan.summary.lower()
    report = build_ats_quality_report(
        evidence=plan.evidence, jd_profile=jd_profile, resume_plan=plan, resume_text=plan.summary
    )
    assert report.exact_target_title_present is True


# ---------------------------------------------------------------------------
# Standardized filenames (Phase 14)
# ---------------------------------------------------------------------------


def test_filename_includes_applicant_role_and_company() -> None:
    name = build_export_filename(
        candidate_name="Jordan Rivera",
        job_title="Developer, Power Platform",
        company_name="Dominion Reserve Authority",
        artifact_type="resume",
    )
    assert name == "Jordan_Rivera_Developer_Power_Platform_Dominion_Reserve_Authority_Resume.pdf"


def test_filename_cover_letter_suffix() -> None:
    name = build_export_filename(
        candidate_name="Jordan Rivera",
        job_title="Developer, Power Platform",
        company_name="Dominion Reserve Authority",
        artifact_type="cover_letter",
    )
    assert name.endswith("_Cover_Letter.pdf")


def test_filename_classic_and_modern_suffix() -> None:
    classic = build_export_filename(
        candidate_name="Ada Lovelace",
        job_title="Engineer",
        company_name="Acme",
        artifact_type="resume",
        template_id="classic",
    )
    modern = build_export_filename(
        candidate_name="Ada Lovelace",
        job_title="Engineer",
        company_name="Acme",
        artifact_type="resume",
        template_id="modern",
    )
    assert classic.endswith("_Resume_Classic.pdf")
    assert modern.endswith("_Resume_Modern.pdf")


def test_filename_missing_company_omits_segment_without_guessing() -> None:
    name = build_export_filename(
        candidate_name="Ada Lovelace", job_title="Engineer", company_name="", artifact_type="resume"
    )
    assert name == "Ada_Lovelace_Engineer_Resume.pdf"


def test_filename_missing_role_omits_segment_without_guessing() -> None:
    name = build_export_filename(
        candidate_name="Ada Lovelace", job_title="", company_name="Acme", artifact_type="resume"
    )
    assert name == "Ada_Lovelace_Acme_Resume.pdf"


def test_filename_missing_candidate_name_falls_back_to_applicant() -> None:
    name = build_export_filename(candidate_name="", job_title="Engineer", company_name="Acme", artifact_type="resume")
    assert name == "Applicant_Engineer_Acme_Resume.pdf"


def test_filename_all_values_missing_falls_back_to_applicant_only() -> None:
    name = build_export_filename(candidate_name="", job_title="", company_name="", artifact_type="resume")
    assert name == "Applicant_Resume.pdf"
    letter = build_export_filename(candidate_name="", job_title="", company_name="", artifact_type="cover_letter")
    assert letter == "Applicant_Cover_Letter.pdf"


def test_filename_strips_punctuation_slashes_and_ampersands() -> None:
    name = build_export_filename(
        candidate_name="O'Brien, Jamie",
        job_title="Sales & Support / Ops",
        company_name="Acme, Inc.",
        artifact_type="resume",
    )
    base = name.removesuffix(".pdf")
    for unsafe in ("'", ",", "/", "&", "."):
        assert unsafe not in base


def test_filename_normalizes_accented_characters() -> None:
    name = build_export_filename(
        candidate_name="José Álvarez", job_title="Engineer", company_name="Acme", artifact_type="resume"
    )
    assert name.startswith("Jose_Alvarez_")


def test_filename_collapses_repeated_spaces_and_underscores() -> None:
    name = build_export_filename(
        candidate_name="Jamie   Lee",
        job_title="Senior   Engineer",
        company_name="Acme   Corp",
        artifact_type="resume",
    )
    assert "__" not in name


def test_filename_bounds_long_values() -> None:
    name = build_export_filename(
        candidate_name="A" * 300, job_title="B" * 300, company_name="C" * 300, artifact_type="resume"
    )
    assert len(name) < 250


def test_filename_never_contains_path_traversal_or_unsafe_characters() -> None:
    name = build_export_filename(
        candidate_name="../../etc/passwd", job_title="../secrets", company_name="C:\\Windows", artifact_type="resume"
    )
    assert ".." not in name
    assert "/" not in name
    assert "\\" not in name
    assert ":" not in name


def test_filename_never_includes_email_or_phone_even_if_passed_as_name() -> None:
    # The utility only ever receives already-resolved name/title/company
    # fields; even so, it must not special-case or preserve @ / phone-shaped
    # digits as if they were meaningful identity text beyond plain characters.
    name = sanitize_filename_component("jane.doe@example.com")
    assert "@" not in name


def test_filename_always_ends_in_pdf() -> None:
    name = build_export_filename(
        candidate_name="Ada", job_title="Engineer", company_name="Acme", artifact_type="resume"
    )
    assert name.endswith(".pdf")
    assert name.count(".pdf") == 1


# ---------------------------------------------------------------------------
# HTML rendering for local PDF rasterization (Phase 12)
# ---------------------------------------------------------------------------


def _sample_resume_document() -> ResumeDocument:
    return ResumeDocument(
        candidate_name="Ada Lovelace",
        professional_headline="Platform Developer | Power Automate",
        contact_lines=["ada@example.com", "555-000-1111"],
        summary="Platform developer with delivery experience across automation tooling.",
        skill_groups=[ResumeSkillGroup("Platform & Automation", ["Power Automate", "Power Apps"])],
        experience=[
            ResumeExperienceEntry(
                employer="Fieldstone Digital",
                title="Platform Developer",
                location="Ottawa, ON",
                date_range="Jan 2020 - Present",
                bullets=["Built automated workflows using Power Automate."],
            )
        ],
        education=[
            ResumeEducationEntry(
                institution="Carleton University",
                degree="Bachelor of Computer Science",
                location="Ottawa, ON",
                date_range="2016 - 2020",
            )
        ],
        certifications=[ResumeCertificationEntry("Microsoft Certified: Power Platform", "2023", "")],
        remaining_sections=[("Publications", ["A study of automated workflow design."])],
    )


def test_render_resume_html_includes_every_structured_section() -> None:
    html = render_resume_html(_sample_resume_document(), "classic")
    assert "Ada Lovelace" in html
    assert "Power Automate" in html
    assert "Fieldstone Digital" in html
    assert "Carleton University" in html
    assert "Microsoft Certified" in html
    assert "Publications" in html


def test_render_resume_html_never_contains_tables_or_images() -> None:
    html = render_resume_html(_sample_resume_document(), "modern")
    assert "<table" not in html.lower()
    assert "<img" not in html.lower()
    assert "<canvas" not in html.lower()


def test_render_resume_html_escapes_untrusted_content() -> None:
    document = _sample_resume_document()
    document.summary = "<script>alert(1)</script>"
    html = render_resume_html(document, "classic")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_cover_letter_html_includes_sender_recipient_and_body() -> None:
    document = CoverLetterDocument(
        sender_name="Ada Lovelace",
        sender_contact_lines=["ada@example.com"],
        date="July 1, 2026",
        recipient_company="Acme Corp",
        target_role="Platform Developer",
        greeting="Dear Hiring Manager,",
        body_paragraphs=["I am interested in the Platform Developer role at Acme Corp."],
        closing="Sincerely,",
        signature_name="Ada Lovelace",
    )
    html = render_cover_letter_html(document, "classic")
    assert "Ada Lovelace" in html
    assert "Acme Corp" in html
    assert "Platform Developer" in html
    assert "Dear Hiring Manager" in html


def test_render_plain_text_html_recognizes_headings_when_present() -> None:
    text = "Ada Lovelace\nada@example.com\n\nSUMMARY\nDelivery-focused engineer.\n\nSKILLS\nPython, SQL\n"
    html = render_plain_text_html(text, template="classic")
    assert "SUMMARY" in html
    assert "Delivery-focused engineer." in html
    assert '<div class="section">' in html


def test_render_plain_text_html_falls_back_to_verbatim_without_recognized_headings() -> None:
    text = "Just a freeform paragraph with no recognizable resume headings at all."
    html = render_plain_text_html(text, template="classic")
    assert "verbatim" in html
    assert "Just a freeform paragraph" in html


def test_rendered_html_never_contains_application_chrome() -> None:
    html = render_resume_html(_sample_resume_document(), "classic")
    for banned in ("Not revalidated", "Trust", "Evidence", "Print / Save as PDF", "Download / Print"):
        assert banned not in html
