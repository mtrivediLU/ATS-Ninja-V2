from __future__ import annotations

from ats_engine.generation.document_normalization import normalize_document_text
from ats_engine.kit.contract import CoverLetterDocument, ResumeDocument

"""Deterministic plain-text rendering from the persisted structured documents.

The initial kit text is rendered from the in-memory :class:`ResumePlan` /
:class:`CoverLetterPlan`. After a v5 change action the plan is no longer in
scope, so the delivered plain text is re-rendered from the persisted, structured
:class:`ResumeDocument` / :class:`CoverLetterDocument` — the authoritative
reversible state a change action mutates. Content is identical; only the source
of the render differs. No candidate fact is inferred here.
"""


def render_resume_text_from_document(document: ResumeDocument) -> str:
    """Render a parseable plain-text resume from the structured document."""
    lines: list[str] = ["Candidate Header"]
    if document.professional_headline:
        lines.append(f"Professional Headline: {document.professional_headline}")
    lines.extend(document.contact_lines)

    if document.summary:
        lines.extend(["", "Professional Summary", document.summary])

    if document.skill_groups:
        lines.extend(["", "Technical Skills"])
        for group in document.skill_groups:
            if group.items:
                lines.append(f"{group.label}: {', '.join(group.items)}")

    if document.experience:
        lines.extend(["", "Professional Experience"])
        for entry in document.experience:
            lines.append(
                _field_line(
                    [
                        ("Company", entry.employer),
                        ("Location", entry.location),
                        ("Title", entry.title),
                        ("Dates", entry.date_range),
                    ]
                )
            )
            for bullet in entry.bullets:
                if bullet.strip():
                    lines.append(f"- {bullet}")
            lines.append("")

    if document.education:
        lines.append("Education")
        for education in document.education:
            lines.append(
                _field_line(
                    [
                        ("Institution", education.institution),
                        ("Location", education.location),
                        ("Degree", education.degree),
                        ("Dates", education.date_range),
                    ]
                )
            )
            for detail in education.details:
                if detail.strip():
                    lines.append(f"- {detail}")

    if document.certifications:
        lines.extend(["", "Certifications"])
        for cert in document.certifications:
            parts = [cert.name]
            if cert.date:
                parts.append(cert.date)
            if cert.link:
                parts.append(cert.link)
            lines.append("- " + " | ".join(parts))

    return normalize_document_text("\n".join(lines).strip())


def render_cover_letter_text_from_document(document: CoverLetterDocument) -> str:
    """Render plain-text cover-letter body paragraphs from the structured document."""
    paragraphs = [paragraph for paragraph in document.body_paragraphs if paragraph.strip()]
    return normalize_document_text("\n\n".join(paragraphs).strip())


def _field_line(fields: list[tuple[str, str]]) -> str:
    return " | ".join(f"{label}: {value}" for label, value in fields if value)
