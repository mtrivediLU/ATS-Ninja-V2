from __future__ import annotations

from ats_engine.evidence.matrix import build_evidence_matrix
from ats_engine.kit.contract import FitCategory, ScoreConfidence
from ats_engine.kit.orchestrator import generate_application_kit
from ats_engine.models import JDProfile
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import build_profile
from ats_engine.scoring.match_report import (
    DISCLAIMER,
    build_match_report,
    build_recommendation,
    build_weighted_keywords,
    fit_category,
    score_confidence,
    score_resume,
)
from ats_engine.validation.style import validate_style
from conftest import SYNTHETIC_JD, SYNTHETIC_RESUME


def _profile_and_jd(resume: str = SYNTHETIC_RESUME, jd: str = SYNTHETIC_JD):
    profile = build_profile(resume)
    if not profile.raw_markdown:
        profile.raw_markdown = resume
    jd_profile = parse_jd(jd)
    evidence = build_evidence_matrix(jd_profile, profile)
    return profile, jd_profile, evidence


# --------------------------------------------------------------------------- #
# Unified keyword vocabulary
# --------------------------------------------------------------------------- #
def test_unified_keywords_dedupe_and_weight() -> None:
    profile, jd_profile, evidence = _profile_and_jd()
    keywords = build_weighted_keywords(evidence, jd_profile)
    terms = [k.term.casefold() for k in keywords]
    assert len(terms) == len(set(terms)), "keywords must be case-insensitively deduplicated"
    for keyword in keywords:
        assert keyword.weight in (1.0, 2.0)
        if keyword.required:
            assert keyword.weight == 2.0
        else:
            assert keyword.weight == 1.0


def test_unified_keywords_are_jd_only() -> None:
    # A candidate-only skill (never in the JD) must not enter the vocabulary.
    jd_profile = JDProfile(
        title="Engineer",
        required_qualifications=["python"],
        technical_keywords=["python", "sql"],
    )
    profile = build_profile("Alex\nSkills\nPython, Rust, Haskell\n")
    evidence = build_evidence_matrix(jd_profile, profile)
    keywords = build_weighted_keywords(evidence, jd_profile)
    terms = {k.term.casefold() for k in keywords}
    assert "rust" not in terms
    assert "haskell" not in terms


# --------------------------------------------------------------------------- #
# Word boundary + presence vs frequency
# --------------------------------------------------------------------------- #
def test_java_does_not_match_javascript() -> None:
    profile, jd_profile, evidence = _profile_and_jd(
        resume="Dev\nProfessional Experience\nCompany: X\nTitle: Dev\nDates: 2020 - 2023\n- Built apps in JavaScript\nSkills\nJavaScript\n",
        jd="Engineer. Required: Java. The team uses Java.",
    )
    keywords = build_weighted_keywords(evidence, jd_profile)
    tiers = {item.keyword.casefold().strip(): item.evidence_tier for item in evidence}
    score = score_resume("Built apps in JavaScript", keywords, profile, tiers)
    assert "Java" not in score.matched_keywords


def test_presence_not_frequency() -> None:
    profile, jd_profile, evidence = _profile_and_jd()
    keywords = build_weighted_keywords(evidence, jd_profile)
    tiers = {item.keyword.casefold().strip(): item.evidence_tier for item in evidence}
    once = score_resume(SYNTHETIC_RESUME, keywords, profile, tiers)
    stuffed = score_resume(SYNTHETIC_RESUME + "\nSQL SQL SQL SQL SQL SQL", keywords, profile, tiers)
    assert stuffed.score == once.score, "repeating a keyword must not raise the score"


def test_required_keyword_outweighs_preferred_in_score() -> None:
    # One required (weight 2.0) + one preferred (weight 1.0). Matching only the
    # required keyword must yield 2/3 = 66.67%, not the count-based 50%.
    jd_profile = JDProfile(
        title="Engineer",
        required_qualifications=["python"],
        preferred_qualifications=["kubernetes"],
        technical_keywords=["python", "kubernetes"],
    )
    profile = build_profile(
        "Alex\nProfessional Experience\nCompany: X\nTitle: Dev\nDates: 2020 - 2023\n"
        "- Built services in Python\nSkills\nPython\n"
    )
    evidence = build_evidence_matrix(jd_profile, profile)
    keywords = build_weighted_keywords(evidence, jd_profile)
    tiers = {item.keyword.casefold().strip(): item.evidence_tier for item in evidence}
    score = score_resume("Built services in Python", keywords, profile, tiers)
    assert score.matched_keywords == ["python"]
    assert score.score == 66.67


def test_weighted_score_repetition_does_not_help() -> None:
    jd_profile = JDProfile(
        title="Engineer",
        required_qualifications=["python"],
        preferred_qualifications=["kubernetes"],
        technical_keywords=["python", "kubernetes"],
    )
    profile = build_profile(
        "Alex\nProfessional Experience\nCompany: X\nTitle: Dev\nDates: 2020 - 2023\n"
        "- Built services in Python\nSkills\nPython\n"
    )
    evidence = build_evidence_matrix(jd_profile, profile)
    keywords = build_weighted_keywords(evidence, jd_profile)
    tiers = {item.keyword.casefold().strip(): item.evidence_tier for item in evidence}
    once = score_resume("Built services in Python", keywords, profile, tiers)
    many = score_resume("Python Python Python built services in Python", keywords, profile, tiers)
    assert once.score == many.score == 66.67


def test_required_and_preferred_counts() -> None:
    profile, jd_profile, evidence = _profile_and_jd()
    keywords = build_weighted_keywords(evidence, jd_profile)
    tiers = {item.keyword.casefold().strip(): item.evidence_tier for item in evidence}
    score = score_resume(SYNTHETIC_RESUME, keywords, profile, tiers)
    assert score.required_total >= 0
    assert score.required_matched <= score.required_total
    assert score.preferred_matched <= score.preferred_total
    assert score.total_keywords == len(keywords)


def test_no_credit_without_candidate_evidence() -> None:
    # A JD keyword absent from candidate evidence earns no credit even if it
    # literally appears in the measured text.
    jd_profile = JDProfile(title="Engineer", required_qualifications=["kubernetes"], technical_keywords=["kubernetes"])
    profile = build_profile("Alex\nSkills\nPython\n")  # no kubernetes evidence
    evidence = build_evidence_matrix(jd_profile, profile)
    keywords = build_weighted_keywords(evidence, jd_profile)
    tiers = {item.keyword.casefold().strip(): item.evidence_tier for item in evidence}
    score = score_resume("I want to learn kubernetes kubernetes kubernetes", keywords, profile, tiers)
    assert "kubernetes" not in score.matched_keywords


# --------------------------------------------------------------------------- #
# Fit category thresholds (edges)
# --------------------------------------------------------------------------- #
def test_fit_category_edges() -> None:
    assert fit_category(85.0, 0) is FitCategory.STRONG_FIT
    assert fit_category(85.0, 1) is FitCategory.GOOD_FIT  # a must-have gap blocks strong
    assert fit_category(84.99, 0) is FitCategory.GOOD_FIT
    assert fit_category(70.0, 1) is FitCategory.GOOD_FIT
    assert fit_category(70.0, 2) is FitCategory.STRETCH_ROLE  # 2 gaps cap at stretch
    assert fit_category(60.0, 2) is FitCategory.STRETCH_ROLE  # >=50 but 2 gaps -> stretch, not partial
    assert fit_category(55.0, 0) is FitCategory.PARTIAL_FIT
    assert fit_category(40.0, 0) is FitCategory.STRETCH_ROLE
    assert fit_category(20.0, 0) is FitCategory.LOW_ALIGNMENT
    assert fit_category(20.0, 3) is FitCategory.STRETCH_ROLE


# --------------------------------------------------------------------------- #
# Confidence rubric
# --------------------------------------------------------------------------- #
def test_confidence_high_for_clean_inputs() -> None:
    profile, jd_profile, evidence = _profile_and_jd()
    level, reasons = score_confidence(
        jd_profile=jd_profile,
        profile=profile,
        evidence=evidence,
        keyword_count=len(build_weighted_keywords(evidence, jd_profile)),
        extraction_warnings=[],
        contact_issue_count=0,
    )
    assert level in (ScoreConfidence.HIGH, ScoreConfidence.MEDIUM)
    assert reasons


def test_garbled_jd_lowers_confidence() -> None:
    jd_profile = JDProfile()  # no title, no requirements
    profile = build_profile("Alex\n")
    level, reasons = score_confidence(
        jd_profile=jd_profile,
        profile=profile,
        evidence=[],
        keyword_count=0,
        extraction_warnings=["manual review recommended"],
        contact_issue_count=1,
    )
    assert level is ScoreConfidence.LOW
    assert any("title" in reason.lower() for reason in reasons)


# --------------------------------------------------------------------------- #
# Recommendation + style + disclaimer
# --------------------------------------------------------------------------- #
def test_recommendation_is_constructive_and_style_clean() -> None:
    for category in FitCategory:
        text = build_recommendation(
            category=category,
            seed=f"seed-{category.value}",
            strongest_matches=["Python", "SQL"],
            genuine_gaps=["Kubernetes"],
            must_have_gaps=["Kubernetes"],
        )
        assert DISCLAIMER in text
        assert "guarantee" not in text.lower()
        assert "do not apply" not in text.lower()
        assert validate_style(text) == [], f"style violation for {category}: {validate_style(text)}"


def test_recommendation_varies_by_input_but_is_deterministic() -> None:
    a1 = build_recommendation(
        category=FitCategory.GOOD_FIT, seed="alex|acme", strongest_matches=[], genuine_gaps=[], must_have_gaps=[]
    )
    a2 = build_recommendation(
        category=FitCategory.GOOD_FIT, seed="alex|acme", strongest_matches=[], genuine_gaps=[], must_have_gaps=[]
    )
    assert a1 == a2, "same input must be deterministic"
    # Different seeds should be able to vary the opening (not guaranteed for every pair,
    # but across a spread at least one differs).
    spread = {
        build_recommendation(
            category=FitCategory.GOOD_FIT, seed=f"seed{i}", strongest_matches=[], genuine_gaps=[], must_have_gaps=[]
        )
        for i in range(6)
    }
    assert len(spread) >= 2


# --------------------------------------------------------------------------- #
# Full report + tailored-lower-than-original explanation
# --------------------------------------------------------------------------- #
def test_full_match_report_end_to_end() -> None:
    kit = generate_application_kit(
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        use_llm=False,
        include_resume=True,
        include_cover_letter=False,
    )
    report = kit.match_report
    assert report is not None
    assert 0 <= report.original_ats_match.score <= 100
    assert report.tailored_ats_match is not None
    assert 0 <= report.alignment_score <= 100
    assert report.disclaimer == DISCLAIMER
    assert validate_style(report.kit_summary) == []
    assert validate_style(report.recommendation) == []
    # kit summary distinguishes the three scores
    assert "Original resume keyword match" in report.kit_summary
    assert "Tailored resume keyword match" in report.kit_summary
    assert "role alignment" in report.kit_summary.lower()


def test_tailored_lower_than_original_is_explained() -> None:
    profile, jd_profile, evidence = _profile_and_jd()
    plan_profile = profile
    keywords = build_weighted_keywords(evidence, jd_profile)
    from ats_engine.generation.planning import build_resume_plan

    plan = build_resume_plan(contacts=profile.contact, jd_profile=jd_profile, profile=profile, provider=None)
    report = build_match_report(
        profile=plan_profile,
        jd_profile=jd_profile,
        resume_plan=plan,
        original_resume_text=SYNTHETIC_RESUME,
        tailored_resume_text="Alex Morgan\nSoftware Engineer\n",  # deliberately sparse tailored text
        job_fit=None,
    )
    assert report.tailored_ats_match is not None
    if report.tailored_ats_match.score < report.original_ats_match.score:
        assert "lower" in report.kit_summary.lower()
    assert keywords  # sanity
