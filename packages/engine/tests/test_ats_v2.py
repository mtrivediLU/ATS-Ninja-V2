"""Focused scoring regressions for Tailoring Engine v2."""

from __future__ import annotations

from ats_engine.models import EvidenceLink, PlacementAction, RequirementTerm
from ats_engine.scoring.ats_v2 import score_resume_v2


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

    accepted = score_resume_v2(
        legitimate,
        [requirement],
        [link],
        source_resume_text=source,
        tailored=True,
        placements=[action],
    )
    appended = score_resume_v2(
        arbitrary_trailing_text,
        [requirement],
        [link],
        source_resume_text=source,
        tailored=True,
        placements=[action],
    )
    wrong_target = score_resume_v2(
        wrong_structured_target,
        [requirement],
        [link],
        source_resume_text=source,
        tailored=True,
        placements=[action],
    )

    assert accepted.score == 100.0
    assert accepted.matched_keywords == ["Terraform"]
    assert appended.score == 0.0
    assert appended.matched_keywords == []
    assert wrong_target.score == 0.0
    assert wrong_target.matched_keywords == []
