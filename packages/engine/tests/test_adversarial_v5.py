from __future__ import annotations

from ats_engine.evidence.matrix import build_evidence_matrix
from ats_engine.kit.contract import FitCategory
from ats_engine.kit.orchestrator import generate_application_kit
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import build_profile
from ats_engine.scoring.match_report import build_weighted_keywords, score_resume
from conftest import ADVERSARIAL_RESUME

"""Adversarial v5 scoring tests: no unsupported content may raise a score."""

# A JD requiring things the adversarial candidate provably lacks (Kubernetes,
# AWS, Docker) plus one thing they have (Python, SQL).
_HARD_JD = (
    "Job Title: Platform Engineer\n"
    "Company: Vantage Analytics\n"
    "Required qualifications:\n"
    "- Kubernetes for container orchestration\n"
    "- AWS cloud infrastructure\n"
    "- Docker containerization\n"
    "- Python and SQL\n"
    "The team uses Kubernetes, AWS, Docker, Python, and SQL."
)


def _score_context(resume: str, jd: str):
    profile = build_profile(resume)
    if not profile.raw_markdown:
        profile.raw_markdown = resume
    jd_profile = parse_jd(jd)
    evidence = build_evidence_matrix(jd_profile, profile)
    keywords = build_weighted_keywords(evidence, jd_profile)
    tiers = {item.keyword.casefold().strip(): item.evidence_tier for item in evidence}
    return profile, keywords, tiers


def test_repeating_a_keyword_twelve_times_does_not_raise_score() -> None:
    profile, keywords, tiers = _score_context(ADVERSARIAL_RESUME, _HARD_JD)
    plain = score_resume(ADVERSARIAL_RESUME, keywords, profile, tiers)
    stuffed = score_resume(ADVERSARIAL_RESUME + "\n" + ("python " * 12), keywords, profile, tiers)
    assert stuffed.score == plain.score
    # An unsupported keyword repeated 12 times earns nothing either.
    kube_stuffed = score_resume(ADVERSARIAL_RESUME + "\n" + ("kubernetes " * 12), keywords, profile, tiers)
    assert kube_stuffed.score == plain.score
    assert "kubernetes" not in kube_stuffed.matched_keywords


def test_appending_whole_jd_does_not_produce_strong_result() -> None:
    kit = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME + "\n\n" + _HARD_JD,
        job_description=_HARD_JD,
        use_llm=False,
        include_resume=True,
        include_job_fit=True,
    )
    report = kit.match_report
    assert report is not None
    # The candidate genuinely lacks Kubernetes/AWS/Docker, so appending the JD
    # must not make the evidence alignment strong or the fit a strong fit.
    assert report.fit_category is not FitCategory.STRONG_FIT
    assert report.alignment_score < 85.0
    assert "kubernetes" not in [k.lower() for k in report.original_ats_match.matched_keywords]


def test_appended_jd_does_not_credit_unsupported_keywords_over_clean_resume() -> None:
    profile_clean, keywords, tiers = _score_context(ADVERSARIAL_RESUME, _HARD_JD)
    clean = score_resume(ADVERSARIAL_RESUME, keywords, profile_clean, tiers)

    appended_resume = ADVERSARIAL_RESUME + "\n\n" + _HARD_JD
    profile_app, keywords_app, tiers_app = _score_context(appended_resume, _HARD_JD)
    appended = score_resume(appended_resume, keywords_app, profile_app, tiers_app)

    # Appending the JD must not credit Kubernetes/AWS/Docker the candidate lacks.
    for unsupported in ("kubernetes", "aws", "docker"):
        assert unsupported not in [k.lower() for k in appended.matched_keywords], unsupported
    # And it must not push the score materially above the clean measurement.
    assert appended.score <= clean.score + 1.0
