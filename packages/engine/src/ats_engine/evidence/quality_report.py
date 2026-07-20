from __future__ import annotations

from dataclasses import dataclass, field

from ats_engine.generation.latex_renderer import parse_resume_sections
from ats_engine.models import EvidenceItem, JDProfile, ResumePlan
from ats_engine.parsing.contact_integrity import ContactIntegrityReport, validate_contact_integrity
from ats_engine.parsing.resume import find_metrics

"""A deterministic, internal ATS-coverage report for the generated Resume.

This is NOT a JobScan score, an "AI confidence" number, or any kind of
predicted match probability — it is a transparent tally of what the grounded
evidence matrix (see ``ats_engine.evidence.matrix``) already decided, plus a
handful of structural facts (sections present, word count, measurable
results). Coverage percentages only ever count keywords with real supporting
evidence (tier A/B, "proven"); inserting an unsupported keyword never
increases the reported coverage.
"""

_SECTION_NAMES = ("summary", "experience", "education", "skills", "certifications")


@dataclass(frozen=True, slots=True)
class AtsQualityReport:
    required_term_count: int
    required_supported_count: int
    required_coverage_percent: float
    preferred_term_count: int
    preferred_supported_count: int
    preferred_coverage_percent: float
    exact_target_title_present: bool
    section_presence: dict[str, bool]
    contact_integrity: ContactIntegrityReport
    measurable_result_count: int
    word_count: int
    unsupported_requirement_count: int
    adjacency_count: int
    working_knowledge_count: int
    formatting_warnings: tuple[str, ...] = field(default_factory=tuple)


def build_ats_quality_report(
    *,
    evidence: list[EvidenceItem],
    jd_profile: JDProfile,
    resume_plan: ResumePlan,
    resume_text: str,
) -> AtsQualityReport:
    """Build the internal ATS coverage report from already-computed pipeline data."""
    required = [item for item in evidence if item.required_or_preferred == "required"]
    preferred = [item for item in evidence if item.required_or_preferred == "preferred"]

    required_supported = sum(1 for item in required if item.evidence_tier in ("A", "B"))
    preferred_supported = sum(1 for item in preferred if item.evidence_tier in ("A", "B"))

    sections = parse_resume_sections(resume_text) if resume_text else {}
    section_presence = {
        name: bool(sections.get(name)) if name != "summary" else bool(sections.get("summary"))
        for name in _SECTION_NAMES
    }

    measurable_result_count = sum(
        len(find_metrics(bullet)) for entry in resume_plan.experience for bullet in entry.bullets
    )

    formatting_warnings: list[str] = []
    if not section_presence["experience"]:
        formatting_warnings.append("no experience section detected in the rendered resume")
    if not section_presence["summary"]:
        formatting_warnings.append("no professional summary detected in the rendered resume")

    return AtsQualityReport(
        required_term_count=len(required),
        required_supported_count=required_supported,
        required_coverage_percent=_percent(required_supported, len(required)),
        preferred_term_count=len(preferred),
        preferred_supported_count=preferred_supported,
        preferred_coverage_percent=_percent(preferred_supported, len(preferred)),
        exact_target_title_present=_target_title_present(jd_profile.title, resume_plan),
        section_presence=section_presence,
        contact_integrity=validate_contact_integrity(resume_plan.contacts),
        measurable_result_count=measurable_result_count,
        word_count=len(resume_text.split()) if resume_text else 0,
        unsupported_requirement_count=sum(1 for item in required if item.evidence_tier == "missing"),
        adjacency_count=sum(1 for item in evidence if item.evidence_tier == "adjacency"),
        working_knowledge_count=sum(1 for item in evidence if item.evidence_tier == "C"),
        formatting_warnings=tuple(formatting_warnings),
    )


def _target_title_present(target_title: str, resume_plan: ResumePlan) -> bool:
    """Whether the exact target title appears in a truthful, non-history context.

    Only checks the headline/work-mode line, which are always framed as the
    candidate's target ("Targeting X opportunities..."), never the rendered
    experience section — the title must never be mistaken for a past role.
    """
    title = (target_title or "").strip().lower()
    if not title or title == "target role":
        return False
    haystack = f"{resume_plan.headline} {resume_plan.work_mode_line}".lower()
    return title in haystack


def _percent(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((count / total) * 100, 1)
