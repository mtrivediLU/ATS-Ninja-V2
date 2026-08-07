"""PRUNE: the gates, and the concentration it is supposed to buy.

Subtraction is the riskiest operation in a truth-grounded product, so most of
this file is about what pruning *refuses* to do. The unit tests exercise each
protection against the real candidate fixture's own bullets, which is where
the interesting cases actually live: a bullet naming a Tier-1 client, one
stating a team size in words rather than digits, one that is the sole evidence
for a credited requirement.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ats_engine.generation.pipeline import run_pipeline
from ats_engine.models import EvidenceLink, Experience, Mode, RequirementTerm
from ats_engine.rachana.facts import build_fact_set
from ats_engine.rachana.pruning import (
    MIN_BULLETS_MOST_RECENT_ROLE,
    MIN_BULLETS_OLDER_ROLE,
    REJECT_PROTECTED_FACT,
    REJECT_ROLE_FLOOR,
    REJECT_UNEVIDENCED_ENTITY,
    REJECT_UNIQUE_EVIDENCE,
    PruneProposal,
    bullet_body,
    check_prune,
    check_role_floor,
    screen_bullet,
)

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"
CASES = ("cgi_fullstack_java_angular", "crowdplat_web_scraper", "latentview_bi_ai")


def _requirement(canonical: str) -> RequirementTerm:
    return RequirementTerm(
        canonical=canonical,
        surface=canonical,
        aliases=(),
        kind="tool",
        section="body",
        weight=1.0,
        ngram=1,
        category="technical",
        jd_evidence_line="",
    )


def _link(canonical: str, location: str) -> EvidenceLink:
    return EvidenceLink(requirement=_requirement(canonical), tier="A", resume_span="", resume_location=location)


def _proposal(text: str, *, experience_index: int = 3, bullet_index: int = 1) -> PruneProposal:
    return PruneProposal(
        experience_index=experience_index,
        bullet_index=bullet_index,
        location=f"experience:{experience_index}:bullet:{bullet_index}",
        text=text,
        rationale="no_requirement_relevance",
    )


def _role(*bullets: str) -> Experience:
    return Experience(
        company="Minax Inc.", title="Lead Software Developer", location="", dates="", bullets=list(bullets)
    )


# --------------------------------------------------------------------------
# The screen
# --------------------------------------------------------------------------


def test_a_bullet_carrying_live_requirement_relevance_is_not_even_a_candidate() -> None:
    proposal = screen_bullet(
        1,
        0,
        "Backend Architecture: Implemented services using Java Spring and Hibernate.",
        requirements=[_requirement("java")],
        document_text="Backend Architecture: Implemented services using Java Spring and Hibernate.",
    )
    assert proposal is None


def test_a_bullet_with_no_requirement_relevance_is_screened_as_class_one() -> None:
    proposal = screen_bullet(
        1,
        2,
        "UI/UX Optimization: Delivered low-latency data visualizations for operators.",
        requirements=[_requirement("java")],
        document_text="irrelevant",
    )
    assert proposal is not None
    assert proposal.rationale == "no_requirement_relevance"
    assert proposal.location == "experience:1:bullet:2"


def test_class_two_needs_an_older_role_and_the_term_expressed_elsewhere() -> None:
    """A relevant bullet is removable only where nothing is lost by removing it."""
    bullet = "Automation: Automated compliance workflows with Python."
    document_with = f"Skills: Python\n{bullet}"
    document_without_elsewhere = bullet

    # Recent role: never eligible for class 2, however redundant the term is.
    assert screen_bullet(1, 0, bullet, requirements=[_requirement("python")], document_text=document_with) is None
    # Older role, term also expressed elsewhere: eligible.
    older = screen_bullet(4, 0, bullet, requirements=[_requirement("python")], document_text=document_with)
    assert older is not None
    assert older.rationale == "relevance_expressed_elsewhere"
    # Older role, but this bullet is the only place the term appears: not eligible.
    assert (
        screen_bullet(4, 0, bullet, requirements=[_requirement("python")], document_text=document_without_elsewhere)
        is None
    )


def test_the_candidates_own_leading_label_is_not_treated_as_a_fact() -> None:
    assert bullet_body("UI/UX Optimization: Delivered low-latency visualizations.") == (
        "Delivered low-latency visualizations."
    )
    # A long prefix is prose, not a label, and is kept under scrutiny.
    long_prefix = "Something that runs on for many words indeed beyond a label: tail"
    assert bullet_body(long_prefix) == long_prefix


# --------------------------------------------------------------------------
# The hard gates, each proven against a real fixture bullet
# --------------------------------------------------------------------------


def test_sole_evidence_for_a_credited_requirement_is_never_removed() -> None:
    text = "CI/CD & Reliability: Optimized deployment workflows through DevOps practices."
    rejection = check_prune(
        _proposal(text),
        role=_role(text, "another bullet", "a third bullet"),
        links=[_link("ci/cd", "experience:3:bullet:1")],
        fact_set=build_fact_set(_empty_profile()),
        credited_canonicals=frozenset({"ci/cd"}),
    )
    assert rejection is not None
    assert rejection.reason == REJECT_UNIQUE_EVIDENCE
    assert "ci/cd" in rejection.detail


def test_a_requirement_with_no_credit_does_not_protect_its_bullet() -> None:
    """Protecting evidence for something the resume is not paid for blocks
    removals for no benefit -- the credited set is what matters."""
    text = "Production Deployment: Deployed and validated the system across sites."
    rejection = check_prune(
        _proposal(text),
        role=_role(text, "another bullet", "a third bullet"),
        links=[_link("ci/cd", "experience:3:bullet:1")],
        fact_set=build_fact_set(_empty_profile()),
        credited_canonicals=frozenset(),
    )
    assert rejection is None


@pytest.mark.parametrize(
    ("text", "expected_fragment"),
    (
        ("Reporting: Reduced manual reporting overhead by 40% across the team.", "40%"),
        ("Leadership: Led a team of four engineers maintaining the platform.", "team of four engineers"),
        # The digits inside a credential id are themselves a metric, so the
        # metric gate fires first. Either way the bullet is kept, which is the
        # property that matters; the detail names whichever fired.
        ("Certified: Holds credential AWS-12345 for the platform.", "12345"),
    ),
)
def test_a_checkable_fact_blocks_removal(text: str, expected_fragment: str) -> None:
    rejection = check_prune(
        _proposal(text),
        role=_role(text, "another bullet", "a third bullet"),
        links=[],
        fact_set=build_fact_set(_empty_profile()),
        credited_canonicals=frozenset(),
    )
    assert rejection is not None
    assert rejection.reason == REJECT_PROTECTED_FACT
    assert expected_fragment in rejection.detail


def test_a_named_entity_not_evidenced_elsewhere_in_the_role_blocks_removal() -> None:
    """The named-client case: "Vale (Tier-1 mining client)" must not vanish."""
    text = "Mobile Architecture: Architected an application for Vale across sites."
    rejection = check_prune(
        _proposal(text),
        role=_role(text, "an unrelated bullet", "a third bullet"),
        links=[],
        fact_set=build_fact_set(_empty_profile()),
        credited_canonicals=frozenset(),
    )
    assert rejection is not None
    assert rejection.reason == REJECT_UNEVIDENCED_ENTITY
    assert "Vale" in rejection.detail


def test_a_named_entity_evidenced_elsewhere_in_the_role_does_not_block_removal() -> None:
    text = "Mobile Architecture: Architected an application for Vale across sites."
    rejection = check_prune(
        _proposal(text),
        role=_role(text, "Delivered the Vale rollout end to end.", "a third bullet"),
        links=[],
        fact_set=build_fact_set(_empty_profile()),
        credited_canonicals=frozenset(),
    )
    assert rejection is None


def test_the_role_floor_protects_the_most_recent_role_more_strongly() -> None:
    assert MIN_BULLETS_MOST_RECENT_ROLE > MIN_BULLETS_OLDER_ROLE
    # Most recent role at its floor: blocked.
    blocked = check_role_floor(0, MIN_BULLETS_MOST_RECENT_ROLE)
    assert blocked is not None
    assert blocked.reason == REJECT_ROLE_FLOOR
    assert "most recent role" in blocked.detail
    # An older role with the same bullet count still has room.
    assert check_role_floor(4, MIN_BULLETS_MOST_RECENT_ROLE) is None
    # No role may fall below its own floor.
    assert check_role_floor(4, MIN_BULLETS_OLDER_ROLE) is not None


def _empty_profile():  # type: ignore[no-untyped-def]
    from ats_engine.models import ContactInfo, Profile

    return Profile(
        contact=ContactInfo(),
        retired_emails=[],
        role_identities=[],
        tier_a={},
        tier_b={},
        tier_c={},
        adjacency={},
        experiences=[],
        education=[],
        certifications=[],
        supported_metrics=[],
    )


# --------------------------------------------------------------------------
# End to end, on the real fixtures
# --------------------------------------------------------------------------


def _run(case: str):  # type: ignore[no-untyped-def]
    return run_pipeline(
        resume_text=(FIXTURES / "candidate_resume.pymupdf.txt").read_text(encoding="utf-8"),
        job_description=(FIXTURES / case / "job_description.txt").read_text(encoding="utf-8"),
        default_mode=Mode.RESUME,
        use_llm=False,
    )


@pytest.mark.parametrize("case", CASES)
def test_pruning_shortens_the_document_and_raises_density_on_every_fixture(case: str) -> None:
    """Criteria 1-3: a prune lands, length falls, concentration rises."""
    result = _run(case)
    diagnostics = result.metadata["optimization_trace"].diagnostics

    assert diagnostics.removals, f"{case} accepted no prune"
    assert diagnostics.delivered_word_count < diagnostics.source_word_count
    assert diagnostics.relevant_terms_per_100_words_after > diagnostics.relevant_terms_per_100_words_before


@pytest.mark.parametrize("case", CASES)
def test_a_pruned_resume_is_still_delivered_and_still_complete(case: str) -> None:
    """A removal must never withhold the resume, and never lose a fact."""
    result = _run(case)
    trace = result.metadata["optimization_trace"]

    assert trace.delivery_state.value == "generated"
    assert not [error for error in result.validation_errors if "completeness:" in error]
    assert not [error for error in result.validation_errors if "fidelity: missing" in error]


@pytest.mark.parametrize("case", CASES)
def test_every_removal_is_recorded_verbatim_and_is_genuinely_gone(case: str) -> None:
    """The ledger's own claim, checked independently of the gate that trusts it."""
    result = _run(case)
    diagnostics = result.metadata["optimization_trace"].diagnostics
    delivered = result.resume_text

    for location, text in diagnostics.removals:
        assert text.strip(), f"{location} recorded an empty original"
        assert text not in delivered, f"{location} claims a removal that is still delivered"


def test_pruning_is_deterministic_across_runs() -> None:
    first, second = _run(CASES[0]), _run(CASES[0])
    assert hashlib.sha256(first.resume_text.encode()).hexdigest() == (
        hashlib.sha256(second.resume_text.encode()).hexdigest()
    )
    assert first.metadata["optimization_trace"].diagnostics.removals == (
        second.metadata["optimization_trace"].diagnostics.removals
    )
