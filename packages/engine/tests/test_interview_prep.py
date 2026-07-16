from __future__ import annotations

import hashlib
import json

import pytest

from ats_engine import (
    Mode,
    RequirementClassification,
    StarCompleteness,
    application_kit_from_dict,
    application_kit_to_dict,
    generate_application_kit,
)
from ats_engine.parsing import parse_jd
from ats_engine.providers import LLMProvider

INTERVIEW_RESUME = (
    "Morgan Lee\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Harbor Data Toronto, ON\n"
    "Data Analyst 2021 - 2025\n"
    "- Situation: Reporting was slow. Task: Improve analyst access. Action: Built Python and SQL pipelines. Result: Reduced reporting time by 30%.\n"
    "- Supported a migration and delivered Tableau dashboards for operations.\n"
    "Lake Systems Ottawa, ON\n"
    "Software Associate 2019 - 2021\n"
    "- Contributed SQL documentation for internal teams.\n"
    "EDUCATION\n"
    "Metro University Ottawa, ON\n"
    "Bachelor of Computer Science 2015 - 2019\n"
    "- Project: Built a Python scheduling prototype for a capstone course.\n"
    "TECHNICAL SKILLS\n"
    "Kubernetes\n"
    "CERTIFICATIONS\n"
    "Certified Data Foundations 2024\n"
)

INTERVIEW_JD = (
    "Job Title: Director of Platform\n"
    "Company: Vantage Analytics\n"
    "Required qualifications:\n"
    "- Python\n- SQL\n- Power BI\n- Kubernetes\n- Rust\n"
    "Responsibilities:\n- Build analytics platforms and partner with business stakeholders.\n"
    "The team uses Python, SQL, Power BI, Kubernetes, and Rust.\n"
)


class InterviewProvider(LLMProvider):
    def __init__(self, strategy: str) -> None:
        self.strategy = strategy
        self._identity = "interview:" + hashlib.sha256(strategy.encode()).hexdigest()[:12]

    @property
    def identity(self) -> str:
        return self._identity

    def complete(self, prompt: str) -> str:
        return self.strategy if "INTERVIEW STRATEGY SUMMARY" in prompt else ""


class JDProvider(LLMProvider):
    @property
    def identity(self) -> str:
        return "adversarial-jd"

    def complete(self, _prompt: str) -> str:
        return (
            '{"title":"Director of Platform","company":"Vantage Analytics",'
            '"required_qualification_lines":[],"preferred_qualification_lines":[8],'
            '"responsibility_lines":[10],"technical_keywords":["Rust"],'
            '"work_mode":"unknown","location":"","domain":"","ats_platform":"unknown"}'
        )


def test_provider_cannot_downgrade_deterministic_required_requirement() -> None:
    profile = parse_jd(INTERVIEW_JD, provider=JDProvider())
    assert any("Rust" in line for line in profile.required_qualifications)
    assert not any("Rust" in line for line in profile.preferred_qualifications)


def _kit(*, provider: LLMProvider | None = None, include_job_fit: bool = True) -> object:
    return generate_application_kit(
        resume_text=INTERVIEW_RESUME,
        job_description=INTERVIEW_JD,
        default_mode=Mode.RESUME,
        use_llm=provider is not None,
        prose_provider=provider,
        include_job_fit=include_job_fit,
    )


def _deliverable_text(kit: object) -> str:
    artifact = kit.interview_prep
    assert artifact is not None
    values = [artifact.strategy_summary]
    values.extend(question.question for question in artifact.questions)
    values.extend(question.rationale for question in artifact.questions)
    values.extend(question.answer_guide.suggested_answer for question in artifact.questions)
    values.extend(point for question in artifact.questions for point in question.answer_guide.key_points)
    for story in artifact.star_stories:
        values.extend((story.situation, story.task, story.action, story.result, story.safe_usage_guidance))
    values.extend(guide.guidance for guide in artifact.gap_handling)
    values.extend(question.question for question in artifact.interviewer_questions)
    return "\n".join(values).casefold()


def test_provider_none_builds_complete_useful_interview_prep() -> None:
    kit = _kit()
    artifact = kit.interview_prep
    assert artifact is not None
    assert artifact.strategy_summary
    assert artifact.focus_areas
    assert {question.category.value for question in artifact.questions} >= {
        "motivation",
        "behavioral",
        "technical",
        "role_specific",
        "problem_solving",
        "gap_clarification",
    }
    assert all(question.answer_guide.suggested_answer for question in artifact.questions)
    assert artifact.star_stories
    assert artifact.technical_study_topics
    assert artifact.gap_handling
    assert artifact.interviewer_questions
    assert artifact.validation.fatal is False
    assert artifact.consistency.passed
    assert artifact.claims
    assert all(len(ref.excerpt) <= 160 for ref in artifact.evidence)


def test_job_fit_and_interview_prep_are_independently_selectable() -> None:
    prep_only = generate_application_kit(
        resume_text=INTERVIEW_RESUME,
        job_description=INTERVIEW_JD,
        use_llm=False,
        include_job_fit=False,
        include_interview_prep=True,
    )
    fit_only = generate_application_kit(
        resume_text=INTERVIEW_RESUME,
        job_description=INTERVIEW_JD,
        use_llm=False,
        include_job_fit=True,
        include_interview_prep=False,
    )
    neither = generate_application_kit(
        resume_text=INTERVIEW_RESUME,
        job_description=INTERVIEW_JD,
        use_llm=False,
        include_job_fit=False,
        include_interview_prep=False,
    )
    assert prep_only.job_fit is None and prep_only.interview_prep is not None
    assert fit_only.job_fit is not None and fit_only.interview_prep is None
    assert neither.job_fit is None and neither.interview_prep is None


def test_interview_prep_json_round_trip() -> None:
    kit = _kit()
    raw = application_kit_to_dict(kit)
    assert raw["schema_version"] == "application-kit/v3"
    assert raw["interview_prep"]["questions"]
    restored = application_kit_from_dict(json.loads(json.dumps(raw)))
    assert restored.interview_prep == kit.interview_prep


def test_star_integrity_complete_incomplete_and_role_separation() -> None:
    artifact = _kit().interview_prep
    assert artifact is not None
    complete = [story for story in artifact.star_stories if story.completeness is StarCompleteness.COMPLETE]
    incomplete = [story for story in artifact.star_stories if story.completeness is StarCompleteness.INCOMPLETE]
    assert complete
    assert complete[0].result == "Reduced reporting time by 30%"
    assert not complete[0].missing_components
    assert incomplete
    assert all(story.missing_components for story in incomplete)
    assert all(
        len({ref.locator.rsplit(":bullet", 1)[0] for ref in story.evidence}) == 1 for story in artifact.star_stories
    )
    final = _deliverable_text(_kit())
    assert "47%" not in final
    assert "20 engineers" not in final
    assert "Project Phoenix" not in final


def test_supported_details_and_honest_boundaries_survive() -> None:
    artifact = _kit().interview_prep
    assert artifact is not None
    final = json.dumps(application_kit_to_dict(_kit())["interview_prep"], ensure_ascii=False).casefold()
    for supported in (
        "harbor data",
        "data analyst",
        "python",
        "sql",
        "30%",
        "metro university",
        "bachelor of computer science",
        "tableau",
        "kubernetes",
        "rust",
    ):
        assert supported in final
    classifications = {area.topic.casefold(): area.classification for area in artifact.focus_areas}
    assert classifications["power bi"] is RequirementClassification.ADJACENT
    assert classifications["kubernetes"] is RequirementClassification.WORKING_KNOWLEDGE
    assert classifications["rust"] is RequirementClassification.GENUINE_GAP
    assert any("not candidate experience" in topic.boundary.casefold() for topic in artifact.technical_study_topics)
    assert any("acknowledge" in guide.guidance.casefold() for guide in artifact.gap_handling)


@pytest.mark.parametrize(
    ("case", "attack", "forbidden"),
    [
        ("google-employment", "I worked at Google as an engineer.", "google"),
        ("target-employment", "I worked at Vantage Analytics before.", "worked at vantage analytics"),
        ("target-title", "I served as Director of Platform.", "served as director of platform"),
        ("invented-project", "I led Project Phoenix.", "project phoenix"),
        ("invented-metric", "I delivered a 47% improvement.", "47%"),
        ("invented-team", "I led 20 engineers.", "20 engineers"),
        ("invented-cert", "I hold an AWS Certified Solutions Architect certification.", "aws certified"),
        ("rust-gap", "I have professional experience with Rust.", "professional experience with rust"),
        ("kubernetes-upgrade", "I have five years of production Kubernetes experience.", "production kubernetes"),
        ("adjacent-upgrade", "I have Power BI expertise.", "power bi expertise"),
        ("cross-role-blend", "At Harbor Data and Lake Systems, I led one shared migration.", "one shared migration"),
        ("invented-result", "The result was record company growth.", "result was record"),
        ("support-to-led", "I led the migration described in my resume.", "i led the migration"),
        ("must-gap-omission", "Prepare the proven Python examples only.", "proven python examples only"),
        ("hide-gap", "Minimize the gap so the interviewer does not notice it.", "minimize the gap"),
        ("jd-tech-experience", "I have hands-on Rust experience.", "hands-on rust experience"),
        ("invented-company-fact", "Ask about your Project Atlas architecture initiative.", "project atlas"),
        ("mixed", "My Python work is relevant and I delivered Project Phoenix with a 47% gain.", "project phoenix"),
        ("unicode-obfuscation", "I have professional experience with R\u200bｕｓｔ.", "professional experience"),
        (
            "split-contradiction",
            "Power BI is adjacent. Elsewhere, I am a Power BI expert. Rust is a gap. I used Rust professionally.",
            "power bi expert",
        ),
    ],
)
def test_adversarial_provider_content_never_survives_final_artifact(
    case: str,
    attack: str,
    forbidden: str,
) -> None:
    del case
    kit = _kit(provider=InterviewProvider(attack))
    artifact = kit.interview_prep
    assert artifact is not None
    final = _deliverable_text(kit)
    assert forbidden.casefold() not in final
    assert "rust" in {guide.requirement.casefold() for guide in artifact.gap_handling}
    assert "rust" in {area.topic.casefold() for area in artifact.focus_areas}
    assert artifact.consistency.passed
    assert not artifact.withheld
    assert artifact.validation.status.value == "repaired"
    assert artifact.validation.warnings or any(claim.status.value == "repaired" for claim in artifact.claims)
    assert not any(
        claim.status.value == "supported" and forbidden.casefold() in claim.text.casefold() for claim in artifact.claims
    )
    assert "python" in final


@pytest.mark.parametrize(
    "resume",
    [
        "Taylor Kim\nPROFESSIONAL EXPERIENCE\nAcme Corp Toronto, ON\nAnalyst 2023 - 2024\n- Built SQL reports.\n",
        "Taylor Kim\nTECHNICAL SKILLS\nPython\n",
        INTERVIEW_RESUME,
    ],
)
def test_sparse_partial_and_metric_rich_inputs_remain_useful(resume: str) -> None:
    kit = generate_application_kit(
        resume_text=resume,
        job_description=INTERVIEW_JD,
        default_mode=Mode.RESUME,
        use_llm=False,
    )
    artifact = kit.interview_prep
    assert artifact is not None
    assert artifact.strategy_summary
    assert artifact.focus_areas
    assert artifact.questions
    assert artifact.gap_handling
    assert artifact.consistency.passed
