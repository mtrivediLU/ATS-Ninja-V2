from __future__ import annotations

import hashlib

import pytest

from ats_engine import (
    FitBand,
    Mode,
    RequirementClassification,
    application_kit_from_dict,
    application_kit_to_dict,
    generate_application_kit,
)
from ats_engine.job_fit.policy import fit_band_for_score, requirement_coverage_score
from ats_engine.models import EvidenceItem
from ats_engine.providers import LLMProvider
from conftest import ADVERSARIAL_JD, ADVERSARIAL_RESUME


class JobFitProvider(LLMProvider):
    def __init__(self, narrative: str) -> None:
        self.narrative = narrative
        self._identity = "job-fit:" + hashlib.sha256(narrative.encode()).hexdigest()[:12]

    @property
    def identity(self) -> str:
        return self._identity

    def complete(self, prompt: str) -> str:
        return self.narrative if "JOB FIT NARRATIVE" in prompt else ""


def _item(tier: str, importance: str = "required") -> EvidenceItem:
    return EvidenceItem("x", importance, tier, "", "", "", "")


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (-1.0, FitBand.LOW),
        (0.0, FitBand.LOW),
        (49.99, FitBand.LOW),
        (50.0, FitBand.PARTIAL),
        (69.99, FitBand.PARTIAL),
        (70.0, FitBand.COMPETITIVE),
        (84.99, FitBand.COMPETITIVE),
        (85.0, FitBand.STRONG),
        (100.0, FitBand.STRONG),
        (101.0, FitBand.STRONG),
    ],
)
def test_fit_band_threshold_boundaries(score: float, expected: FitBand) -> None:
    assert fit_band_for_score(score) is expected


def test_requirement_coverage_policy_is_reproducible() -> None:
    evidence = [_item("A"), _item("B"), _item("adjacency", "preferred"), _item("C"), _item("missing")]
    assert requirement_coverage_score(evidence) == 53.89
    assert requirement_coverage_score(evidence) == requirement_coverage_score(evidence)


def test_provider_none_builds_complete_useful_job_fit() -> None:
    kit = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        default_mode=Mode.RESUME,
        use_llm=False,
    )
    artifact = kit.job_fit
    assert artifact is not None
    assert artifact.summary
    assert artifact.requirements
    assert artifact.requirement_coverage_score == 100.0
    assert artifact.fit_band is FitBand.STRONG
    assert {item.classification for item in artifact.requirements} == {RequirementClassification.PROVEN}
    assert {"python", "sql", "dashboards"} <= {item.lower() for item in artifact.strongest_matches}
    assert artifact.consistency.passed
    assert not artifact.withheld
    assert all(len(ref.excerpt) <= 160 for ref in artifact.evidence)


def test_job_fit_can_be_disabled_without_changing_existing_artifacts() -> None:
    enabled = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        default_mode=Mode.RESUME_AND_COVER,
        use_llm=False,
    )
    disabled = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        default_mode=Mode.RESUME_AND_COVER,
        use_llm=False,
        include_job_fit=False,
    )
    assert disabled.job_fit is None
    assert enabled.resume is not None and disabled.resume is not None
    assert enabled.resume.text == disabled.resume.text
    assert enabled.cover_letter is not None and disabled.cover_letter is not None
    assert enabled.cover_letter.text == disabled.cover_letter.text


def test_job_fit_json_round_trip() -> None:
    kit = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        use_llm=False,
    )
    restored = application_kit_from_dict(application_kit_to_dict(kit))
    assert restored.job_fit == kit.job_fit


GAP_JD = (
    "Job Title: Director of Platform\nCompany: Vantage Analytics\nRequired qualifications:\n"
    "- Python\n- Kubernetes\n- Rust\nPreferred qualifications:\n- AWS\n"
    "The platform uses Python, Kubernetes, Rust, and AWS."
)


@pytest.mark.parametrize(
    "attack",
    [
        "Rust is a proven strength.",
        "Tableau adjacency gives the candidate Power BI expertise.",
        "The candidate worked at Vantage Analytics.",
        "The candidate previously served as Director of Platform.",
        "The candidate delivered a 47% improvement.",
        "The candidate led 20 engineers.",
        "The candidate holds an AWS Certified Solutions Architect certification.",
        "Kubernetes is a proven strength.",
        "The candidate has five years of production Kubernetes experience.",
        "Requirement coverage: 95.00%. Fit band: strong.",
        "There are no meaningful gaps.",
        "Ｒｕｓｔ is proven expertise.",
        "Kubernetes is a transferable hands-on capability.",
    ],
)
def test_adversarial_provider_cannot_override_structured_job_fit(attack: str) -> None:
    deterministic = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=GAP_JD,
        use_llm=False,
    )
    assert deterministic.job_fit is not None
    prefix = (
        f"Requirement coverage: {deterministic.job_fit.requirement_coverage_score:.2f}%. "
        f"Fit band: {deterministic.job_fit.fit_band.value}. "
    )
    kit = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=GAP_JD,
        use_llm=True,
        prose_provider=JobFitProvider(prefix + attack),
    )
    artifact = kit.job_fit
    assert artifact is not None
    final = artifact.summary.casefold()
    assert attack.casefold() not in final
    assert artifact.requirement_coverage_score == deterministic.job_fit.requirement_coverage_score
    assert artifact.fit_band is deterministic.job_fit.fit_band
    assert {item.requirement for item in artifact.requirements} == {
        item.requirement for item in deterministic.job_fit.requirements
    }
    assert artifact.must_have_gaps
    assert all(gap.casefold() in final for gap in artifact.must_have_gaps)
    assert artifact.validation.status.value == "repaired"
    assert artifact.validation.warnings or any(claim.status.value == "repaired" for claim in artifact.claims)
    assert not any(
        claim.status.value == "supported" and attack.casefold() in claim.text.casefold() for claim in artifact.claims
    )


def test_mixed_provider_paragraph_preserves_supported_fact_and_removes_fabrication() -> None:
    deterministic = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        use_llm=False,
    )
    assert deterministic.job_fit is not None
    narrative = (
        f"Requirement coverage: {deterministic.job_fit.requirement_coverage_score:.2f}%. "
        f"Fit band: {deterministic.job_fit.fit_band.value}. "
        "The candidate's Python and SQL work at Northstar Analytics is directly relevant. "
        "The candidate also improved revenue by 47%."
    )
    kit = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        use_llm=True,
        prose_provider=JobFitProvider(narrative),
    )
    assert kit.job_fit is not None
    assert "Northstar Analytics" in kit.job_fit.summary
    assert "Python" in kit.job_fit.summary
    assert "47%" not in kit.job_fit.summary
    assert kit.job_fit.validation.status.value == "repaired"
