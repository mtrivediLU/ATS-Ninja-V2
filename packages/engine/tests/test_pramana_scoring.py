"""PRAMANA scoring: saturation, monotonicity, hygiene, and the provenance gate.

The single most important test in this file is
``test_tailored_score_requires_provenance_phrase_in_its_structured_target``,
which is a byte-for-byte port of the equivalent ats_v2 regression test. The
literal §2.3 formula (``supply(r) = occurrences of ... in resume_text``) says
nothing about *where* in the resume a phrase must appear -- implementing it
without carrying over the provenance gate would silently reopen the "paste
the JD at the bottom of the resume" scoring exploit ats_v2.py's own docstring
exists to prevent. This file proves the gate survived the port unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ats_engine.models import EvidenceLink, PlacementAction, RequirementTerm
from ats_engine.pramana.requirements import extract_requirements
from ats_engine.pramana.scoring import score_resume

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"


def _requirement(
    canonical: str,
    *,
    surface: str | None = None,
    weight: float = 3.0,
    section: str = "required",
    jd_occurrences: int = 1,
    aliases: tuple[str, ...] = (),
) -> RequirementTerm:
    return RequirementTerm(
        canonical=canonical,
        surface=surface or canonical,
        aliases=aliases,
        kind="tool",
        section=section,
        weight=weight,
        ngram=1,
        category="cloud",
        jd_evidence_line=f"- {surface or canonical} experience",
        jd_occurrences=jd_occurrences,
    )


def _grounded_link(requirement: RequirementTerm, *, tier: str = "A") -> EvidenceLink:
    return EvidenceLink(requirement=requirement, tier=tier, resume_span=requirement.surface)


# --------------------------------------------------------------- provenance ----


def test_tailored_score_requires_provenance_phrase_in_its_structured_target() -> None:
    """A valid action cannot authorize an arbitrary trailing keyword paste."""
    requirement = RequirementTerm(
        canonical="terraform",
        surface="Terraform",
        aliases=(),
        kind="tool",
        section="required",
        weight=3.0,
        ngram=1,
        category="cloud",
        jd_evidence_line="- Terraform experience",
    )
    link = EvidenceLink(
        requirement=requirement,
        tier="A",
        resume_span="Built Terraform modules for platform services.",
        resume_location="experience:0:bullet:0",
        match_type="direct_experience",
        surface_to_use="Terraform",
        max_placement="summary, skills, supported bullets",
    )
    action = PlacementAction(
        term="Terraform",
        link=link,
        target="skills",
        operation="append_skill",
        rendered_text="Terraform",
        grounded_by=link.resume_location,
    )
    source = """Professional Experience
- Built Terraform modules for platform services.
"""
    legitimate = """Candidate Header
Professional Headline: Platform Engineer

Professional Summary
Platform engineer focused on reliable cloud services.

Technical Skills
Cloud: Terraform

Professional Experience
Company: Example Corp | Title: Engineer
- Built platform services.

Education
BSc, Computer Science
"""
    arbitrary_trailing_text = """Candidate Header
Professional Headline: Platform Engineer

Professional Summary
Platform engineer focused on reliable cloud services.

Technical Skills
Cloud: Kubernetes

Professional Experience
Company: Example Corp | Title: Engineer
- Built platform services.

Education
BSc, Computer Science

Terraform
"""
    wrong_structured_target = """Candidate Header
Professional Headline: Platform Engineer

Professional Summary
Platform engineer with Terraform experience.

Technical Skills
Cloud: Kubernetes

Professional Experience
Company: Example Corp | Title: Engineer
- Built platform services.
"""

    accepted = score_resume(
        legitimate, [requirement], [link], source_resume_text=source, tailored=True, placements=[action]
    )
    appended = score_resume(
        arbitrary_trailing_text, [requirement], [link], source_resume_text=source, tailored=True, placements=[action]
    )
    wrong_target = score_resume(
        wrong_structured_target, [requirement], [link], source_resume_text=source, tailored=True, placements=[action]
    )

    assert accepted.score == 100.0
    assert appended.score == 0.0
    assert wrong_target.score == 0.0


# ---------------------------------------------------------------- saturation ----


def test_supply_beyond_target_credits_no_higher_than_saturation() -> None:
    """6 occurrences against a target of 3 credits the same as exactly 3."""
    requirement = _requirement("kubernetes", jd_occurrences=3)
    link = _grounded_link(requirement)

    at_target = score_resume("Kubernetes " * 3, [requirement], [link])
    above_target = score_resume("Kubernetes " * 6, [requirement], [link])

    assert at_target.per_requirement[0].credit == 1.0
    assert above_target.per_requirement[0].credit == 1.0
    assert at_target.keyword_score == above_target.keyword_score == 100.0


def test_extreme_stuffing_triggers_the_penalty_and_credits_no_more() -> None:
    """40 occurrences against a target of 3 penalizes; credit still caps at 1.0."""
    requirement = _requirement("kubernetes", jd_occurrences=3)
    link = _grounded_link(requirement)

    stuffed = score_resume("Kubernetes " * 40, [requirement], [link])

    assert stuffed.per_requirement[0].credit == 1.0
    assert stuffed.stuffing_penalty > 0
    assert stuffed.score < 100.0


def test_presence_is_fractional_below_target() -> None:
    """1 occurrence against a target of 3 earns partial, not full or zero, credit."""
    requirement = _requirement("kubernetes", jd_occurrences=3)
    link = _grounded_link(requirement)

    result = score_resume("Kubernetes", [requirement], [link])

    assert result.per_requirement[0].credit == pytest.approx(1 / 3)
    assert 0.0 < result.keyword_score < 100.0


# ------------------------------------------------------------- monotonicity ----


def test_adding_a_grounded_occurrence_never_decreases_the_score() -> None:
    """Within the non-stuffing range, one more mention never hurts."""
    requirement = _requirement("kubernetes", jd_occurrences=3)
    link = _grounded_link(requirement)

    fewer = score_resume("Kubernetes " * 2, [requirement], [link])
    more = score_resume("Kubernetes " * 3, [requirement], [link])

    assert more.score >= fewer.score


def test_removing_a_grounded_occurrence_never_increases_the_score() -> None:
    requirement = _requirement("kubernetes", jd_occurrences=3)
    link = _grounded_link(requirement)

    more = score_resume("Kubernetes " * 3, [requirement], [link])
    fewer = score_resume("Kubernetes " * 2, [requirement], [link])

    assert fewer.score <= more.score


def test_an_ungrounded_term_earns_no_credit_regardless_of_supply() -> None:
    """Presence without evidence is not credited -- tier "missing" earns zero."""
    requirement = _requirement("kubernetes", jd_occurrences=3)
    link = EvidenceLink(requirement=requirement, tier="missing")

    result = score_resume("Kubernetes " * 5, [requirement], [link])

    assert result.per_requirement[0].credit == 0.0
    assert result.keyword_score == 0.0


# -------------------------------------------------------------------- gaps ----


def test_unreachable_gap_stays_in_the_denominator_but_is_reported_separately() -> None:
    """tier="missing" requirements weigh down the score honestly, and are
    also surfaced separately so the product can say "these need real
    experience, not better wording."""
    reachable = _requirement("python", weight=3.0)
    unreachable = _requirement("kubernetes", weight=3.0)
    links = [_grounded_link(reachable), EvidenceLink(requirement=unreachable, tier="missing")]
    resume = "Professional Summary\nExperienced Python developer building backend services.\n"

    result = score_resume(resume, [reachable, unreachable], links)

    assert "kubernetes" in result.unreachable_gaps
    assert "python" not in result.unreachable_gaps
    # Half the weighted denominator is uncredited, so the score is well below
    # what a single fully-credited requirement alone would produce.
    assert result.keyword_score < 100.0


def test_declared_gaps_is_always_empty_today() -> None:
    """No resolver path produces tier="declared" yet (RACHANA §3.9, unbuilt)."""
    requirement = _requirement("python")
    link = _grounded_link(requirement)

    result = score_resume("Python", [requirement], [link])

    assert result.declared_gaps == []


# ----------------------------------------------------------- denominator hygiene ----


def test_junk_requirements_never_enter_the_denominator() -> None:
    """Label-shaped junk never reaches extract_requirements (PR A-1's job), so
    it can never enter PRAMANA's denominator either -- proven end to end
    against the real LatentView posting rather than assumed."""
    jd_text = (FIXTURES / "latentview_bi_ai" / "job_description.txt").read_text()
    requirements = extract_requirements(jd_text)
    canonicals = {requirement.canonical for requirement in requirements}
    for junk in ("bi frameworks", "ai tooling platforms", "analytical bi", "modern low code"):
        assert junk not in canonicals


# ---------------------------------------------------------------- explanation ----


def test_explanation_includes_a_line_for_every_material_nonzero_factor() -> None:
    requirement = _requirement("kubernetes", jd_occurrences=3)
    link = _grounded_link(requirement)

    stuffed = score_resume("Kubernetes " * 40, [requirement], [link], parse_confidence=0.2)

    assert stuffed.stuffing_penalty > 0
    assert any("stuffing" in line.lower() for line in stuffed.explanation)
    assert stuffed.confidence == "low"
    assert any("confidence" in line.lower() for line in stuffed.explanation)


def test_explanation_always_states_the_keyword_match_line() -> None:
    requirement = _requirement("python")
    link = _grounded_link(requirement)

    result = score_resume("Python", [requirement], [link])

    assert result.explanation
    assert "keyword match" in result.explanation[0].lower()


# ------------------------------------------------------------------ empty input ----


def test_no_requirements_scores_zero_honestly_rather_than_falling_back() -> None:
    result = score_resume("Anything at all", [], [])
    assert result.score == 0.0
    assert result.explanation


# ------------------------------------------------------------------ determinism ----


def test_scoring_is_deterministic() -> None:
    requirement = _requirement("python")
    link = _grounded_link(requirement)
    resume = "Professional Summary\nPython developer.\n"

    first = score_resume(resume, [requirement], [link])
    second = score_resume(resume, [requirement], [link])

    assert first == second


# -------------------------------------------------------------- title alignment ----


def test_title_alignment_rewards_a_matching_headline() -> None:
    requirement = _requirement("python")
    link = _grounded_link(requirement)
    resume = "Professional Headline: Senior Data Engineer\n\nProfessional Summary\nPython developer.\n"

    aligned = score_resume(resume, [requirement], [link], jd_title="Senior Data Engineer")
    unaligned = score_resume(resume, [requirement], [link], jd_title="Marketing Manager")

    assert aligned.title_alignment > unaligned.title_alignment
    assert aligned.score > unaligned.score


def test_a_placeholder_jd_title_earns_no_alignment_bonus() -> None:
    requirement = _requirement("python")
    link = _grounded_link(requirement)
    resume = "Professional Headline: Target Role\n\nProfessional Summary\nPython developer.\n"

    result = score_resume(resume, [requirement], [link], jd_title="Target Role")

    assert result.title_alignment == 0.0


# ---------------------------------------------------------------- placement bonus ----


def test_placement_bonus_rewards_skills_and_bullet_reinforcement() -> None:
    requirement = _requirement("python")
    link = _grounded_link(requirement)
    reinforced = (
        "Technical Skills\nPython\n\n"
        "Professional Experience\nCompany: Example Corp | Title: Engineer\n- Built services in Python.\n"
    )
    skills_only = "Technical Skills\nPython\n\nProfessional Experience\nCompany: Example Corp | Title: Engineer\n- Built services.\n"

    reinforced_result = score_resume(reinforced, [requirement], [link])
    skills_only_result = score_resume(skills_only, [requirement], [link])

    assert reinforced_result.placement_bonus > skills_only_result.placement_bonus
