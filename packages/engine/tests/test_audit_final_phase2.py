from __future__ import annotations

from ats_engine import Mode, RequirementClassification, generate_application_kit
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import term_in_text_affirmative

"""Regression tests for defects found by the independent final Phase 2 audit.

Both defects were confirmed against the FINAL ApplicationKit (not merely
detected by an internal validator), fixed with the smallest scoped change, and
verified to introduce zero regressions across the full engine suite.
"""

# --------------------------------------------------------------------------- #
# Finding 1 (CRITICAL): negation/aspiration bypass in evidence tiering.
#
# The deterministic evidence-tier "bullet backstop" (evidence/matrix.py) and the
# candidate-self-listed-skill tiering (parsing/resume.py::_tier_skills) treated
# ANY word-boundary match of a JD keyword in a candidate bullet as proof of a
# proven skill — with no awareness of negation ("I have no Kubernetes
# experience") or aspiration ("currently exploring Rust", "interested in AWS
# certification but not yet certified"). Because resume "Technical Skills" /
# "Professional Headline" / "Professional Summary" sections are rendered
# directly from this tiering and are NEVER passed through the AI-prose grounding
# gate (ats_engine.kit.grounding only grounds LLM-touched text), a fabricated
# "proven" skill reached the final resume, JobFitArtifact, InterviewPrepArtifact,
# and LinkedInOutreachArtifact with ZERO claim trace and ZERO repair — even on
# the fully deterministic, provider=None path.
# --------------------------------------------------------------------------- #

NEGATION_ASPIRATION_RESUME = (
    "Sam Lee\n"
    "sam.lee@example.com | linkedin.com/in/samlee\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Northstar Analytics Toronto, ON\n"
    "Data Analyst 2022 - 2024\n"
    "- Built dashboards using Python and SQL; I have no Kubernetes experience and did not lead the team.\n"
    "- Currently exploring Rust in my spare time; interested in AWS certification but not yet certified.\n"
    "EDUCATION\n"
    "Carleton University\n"
    "Bachelor of Computer Science 2018 - 2022\n"
)

AFFIRMATIVE_SKILL_RESUME = (
    "Alex Kim\n"
    "alex.kim@example.com\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Northstar Analytics Toronto, ON\n"
    "Data Analyst 2022 - 2024\n"
    "- Built dashboards using Python and SQL with Kubernetes for deployment automation.\n"
    "EDUCATION\n"
    "Carleton University\n"
    "Bachelor of Computer Science 2018 - 2022\n"
)

KUBERNETES_JD = (
    "Job Title: Platform Engineer\n"
    "Company: Vantage Analytics\n"
    "Required qualifications:\n"
    "- Kubernetes\n"
    "- Rust\n"
    "- AWS certification\n"
    "The team uses Kubernetes, Rust, and AWS."
)


def test_negated_skill_is_not_tiered_as_proven() -> None:
    kit = generate_application_kit(
        resume_text=NEGATION_ASPIRATION_RESUME,
        job_description=KUBERNETES_JD,
        default_mode=Mode.RESUME_AND_QUESTIONS,
        questions_text="Describe your technical background.",
        use_llm=False,
    )
    assert kit.job_fit is not None
    classifications = {item.requirement.lower(): item.classification for item in kit.job_fit.requirements}
    assert classifications["kubernetes"] is RequirementClassification.GENUINE_GAP
    assert classifications["aws"] is RequirementClassification.GENUINE_GAP
    assert classifications["rust"] is RequirementClassification.GENUINE_GAP


def test_negated_skill_does_not_survive_final_resume_text() -> None:
    """The core regression: the FINAL resume must not present a negated/aspirational
    skill as a headline, summary, or Core Skills claim."""
    kit = generate_application_kit(
        resume_text=NEGATION_ASPIRATION_RESUME,
        job_description=KUBERNETES_JD,
        default_mode=Mode.RESUME,
        use_llm=False,
    )
    assert kit.resume is not None
    text = kit.resume.text.lower()
    # The candidate's own honest bullet text is still allowed to appear (it IS
    # what they wrote), but the fabricated headline/summary/skills claims are not.
    headline = text.split("\n")[1]
    assert "kubernetes" not in headline and "aws" not in headline and "rust" not in headline
    assert "core skills: kubernetes" not in text
    assert "working across kubernetes" not in text


def test_aspirational_skill_does_not_survive_final_resume_text() -> None:
    kit = generate_application_kit(
        resume_text=NEGATION_ASPIRATION_RESUME,
        job_description=KUBERNETES_JD,
        default_mode=Mode.RESUME,
        use_llm=False,
    )
    assert kit.resume is not None
    skills_section = kit.resume.text.lower().split("technical skills")[1].split("professional experience")[0]
    assert "rust" not in skills_section
    assert "aws" not in skills_section


def test_affirmative_skill_still_classified_proven_after_negation_fix() -> None:
    """Over-removal guard: a genuinely-claimed skill (no negation nearby) must
    still be tiered as proven and must still appear in the final resume."""
    kit = generate_application_kit(
        resume_text=AFFIRMATIVE_SKILL_RESUME,
        job_description=KUBERNETES_JD,
        default_mode=Mode.RESUME,
        use_llm=False,
    )
    assert kit.job_fit is not None
    classifications = {item.requirement.lower(): item.classification for item in kit.job_fit.requirements}
    assert classifications["kubernetes"] is RequirementClassification.PROVEN
    assert kit.resume is not None
    assert "kubernetes" in kit.resume.text.lower()


def test_term_in_text_affirmative_unit_behavior() -> None:
    """Direct unit coverage of the shared negation/aspiration-aware helper."""
    assert term_in_text_affirmative("kubernetes", "Built systems using Kubernetes for deployment.")
    assert not term_in_text_affirmative("kubernetes", "I have no Kubernetes experience.")
    assert not term_in_text_affirmative("kubernetes", "did not use Kubernetes in this role.")
    assert not term_in_text_affirmative("rust", "Currently exploring Rust in my spare time.")
    assert not term_in_text_affirmative("aws", "Interested in AWS certification but not yet certified.")
    # A negation elsewhere in a different clause must not suppress real evidence
    # in another clause of the same text.
    assert term_in_text_affirmative("python", "I have no Kubernetes experience. Built dashboards using Python and SQL.")
    # Case-insensitivity is preserved (matches prior behavior of both call sites).
    assert term_in_text_affirmative("kubernetes", "Built systems using KUBERNETES for deployment.")


# --------------------------------------------------------------------------- #
# Finding 2: required/preferred JD section-heading collision.
#
# The heuristic JD section extractor used "qualifications" as a generic start
# heading for the REQUIRED section. Because "Preferred qualifications:" also
# contains the word "qualifications", it matched the required-section start
# condition before the section-boundary break check ever ran, so the entire
# preferred section (and a trailing descriptive sentence) was absorbed into
# required_qualifications — inflating a merely-preferred JD item into a
# JobFitArtifact "must-have gap" with RequirementRisk.MUST_HAVE_GAP.
# --------------------------------------------------------------------------- #

REQUIRED_PREFERRED_JD = (
    "Job Title: Senior Data Engineer\n"
    "Company: Vantage Analytics\n"
    "Required qualifications:\n"
    "- Python and SQL for data systems\n"
    "- Snowflake data warehouse experience\n"
    "- Kubernetes container orchestration\n"
    "Preferred qualifications:\n"
    "- Docker containerization\n"
    "The team uses Python, SQL, Snowflake, Kubernetes, and Docker."
)

RICH_RESUME = (
    "Priya Shah\n"
    "priya.shah@example.com\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Northstar Analytics Toronto, ON\n"
    "Data Analyst 2022 - 2024\n"
    "- Built dashboards and SQL reporting using Python and PostgreSQL, reducing manual reporting time by 30%.\n"
    "TECHNICAL SKILLS\n"
    "Python, SQL, PostgreSQL, Tableau, Docker\n"
    "EDUCATION\n"
    "Carleton University Ottawa, ON\n"
    "Bachelor of Computer Science 2018 - 2022\n"
)


def test_preferred_heading_does_not_leak_into_required_qualifications() -> None:
    jd = parse_jd(REQUIRED_PREFERRED_JD, profile=None, provider=None)
    required_text = " ".join(jd.required_qualifications).lower()
    assert "docker" not in required_text
    assert "the team uses" not in required_text
    assert any("kubernetes" in line.lower() for line in jd.required_qualifications)


def test_preferred_only_requirement_is_not_reported_as_must_have_gap() -> None:
    kit = generate_application_kit(
        resume_text=RICH_RESUME,
        job_description=REQUIRED_PREFERRED_JD,
        default_mode=Mode.RESUME,
        use_llm=False,
    )
    assert kit.job_fit is not None
    docker = next(item for item in kit.job_fit.requirements if item.requirement.lower() == "docker")
    assert docker.must_have is False
    assert docker.requirement not in kit.job_fit.must_have_gaps


def test_required_only_requirement_is_still_must_have() -> None:
    kit = generate_application_kit(
        resume_text=RICH_RESUME,
        job_description=REQUIRED_PREFERRED_JD,
        default_mode=Mode.RESUME,
        use_llm=False,
    )
    assert kit.job_fit is not None
    kubernetes = next(item for item in kit.job_fit.requirements if item.requirement.lower() == "kubernetes")
    assert kubernetes.must_have is True
    assert kubernetes.requirement in kit.job_fit.must_have_gaps
