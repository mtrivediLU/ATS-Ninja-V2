from __future__ import annotations

import pytest

from ats_engine import ApplicationKit, ClaimStatus, ClaimType, generate_application_kit
from ats_engine.models import Mode
from conftest import (
    ADVERSARIAL_JD,
    ADVERSARIAL_RESUME,
    FabricatingProvider,
    fabricated_answer,
)

"""Adversarial anti-fabrication suite — the primary Phase 2A acceptance criterion.

Every test injects a claim the candidate provably never made (via a controlled
adversarial provider — never a live model) and asserts the fabricated value is
**absent from the final ApplicationKit artifact**. It is deliberately not enough
that a validator "noticed" the fabrication; these tests read the delivered
artifact text and prove the fabricated content is gone. See ADR-0009/0011.
"""


# --------------------------------------------------------------------------- #
# Helpers: run the real orchestrator with a fabrication routed into one artifact
# --------------------------------------------------------------------------- #
def _answers_kit(claim_sentence: str) -> ApplicationKit:
    provider = FabricatingProvider(answer=fabricated_answer(claim_sentence))
    return generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        questions_text="Describe a leadership experience and your background.",
        default_mode=Mode.RESUME_AND_QUESTIONS,
        use_llm=True,
        prose_provider=provider,
    )


def _cover_kit(cover_text: str) -> ApplicationKit:
    provider = FabricatingProvider(cover=cover_text)
    return generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        default_mode=Mode.RESUME_AND_COVER,
        use_llm=True,
        prose_provider=provider,
    )


def _answers_text(kit: ApplicationKit) -> str:
    assert kit.answers is not None
    return kit.answers.text.lower()


def _has_disposed_claim(kit: ApplicationKit, claim_type: ClaimType) -> bool:
    return any(
        claim.claim_type == claim_type and claim.status in (ClaimStatus.REPAIRED, ClaimStatus.REJECTED)
        for claim in kit.all_claims()
    )


# A 4-paragraph, metric-free, style-clean cover letter that passes the engine's
# generation gate (so the fabrications actually reach the grounding stage rather
# than being pre-empted by a deterministic fallback).
ADVERSARIAL_COVER = (
    "I am applying for the AI Engineer role at Vantage Analytics because it matches the work I want to keep "
    "doing every day. My background sits at the meeting point of data and analytics, and I enjoy turning messy "
    "operational questions into clear and useful answers for the people who depend on them to make decisions.\n\n"
    "Earlier in my career I worked at Google, where I served as the Chief Technology Officer and set the "
    "direction for several large data teams across the whole company. That experience taught me how to keep "
    "delivery honest, how to weigh trade offs carefully, and how to explain those trade offs to stakeholders "
    "who are not close to the technical detail of the systems they rely on.\n\n"
    "I am also an expert in Rust, and I bring the same steady care to every system that I help to build. I "
    "focus on reliability, on clear documentation, and on smooth handoffs, because a change that nobody on the "
    "team can maintain later is not really finished. I would always rather ask an early question than quietly "
    "guess at a requirement and then rebuild it.\n\n"
    "I am based in Toronto and I am open to the work mode that the role needs. I would be glad to walk through "
    "how my background can support your priorities and where I think I could contribute first. Thank you very "
    "much for taking the time to consider my application to join your team this year."
)


# --------------------------------------------------------------------------- #
# The twelve mandatory scenarios (asserted on FINAL artifact output)
# --------------------------------------------------------------------------- #
def test_scenario_01_fabricated_employer_does_not_survive() -> None:
    kit = _answers_kit("At Google I led the analytics platform for the search organization.")
    assert "google" not in _answers_text(kit)
    assert _has_disposed_claim(kit, ClaimType.EMPLOYER)


def test_scenario_02_fabricated_title_does_not_survive() -> None:
    kit = _answers_kit("I served as Director of Data Engineering for the whole division.")
    text = _answers_text(kit)
    assert "director of data engineering" not in text
    assert "director" not in text
    assert _has_disposed_claim(kit, ClaimType.TITLE)


def test_scenario_03_fabricated_metric_does_not_survive() -> None:
    kit = _answers_kit("On that project I increased revenue by 47% in a single quarter.")
    assert "47%" not in _answers_text(kit)
    assert _has_disposed_claim(kit, ClaimType.METRIC)


def test_scenario_04_fabricated_dollar_value_does_not_survive() -> None:
    kit = _answers_kit("I personally saved the company $2.4 million in operating costs.")
    text = _answers_text(kit)
    assert "$2.4 million" not in text
    assert "2.4 million" not in text
    assert _has_disposed_claim(kit, ClaimType.MONETARY)


def test_scenario_05_fabricated_team_size_does_not_survive() -> None:
    kit = _answers_kit("I led a team of 15 engineers delivering the platform.")
    text = _answers_text(kit)
    assert "15 engineers" not in text
    assert "team of 15" not in text
    assert _has_disposed_claim(kit, ClaimType.TEAM_SIZE)


def test_scenario_06_fabricated_skill_does_not_survive() -> None:
    kit = _answers_kit("I am an expert in Rust and use it for systems programming daily.")
    assert "rust" not in _answers_text(kit)
    assert _has_disposed_claim(kit, ClaimType.SKILL)


def test_scenario_07_fabricated_certification_does_not_survive() -> None:
    kit = _answers_kit("I hold the AWS Certified Solutions Architect credential.")
    assert "aws certified" not in _answers_text(kit)
    assert _has_disposed_claim(kit, ClaimType.CERTIFICATION)


def test_scenario_08_fabricated_degree_does_not_survive() -> None:
    kit = _answers_kit("I earned a PhD in Artificial Intelligence during that period.")
    assert "phd" not in _answers_text(kit)
    assert _has_disposed_claim(kit, ClaimType.EDUCATION)


def test_scenario_09_fabricated_tenure_does_not_survive() -> None:
    kit = _answers_kit("I spent 10 years at that employer building their data stack.")
    assert "10 years" not in _answers_text(kit)
    assert _has_disposed_claim(kit, ClaimType.TENURE)


def test_scenario_10_cover_letter_hallucination_does_not_survive() -> None:
    kit = _cover_kit(ADVERSARIAL_COVER)
    assert kit.cover_letter is not None
    text = kit.cover_letter.text.lower()
    assert "google" not in text
    assert "chief technology officer" not in text
    assert "rust" not in text
    # A clean paragraph remains, so the letter is repaired (not merely emptied).
    assert "vantage analytics" in text


def test_scenario_11_application_answer_management_claim_does_not_survive() -> None:
    kit = _answers_kit("In that role I managed 50 people across three departments.")
    text = _answers_text(kit)
    assert "50 people" not in text
    assert _has_disposed_claim(kit, ClaimType.TEAM_SIZE)


def test_scenario_12_mixed_valid_and_invalid_preserves_supported_claims() -> None:
    # Supported facts in one sentence, a fabricated metric in another; only the
    # fabricated sentence should be removed.
    claim = (
        "At Northstar Analytics I worked as a Data Analyst building Python and SQL dashboards for the team. "
        "Separately, I increased revenue by 47% across the whole business."
    )
    kit = _answers_kit(claim)
    text = _answers_text(kit)
    assert "47%" not in text  # fabricated metric removed
    assert "northstar analytics" in text  # supported employer preserved
    assert "data analyst" in text  # supported title preserved
    assert "python" in text and "sql" in text  # supported skills preserved
    # The trace records the fabricated metric's disposition, not silent loss.
    assert _has_disposed_claim(kit, ClaimType.METRIC)


# --------------------------------------------------------------------------- #
# Step 25 adversarial variants: formatting / phrasing bypasses
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "claim_sentence,forbidden",
    [
        ("I grew signups by 47 percent last year.", "47 percent"),  # spelled-out percent
        ("I grew signups by 47%.", "47%"),  # symbol percent
        ("I saved the org $2.4M in the first year.", "2.4m"),  # $2.4M abbreviation
        ("I saved the org 2.4 million dollars overall.", "2.4 million"),  # spelled-out money
        ("I helped lead a team of 20 engineers there.", "20 engineers"),  # "helped lead" hedge
        ("I managed a team of 20 people directly.", "team of 20"),  # management phrasing
        ("I am familiar with Kubernetes at an advanced level.", "kubernetes"),  # "familiar with" hedge
        ("I have deep expertise in Golang for backend work.", "golang"),  # deep expertise
    ],
)
def test_step25_formatting_variants_do_not_survive(claim_sentence: str, forbidden: str) -> None:
    kit = _answers_kit(claim_sentence)
    assert forbidden.lower() not in _answers_text(kit)


def test_step25_title_inflation_helped_lead_does_not_become_director() -> None:
    kit = _answers_kit("As a Director I owned the roadmap and helped lead the org.")
    text = _answers_text(kit)
    assert "as a director" not in text
    assert "director" not in text


# --------------------------------------------------------------------------- #
# Step 25 regression locks: additional bypass vectors found during review
# --------------------------------------------------------------------------- #
def test_step25_exec_title_vp_does_not_survive() -> None:
    kit = _answers_kit("As VP of Engineering I owned the entire platform roadmap.")
    text = _answers_text(kit)
    assert "vp of engineering" not in text
    assert "vp " not in text


def test_step25_all_caps_expertise_does_not_survive() -> None:
    kit = _answers_kit("I am an EXPERT IN RUST for high-performance services.")
    assert "rust" not in _answers_text(kit)


def test_step25_certification_plural_phrasing_does_not_survive() -> None:
    kit = _answers_kit("I completed the CISSP certification during that year of work.")
    assert "cissp" not in _answers_text(kit)


# --------------------------------------------------------------------------- #
# Positive control (Step 14): with no fabrication, real facts survive end to end
# --------------------------------------------------------------------------- #
def test_deterministic_kit_preserves_supported_candidate_facts() -> None:
    kit = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        default_mode=Mode.RESUME_AND_COVER,
        use_llm=False,
    )
    assert kit.resume is not None and kit.cover_letter is not None
    resume = kit.resume.text
    assert "Northstar Analytics" in resume  # real employer kept
    assert "Data Analyst" in resume  # real title kept
    assert "Python" in resume and "SQL" in resume  # real skills kept
    assert "30%" in resume  # real metric kept
    assert "Bachelor of Computer Science" in resume  # real degree kept
    assert not kit.validation.fatal  # nothing fabricated, nothing rejected
    assert kit.resume.validation.rejected_claims == 0
