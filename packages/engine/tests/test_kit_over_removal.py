from __future__ import annotations

import pytest

from ats_engine import ClaimStatus, ClaimType, generate_application_kit
from ats_engine.kit.contract import ArtifactKind
from ats_engine.kit.grounding import EvidenceContext, build_evidence_context, ground_text
from ats_engine.models import JDProfile, Mode
from ats_engine.parsing.resume import build_profile
from conftest import ADVERSARIAL_JD, ADVERSARIAL_RESUME, FabricatingProvider, fabricated_answer

"""Over-removal / supported-claim preservation (audit remediation, Step 3).

A grounding layer that passes every adversarial test by deleting everything
specific is a failure, not a success. These tests prove the remediation removes
fabrications WITHOUT destroying legitimate supported candidate evidence, including
the hard case where a supported claim shares a sentence with a fabricated one.
"""


def _ctx(resume: str = ADVERSARIAL_RESUME, company: str = "Vantage Analytics") -> EvidenceContext:
    profile = build_profile(resume)
    if not profile.raw_markdown:
        profile.raw_markdown = resume
    return build_evidence_context(profile, JDProfile(title="AI Engineer", company=company))


def _clean(text: str, ctx: EvidenceContext) -> str:
    return ground_text(text, artifact=ArtifactKind.ANSWERS, context=ctx, id_prefix="t").clean_text


# --------------------------------------------------------------------------- #
# Pure false positives must NOT delete truthful sentences
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "sentence,must_keep",
    [
        ("In Plan C to organize the rollout, I built dashboards using Python and SQL.", "dashboards"),
        ("I needed a grade C to obtain the certificate for my SQL coursework.", "coursework"),
        ("I worked with Finance and Operations to deliver Python dashboards.", "python dashboards"),
    ],
)
def test_ambiguous_prose_is_not_over_removed(sentence: str, must_keep: str) -> None:
    cleaned = _clean(sentence, _ctx()).lower()
    assert must_keep in cleaned
    # None of these contain a real fabrication, so nothing should be dropped.
    assert cleaned.strip() != ""


# --------------------------------------------------------------------------- #
# Mixed sentence: fabricated clause removed, supported clause preserved
# --------------------------------------------------------------------------- #
def test_mixed_sentence_preserves_supported_clause_grounding() -> None:
    sentence = (
        "At Northstar Analytics I used Python and SQL to lift dashboard adoption by 30 percent, "
        "and at Google I wrote Rust that saved two million dollars as VP."
    )
    cleaned = _clean(sentence, _ctx()).lower()
    # Fabricated identity/metric/skill/title gone.
    for forbidden in ("google", "rust", "two million", "vp"):
        assert forbidden not in cleaned
    # Supported facts retained.
    for kept in ("northstar analytics", "python", "sql", "30"):
        assert kept in cleaned
    # Not reduced to generic filler.
    assert "northstar analytics i used python and sql" in cleaned


def test_mixed_sentence_preserves_supported_content_end_to_end() -> None:
    answer = fabricated_answer(
        "At Northstar Analytics I worked as a Data Analyst using Python and SQL to lift dashboard "
        "adoption by 30 percent, and at Google I wrote Rust that saved two million dollars as VP."
    )
    kit = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        questions_text="Describe your background.",
        default_mode=Mode.RESUME_AND_QUESTIONS,
        use_llm=True,
        prose_provider=FabricatingProvider(answer=answer),
    )
    assert kit.answers is not None
    text = kit.answers.text.lower()
    for forbidden in ("google", "rust", "two million", "as vp"):
        assert forbidden not in text
    for kept in ("northstar analytics", "python", "sql", "30"):
        assert kept in text
    # The evidence trace must not mark the fabricated claims supported.
    for claim in kit.all_claims():
        if claim.text.lower() in {"google", "rust", "vp"} or "two million" in claim.text.lower():
            assert claim.status in (ClaimStatus.REPAIRED, ClaimStatus.REJECTED)


def test_jd_tool_clause_dropped_but_supported_contribution_kept() -> None:
    cleaned = _clean("The team uses Docker and Kubernetes, and I contributed SQL dashboards.", _ctx()).lower()
    assert "docker" not in cleaned and "kubernetes" not in cleaned
    assert "sql dashboards" in cleaned


# --------------------------------------------------------------------------- #
# Real, supported claims survive (positive controls at grounding level)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "sentence,expected",
    [
        ("At Northstar Analytics I built the reporting stack.", "northstar analytics"),
        ("I reduced manual reporting time by 30% last year.", "30%"),
        ("I am proficient in Python and used SQL daily.", "python"),
        ("I hold a Bachelor of Computer Science degree.", "bachelor"),
    ],
)
def test_supported_claims_survive(sentence: str, expected: str) -> None:
    assert expected in _clean(sentence, _ctx()).lower()


_MANAGER_RESUME = (
    "Alex Lee\nalex.lee@example.com\nPROFESSIONAL EXPERIENCE\n"
    "Riverstone Labs Toronto, ON\nEngineering Manager 2018 - 2024\n"
    "- Led a team of 4 engineers maintaining a payments platform, improving reliability by 20%.\n"
    "- Managed the reporting roadmap for the analytics group.\n"
    "EDUCATION\nWaterloo University\nBachelor of Software Engineering 2014 - 2018\n"
)


def test_real_management_claim_survives_even_with_number_words() -> None:
    ctx = _ctx(_MANAGER_RESUME, company="Vantage")
    # Exact digit form and paraphrased number-word form both survive.
    assert "4 engineers" in _clean("I led a team of 4 engineers on the payments platform.", ctx).lower()
    assert "four engineers" in _clean("I led a team of four engineers on the payments platform.", ctx).lower()
    assert "roadmap" in _clean("I managed the reporting roadmap for the analytics group.", ctx).lower()


def test_real_team_size_metric_survives() -> None:
    ctx = _ctx(_MANAGER_RESUME, company="Vantage")
    assert "20%" in _clean("I improved reliability by 20% on the platform.", ctx).lower()


# --------------------------------------------------------------------------- #
# End-to-end: a deterministic kit keeps useful specificity (not generic filler)
# --------------------------------------------------------------------------- #
def test_deterministic_kit_keeps_useful_specificity() -> None:
    kit = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        default_mode=Mode.RESUME_AND_COVER,
        use_llm=False,
    )
    assert kit.resume is not None
    resume = kit.resume.text
    for fact in ("Northstar Analytics", "Data Analyst", "Python", "SQL", "30%", "Bachelor of Computer Science"):
        assert fact in resume, f"deterministic kit dropped supported fact: {fact}"
    assert not kit.validation.fatal
    # A supported metric is recorded as supported in the trace (not silently lost).
    assert any(
        claim.claim_type == ClaimType.METRIC and claim.status == ClaimStatus.SUPPORTED for claim in kit.resume.claims
    )
