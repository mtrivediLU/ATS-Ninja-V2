from __future__ import annotations

from ats_engine.generation.delivered_layout import bullet_line, join_fields
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
            if cert.credential_id:
                parts.append(f"Credential ID: {cert.credential_id}")
            lines.append("- " + " | ".join(parts))

    return normalize_document_text("\n".join(lines).strip())


def render_delivered_resume_text(document: ResumeDocument) -> str:
    """Render the text an ATS reads out of the *delivered* resume.

    This is deliberately not the labelled ``Company: X | Location: Y`` shape
    :func:`render_resume_text_from_document` produces. That shape is a wire
    format for the LaTeX renderer, and nothing a candidate ever receives looks
    like it -- which is exactly why the tailored score used to be a projection
    of the plan rather than a measurement of the artifact. This function
    reproduces the layout the DOCX/HTML/PDF renderers emit, field for field,
    using the shared helpers in ``generation/delivered_layout.py``, so scoring
    and round-trip checks see the same text an external ATS would.
    """
    lines: list[str] = []
    if document.candidate_name:
        lines.append(document.candidate_name)
    if document.professional_headline:
        lines.append(document.professional_headline)
    if document.contact_lines:
        lines.append(join_fields(*document.contact_lines))

    if document.summary:
        lines.extend(["", "Professional Summary", document.summary])

    if document.skill_groups:
        lines.extend(["", "Technical Skills"])
        for group in document.skill_groups:
            items = [item for item in group.items if item]
            if items:
                lines.append(f"{group.label}: {', '.join(items)}" if group.label else ", ".join(items))

    if document.experience:
        lines.extend(["", "Professional Experience"])
        for entry in document.experience:
            lines.append(join_fields(entry.employer, entry.location))
            if entry.date_range:
                lines.append(entry.date_range)
            if entry.title:
                lines.append(entry.title)
            lines.extend(bullet_line(bullet) for bullet in entry.bullets if bullet.strip())
            lines.append("")

    if document.education:
        lines.append("Education")
        for education in document.education:
            lines.append(join_fields(education.institution, education.location))
            if education.date_range:
                lines.append(education.date_range)
            if education.degree:
                lines.append(education.degree)
            lines.extend(bullet_line(detail) for detail in education.details if detail.strip())

    if document.certifications:
        lines.extend(["", "Certifications"])
        for cert in document.certifications:
            lines.append(
                bullet_line(
                    join_fields(
                        cert.name,
                        cert.date,
                        cert.link,
                        f"Credential ID: {cert.credential_id}" if cert.credential_id else "",
                    )
                )
            )

    for heading, section_lines in document.remaining_sections:
        content = [line for line in section_lines if line.strip()]
        if content:
            lines.extend(["", heading or "Additional Information", *content])

    return normalize_document_text("\n".join(lines).strip())


def render_cover_letter_text_from_document(document: CoverLetterDocument) -> str:
    """Render plain-text cover-letter body paragraphs from the structured document."""
    paragraphs = [paragraph for paragraph in document.body_paragraphs if paragraph.strip()]
    return normalize_document_text("\n\n".join(paragraphs).strip())


def _field_line(fields: list[tuple[str, str]]) -> str:
    return " | ".join(f"{label}: {value}" for label, value in fields if value)
