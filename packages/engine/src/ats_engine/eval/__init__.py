from __future__ import annotations

from dataclasses import dataclass, field

from ats_engine.kit import SCHEMA_VERSION, ApplicationKit, generate_application_kit
from ats_engine.models import Mode

"""Grounding, JobFit, and InterviewPrep quality-evaluation harness.

A small, maintainable set of synthetic candidate/JD cases that measure the
*properties that matter* for Phase 2B2 rather than an opaque "AI quality score":

- **truth-grounding violations** — any forbidden (never-in-evidence) value that
  reached a final artifact (must be zero);
- **supported-claim preservation** — expected real facts that survived;
- **required-artifact presence** — the requested artifacts exist;
- **validation state** — whether the kit came back fatally invalid;
- **contract correctness** — the versioned schema is present.

It runs fully deterministically (``provider=None``) so it is reproducible and
CI-safe, and it is structured so a future phase can run the same cases against a
real provider (or several) and compare the same properties. Run it with:

    python -m ats_engine.eval
"""


@dataclass(slots=True)
class EvalCase:
    """One synthetic evaluation scenario."""

    name: str
    resume: str
    jd: str
    mode: Mode
    # Real facts that should survive into the final artifacts.
    expect_present: list[str] = field(default_factory=list)
    # Values that are NOT in the candidate evidence and must never appear.
    forbidden: list[str] = field(default_factory=list)
    expect_job_fit_strengths: list[str] = field(default_factory=list)
    expect_job_fit_gaps: list[str] = field(default_factory=list)
    expect_must_have_gaps: list[str] = field(default_factory=list)
    expect_complete_star: bool = False
    expect_incomplete_star: bool = False


@dataclass(slots=True)
class CaseResult:
    name: str
    schema_ok: bool
    artifact_present: bool
    preserved: list[str]
    missing_supported: list[str]
    truth_violations: list[str]
    validation_fatal: bool
    job_fit_present: bool
    job_fit_consistent: bool
    missing_job_fit_expectations: list[str]
    interview_prep_present: bool
    interview_prep_consistent: bool
    interview_star_integrity: bool
    interview_gap_visibility: bool
    interview_truth_violations: list[str]

    @property
    def passed(self) -> bool:
        return (
            self.schema_ok
            and self.artifact_present
            and self.job_fit_present
            and self.job_fit_consistent
            and not self.truth_violations
            and not self.missing_supported
            and not self.missing_job_fit_expectations
            and self.interview_prep_present
            and self.interview_prep_consistent
            and self.interview_star_integrity
            and self.interview_gap_visibility
            and not self.interview_truth_violations
        )


def _artifact_texts(kit: ApplicationKit) -> str:
    parts: list[str] = []
    if kit.resume is not None:
        parts.append(kit.resume.text)
    if kit.cover_letter is not None:
        parts.append(kit.cover_letter.text)
    if kit.answers is not None:
        parts.append(kit.answers.text)
    # Honest gap names in JobFit are not candidate claims and therefore are not
    # compared with the generic forbidden-value list. JobFit truth is evaluated
    # through its structured classifications and consistency result below.
    return "\n".join(parts).lower()


def _requested_artifact_present(kit: ApplicationKit) -> bool:
    mode = kit.resolved_mode
    if mode in {Mode.RESUME.value, Mode.RESUME_AND_COVER.value, Mode.RESUME_AND_QUESTIONS.value}:
        if kit.resume is None:
            return False
    if mode in {Mode.COVER_LETTER.value, Mode.RESUME_AND_COVER.value} and kit.cover_letter is None:
        return False
    return not (mode in {Mode.QUESTIONS.value, Mode.RESUME_AND_QUESTIONS.value} and kit.answers is None)


def run_case(case: EvalCase) -> CaseResult:
    """Generate a deterministic kit for one case and evaluate its properties."""
    kit = generate_application_kit(
        resume_text=case.resume,
        job_description=case.jd,
        default_mode=case.mode,
        use_llm=False,
    )
    text = _artifact_texts(kit)
    preserved = [fact for fact in case.expect_present if fact.lower() in text]
    missing = [fact for fact in case.expect_present if fact.lower() not in text]
    violations = [value for value in case.forbidden if value.lower() in text]
    job_fit = kit.job_fit
    interview = kit.interview_prep
    missing_fit: list[str] = []
    if job_fit is not None:
        strengths = {value.casefold() for value in job_fit.strongest_matches}
        gaps = {value.casefold() for value in job_fit.genuine_gaps}
        must_gaps = {value.casefold() for value in job_fit.must_have_gaps}
        missing_fit.extend(
            f"strength:{value}" for value in case.expect_job_fit_strengths if value.casefold() not in strengths
        )
        missing_fit.extend(f"gap:{value}" for value in case.expect_job_fit_gaps if value.casefold() not in gaps)
        missing_fit.extend(
            f"must-have-gap:{value}" for value in case.expect_must_have_gaps if value.casefold() not in must_gaps
        )
    star_integrity = False
    gap_visibility = False
    interview_truth_violations: list[str] = []
    if interview is not None:
        star_integrity = all(
            (
                story.completeness.value == "incomplete"
                or (all((story.situation, story.task, story.action, story.result)) and not story.missing_components)
            )
            and len({ref.locator.rsplit(":bullet", 1)[0] for ref in story.evidence}) <= 1
            for story in interview.star_stories
        )
        if case.expect_complete_star:
            star_integrity = star_integrity and any(
                story.completeness.value == "complete" for story in interview.star_stories
            )
        if case.expect_incomplete_star:
            star_integrity = star_integrity and any(
                story.completeness.value == "incomplete" for story in interview.star_stories
            )
        handled = {item.requirement.casefold() for item in interview.gap_handling}
        expected_gaps = {item.casefold() for item in case.expect_job_fit_gaps + case.expect_must_have_gaps}
        gap_visibility = expected_gaps <= handled
        interview_truth_violations = [
            claim.text for claim in interview.claims if claim.status.value == "supported" and not claim.evidence
        ]
    return CaseResult(
        name=case.name,
        schema_ok=kit.schema_version == SCHEMA_VERSION,
        artifact_present=_requested_artifact_present(kit),
        preserved=preserved,
        missing_supported=missing,
        truth_violations=violations,
        validation_fatal=kit.validation.fatal,
        job_fit_present=job_fit is not None,
        job_fit_consistent=bool(job_fit and job_fit.consistency.passed and not job_fit.withheld),
        missing_job_fit_expectations=missing_fit,
        interview_prep_present=interview is not None,
        interview_prep_consistent=bool(interview and interview.consistency.passed and not interview.withheld),
        interview_star_integrity=star_integrity,
        interview_gap_visibility=gap_visibility,
        interview_truth_violations=interview_truth_violations,
    )


def run_all() -> list[CaseResult]:
    return [run_case(case) for case in CASES]


def format_report(results: list[CaseResult]) -> str:
    lines = ["Phase 2B2 grounding + JobFit + InterviewPrep evaluation", "=" * 55]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(
            f"[{status}] {result.name}: "
            f"preserved {len(result.preserved)}/{len(result.preserved) + len(result.missing_supported)}, "
            f"violations {len(result.truth_violations)}, "
            f"fit_consistent={result.job_fit_consistent}, "
            f"interview_consistent={result.interview_prep_consistent}, "
            f"star_integrity={result.interview_star_integrity}, fatal={result.validation_fatal}"
        )
        if result.truth_violations:
            lines.append(f"    truth-grounding violations: {result.truth_violations}")
        if result.missing_supported:
            lines.append(f"    missing supported facts: {result.missing_supported}")
        if result.missing_job_fit_expectations:
            lines.append(f"    missing JobFit expectations: {result.missing_job_fit_expectations}")
        if result.interview_truth_violations:
            lines.append(f"    interview truth violations: {result.interview_truth_violations}")
    passed = sum(1 for result in results if result.passed)
    total_violations = sum(len(result.truth_violations) for result in results)
    lines.append("-" * 32)
    lines.append(f"{passed}/{len(results)} cases passed; {total_violations} total truth-grounding violations")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Synthetic evaluation cases (no real candidate data)
# --------------------------------------------------------------------------- #
_STRONG_RESUME = (
    "Sam Carter\nsam.carter@example.com\nPROFESSIONAL EXPERIENCE\n"
    "Meridian Data Toronto, ON\nSenior Data Engineer 2019 - 2024\n"
    "- Built Python and SQL ETL pipelines on PostgreSQL, cutting report time by 35%.\n"
    "- Delivered Tableau dashboards for finance and operations teams.\n"
    "EDUCATION\nCarleton University\nBachelor of Computer Science 2015 - 2019\n"
)
_STRONG_JD = (
    "Job Title: Data Engineer\nCompany: Vantage\nRequired qualifications:\n"
    "- Python, SQL, PostgreSQL, ETL\n- Tableau dashboards\nThe team uses Python, SQL, PostgreSQL, Tableau."
)

_SPARSE_RESUME = (
    "Riley Kim\nriley.kim@example.com\nPROFESSIONAL EXPERIENCE\n"
    "Cedar Retail Ottawa, ON\nData Analyst 2021 - 2023\n- Built weekly SQL reports for store managers.\n"
    "EDUCATION\nAlgonquin College\nDiploma in Business Analytics 2019 - 2021\n"
)
_METRIC_RESUME = (
    "Jordan Blake\njordan.blake@example.com\nPROFESSIONAL EXPERIENCE\n"
    "Northwind Labs Toronto, ON\nAnalytics Engineer 2018 - 2024\n"
    "- Cut pipeline latency by 60% and reduced cloud spend by 25% using Python and SQL.\n"
    "- Maintained 99.9% uptime across reporting services for millions of events.\n"
    "EDUCATION\nMetro University\nBachelor of Data Science 2014 - 2018\n"
)
_GENERIC_JD = (
    "Job Title: Analytics Engineer\nCompany: Beacon\nRequired qualifications:\n"
    "- Python and SQL\n- Cloud data pipelines\n- Rust and Kubernetes\nThe team uses Python, SQL, Rust, Kubernetes."
)

CASES: list[EvalCase] = [
    EvalCase(
        name="strongly-aligned",
        resume=_STRONG_RESUME,
        jd=_STRONG_JD,
        mode=Mode.RESUME_AND_COVER,
        expect_present=["Meridian Data", "Python", "SQL", "35%", "Bachelor"],
        forbidden=["Google", "PhD", "Rust"],
        expect_job_fit_strengths=["python", "sql", "postgresql", "etl", "tableau"],
    ),
    EvalCase(
        name="partially-aligned",
        resume=_STRONG_RESUME,
        jd=_GENERIC_JD,  # asks for Rust/Kubernetes the candidate lacks
        mode=Mode.RESUME_AND_COVER,
        expect_present=["Python", "SQL"],
        forbidden=["expert in Rust", "Kubernetes expert"],
        expect_job_fit_strengths=["python", "sql"],
        expect_job_fit_gaps=["rust", "kubernetes"],
        expect_must_have_gaps=["rust", "kubernetes"],
    ),
    EvalCase(
        name="genuine-gaps",
        resume=_SPARSE_RESUME,
        jd=_GENERIC_JD,
        mode=Mode.RESUME,
        expect_present=["Cedar Retail", "SQL"],
        forbidden=["Rust", "Kubernetes", "Python expert"],
        expect_job_fit_gaps=["python", "rust", "kubernetes"],
    ),
    EvalCase(
        name="adjacent-skills",
        resume=_STRONG_RESUME,
        jd="Job Title: BI Developer\nCompany: Vantage\nRequired qualifications:\n- Power BI\n- Snowflake\nThe team uses Power BI and Snowflake.",
        mode=Mode.RESUME,
        expect_present=["Tableau"],  # real adjacent tool
        forbidden=["expert in Power BI", "Snowflake certified"],
    ),
    EvalCase(
        name="sparse-resume",
        resume=_SPARSE_RESUME,
        jd=_STRONG_JD,
        mode=Mode.RESUME_AND_COVER,
        expect_present=["Cedar Retail"],
        forbidden=["PostgreSQL expert", "10 years"],
    ),
    EvalCase(
        name="metric-rich",
        resume=_METRIC_RESUME,
        jd=_STRONG_JD,
        mode=Mode.RESUME,
        expect_present=["60%", "25%", "Python"],
        forbidden=["Google", "$5 million", "PhD"],
    ),
    EvalCase(
        name="working-knowledge",
        resume=(
            "Taylor Chen\nTECHNICAL SKILLS\nKubernetes\nPROFESSIONAL EXPERIENCE\n"
            "Cedar Labs Toronto, ON\nData Analyst 2022 - 2024\n- Built SQL reports.\n"
        ),
        jd=(
            "Job Title: Platform Analyst\nCompany: Beacon\nRequired qualifications:\n- Kubernetes\n"
            "The platform uses Kubernetes."
        ),
        mode=Mode.RESUME,
        expect_present=["Working knowledge", "Kubernetes"],
    ),
    EvalCase(
        name="must-have-gap",
        resume=_STRONG_RESUME,
        jd=(
            "Job Title: Platform Engineer\nCompany: Beacon\nRequired qualifications:\n- Kubernetes\n- Rust\n"
            "The platform uses Kubernetes and Rust."
        ),
        mode=Mode.RESUME,
        expect_job_fit_gaps=["kubernetes", "rust"],
        expect_must_have_gaps=["kubernetes", "rust"],
        forbidden=["Kubernetes expert", "Rust expert"],
    ),
    EvalCase(
        name="complete-star-evidence",
        resume=(
            "Casey Park\nPROFESSIONAL EXPERIENCE\nAster Labs Toronto, ON\nData Engineer 2020 - 2024\n"
            "- Situation: Reports were delayed. Task: Improve delivery. Action: Built Python and SQL pipelines. Result: Reduced report time by 35%.\n"
        ),
        jd=_GENERIC_JD,
        mode=Mode.RESUME,
        expect_present=["Python", "SQL", "35%"],
        expect_complete_star=True,
    ),
    EvalCase(
        name="incomplete-star-evidence",
        resume=(
            "Casey Park\nPROFESSIONAL EXPERIENCE\nAster Labs Toronto, ON\nData Engineer 2020 - 2024\n"
            "- Built Python and SQL pipelines for reporting.\n"
        ),
        jd=_GENERIC_JD,
        mode=Mode.RESUME,
        expect_present=["Python", "SQL"],
        expect_incomplete_star=True,
    ),
]
