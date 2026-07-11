from __future__ import annotations

from dataclasses import dataclass, field

from ats_engine.kit import SCHEMA_VERSION, ApplicationKit, generate_application_kit
from ats_engine.models import Mode

"""Phase 2A quality-evaluation harness.

A small, maintainable set of synthetic candidate/JD cases that measure the
*properties that matter* for Phase 2A rather than an opaque "AI quality score":

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


@dataclass(slots=True)
class CaseResult:
    name: str
    schema_ok: bool
    artifact_present: bool
    preserved: list[str]
    missing_supported: list[str]
    truth_violations: list[str]
    validation_fatal: bool

    @property
    def passed(self) -> bool:
        return self.schema_ok and self.artifact_present and not self.truth_violations and not self.missing_supported


def _artifact_texts(kit: ApplicationKit) -> str:
    parts: list[str] = []
    if kit.resume is not None:
        parts.append(kit.resume.text)
    if kit.cover_letter is not None:
        parts.append(kit.cover_letter.text)
    if kit.answers is not None:
        parts.append(kit.answers.text)
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
    return CaseResult(
        name=case.name,
        schema_ok=kit.schema_version == SCHEMA_VERSION,
        artifact_present=_requested_artifact_present(kit),
        preserved=preserved,
        missing_supported=missing,
        truth_violations=violations,
        validation_fatal=kit.validation.fatal,
    )


def run_all() -> list[CaseResult]:
    return [run_case(case) for case in CASES]


def format_report(results: list[CaseResult]) -> str:
    lines = ["Phase 2A quality evaluation", "=" * 32]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(
            f"[{status}] {result.name}: "
            f"preserved {len(result.preserved)}/{len(result.preserved) + len(result.missing_supported)}, "
            f"violations {len(result.truth_violations)}, "
            f"fatal={result.validation_fatal}"
        )
        if result.truth_violations:
            lines.append(f"    truth-grounding violations: {result.truth_violations}")
        if result.missing_supported:
            lines.append(f"    missing supported facts: {result.missing_supported}")
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
    ),
    EvalCase(
        name="partially-aligned",
        resume=_STRONG_RESUME,
        jd=_GENERIC_JD,  # asks for Rust/Kubernetes the candidate lacks
        mode=Mode.RESUME_AND_COVER,
        expect_present=["Python", "SQL"],
        forbidden=["expert in Rust", "Kubernetes expert"],
    ),
    EvalCase(
        name="genuine-gaps",
        resume=_SPARSE_RESUME,
        jd=_GENERIC_JD,
        mode=Mode.RESUME,
        expect_present=["Cedar Retail", "SQL"],
        forbidden=["Rust", "Kubernetes", "Python expert"],
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
]
