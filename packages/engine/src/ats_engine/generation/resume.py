from __future__ import annotations

from ats_engine.generation.document_normalization import normalize_document_text
from ats_engine.generation.latex_renderer import resume_to_latex
from ats_engine.models import ResumePlan
from ats_engine.validation.repair import soften_banned_style


def generate_resume_text(plan: ResumePlan) -> str:
    """Render the structured resume plan into parseable resume text."""
    contact = plan.contacts
    lines: list[str] = [
        "Candidate Header",
        f"Professional Headline: {plan.headline}",
    ]
    for label, value in [
        ("Location", contact.location),
        ("LinkedIn", contact.linkedin),
        ("Portfolio", contact.website),
        ("Work Authorization", contact.work_authorization),
        ("Relocation", contact.relocation),
    ]:
        if value:
            lines.append(f"{label}: {value}")

    lines.extend(["", "Professional Summary", plan.summary, "", "Technical Skills"])
    for category, items in plan.skill_groups:
        lines.append(f"{category}: {', '.join(items)}")

    lines.extend(["", "Professional Experience"])
    for entry in plan.experience:
        lines.append(
            _field_line(
                [
                    ("Company", entry.company),
                    ("Location", entry.location),
                    ("Title", entry.title),
                    ("Dates", entry.dates),
                ]
            )
        )
        for bullet in entry.bullets:
            lines.append(f"- {bullet}")
        lines.append("")

    lines.append("Education")
    for education in plan.education:
        lines.append(
            _field_line(
                [
                    ("Institution", education.institution),
                    ("Location", education.location),
                    ("Degree", education.degree),
                    ("Dates", education.dates),
                ]
            )
        )
        for bullet in education.bullets:
            lines.append(f"- {bullet}")
    lines.extend(["", "Certifications"])
    for cert in plan.certifications:
        parts = [cert.name]
        if cert.date:
            parts.append(cert.date)
        if cert.link:
            parts.append(cert.link)
        lines.append("- " + " | ".join(parts))
    return normalize_document_text(soften_banned_style(_strip_banned_dashes("\n".join(lines).strip())))


def generate_resume_latex(plan: ResumePlan) -> str:
    """Produce a complete Overleaf-ready LaTeX resume."""
    user_info = _user_info(plan)
    return _strip_banned_dashes(resume_to_latex(generate_resume_text(plan), user_info)).strip()


def format_resume_output(plan: ResumePlan, latex_code: str) -> str:
    """Format Mode R output exactly."""
    role = f"{plan.jd_profile.title} at {plan.jd_profile.company}"
    analysis = "\n".join(plan.analysis[:4])
    return (
        f"**Role:** {role}\n"
        f"**Interview Call Probability:** {plan.interview_probability}%\n"
        f"**Analysis:** {analysis}\n"
        "```latex\n"
        f"{latex_code.strip()}\n"
        "```"
    )


def _user_info(plan: ResumePlan) -> dict[str, str]:
    contact = plan.contacts
    return {
        "name": contact.name,
        "email": contact.email,
        "phone": contact.phone,
        "headline": plan.headline,
        "location": contact.location,
        "linkedin": contact.linkedin,
        "portfolio": contact.website,
        "work_authorization": contact.work_authorization,
        "relocation": contact.relocation,
    }


def _strip_banned_dashes(text: str) -> str:
    return text.replace("—", ",").replace("–", " to ").replace("--", "-")


def _field_line(fields: list[tuple[str, str]]) -> str:
    return " | ".join(f"{label}: {value}" for label, value in fields if value)
