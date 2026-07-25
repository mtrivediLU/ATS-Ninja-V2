from __future__ import annotations

from dataclasses import dataclass

from ats_engine import (
    build_export_filename,
    render_cover_letter_docx,
    render_cover_letter_html,
    render_plain_text_docx,
    render_plain_text_html,
    render_resume_docx,
    render_resume_html,
)
from ats_engine.kit.contract import (
    CoverLetterDocument,
    ResumeCertificationEntry,
    ResumeDocument,
    ResumeEducationEntry,
    ResumeExperienceEntry,
    ResumeSkillGroup,
)
from ats_engine.kit.serialization import normalize_persisted_result
from weasyprint import HTML

from app.models import Kit
from app.schemas import (
    ApplicationKitResponse,
    CoverLetterDocumentResponse,
    DocumentExportRequest,
    KitStatus,
    ResumeDocumentResponse,
)

"""Local, request-scoped PDF and DOCX rendering for the Resume/Cover Letter download.

Renders the already-persisted, already-validated ApplicationKit content (or a
request-scoped local edit, never persisted) via the engine's pure-Python
renderers (``ats_engine.generation.html_renderer`` / ``docx_renderer``), then
either rasterizes the HTML to PDF bytes with WeasyPrint or returns the DOCX
bytes directly. WeasyPrint's native dependency stays confined to this
service/apps-api layer per ADR-0004/ADR-0018 — the engine itself never imports
it; ``python-docx`` is a pure-Python OOXML writer, so DOCX rendering lives in
the engine alongside the other renderers.
"""


class DocumentExportError(Exception):
    """A resolvable export failure with a message that is safe to return to the client."""


@dataclass(slots=True)
class RenderedExport:
    pdf_bytes: bytes
    filename: str


@dataclass(slots=True)
class RenderedDocxExport:
    docx_bytes: bytes
    filename: str


@dataclass(slots=True)
class _ResolvedArtifact:
    """The document to render, resolved once for both the PDF and DOCX paths.

    ``document`` is the engine's structured dataclass (``ResumeDocument`` or
    ``CoverLetterDocument``) when one is available; ``plain_text`` is the raw
    text used instead when the source is a local edit or no structured document
    exists — both output formats agree on which content produced the export.
    """

    candidate_name: str
    document: ResumeDocument | CoverLetterDocument | None
    plain_text: str


def build_export(kit: Kit, payload: DocumentExportRequest) -> RenderedExport:
    """Render the requested artifact to PDF bytes with a standardized filename."""
    company, role, resolved = _resolve(kit, payload)

    if payload.artifact_type == "cover_letter":
        html = (
            render_cover_letter_html(resolved.document, payload.template_id)
            if isinstance(resolved.document, CoverLetterDocument)
            else render_plain_text_html(resolved.plain_text, template=payload.template_id)
        )
    else:
        html = (
            render_resume_html(resolved.document, payload.template_id)
            if isinstance(resolved.document, ResumeDocument)
            else render_plain_text_html(resolved.plain_text, template=payload.template_id)
        )

    pdf_bytes = HTML(string=html).write_pdf()
    filename = build_export_filename(
        candidate_name=resolved.candidate_name,
        job_title=role,
        company_name=company,
        artifact_type=payload.artifact_type,
        template_id=payload.template_id,
        kit_id=str(kit.id),
    )
    return RenderedExport(pdf_bytes=pdf_bytes, filename=filename)


def build_docx_export(kit: Kit, payload: DocumentExportRequest) -> RenderedDocxExport:
    """Render the requested artifact to DOCX bytes with a standardized filename."""
    company, role, resolved = _resolve(kit, payload)

    if payload.artifact_type == "cover_letter":
        docx_bytes = (
            render_cover_letter_docx(resolved.document, payload.template_id)
            if isinstance(resolved.document, CoverLetterDocument)
            else render_plain_text_docx(resolved.plain_text, template=payload.template_id)
        )
    else:
        docx_bytes = (
            render_resume_docx(resolved.document, payload.template_id)
            if isinstance(resolved.document, ResumeDocument)
            else render_plain_text_docx(resolved.plain_text, template=payload.template_id)
        )

    filename = build_export_filename(
        candidate_name=resolved.candidate_name,
        job_title=role,
        company_name=company,
        artifact_type=payload.artifact_type,
        template_id=payload.template_id,
        kit_id=str(kit.id),
        extension="docx",
    )
    return RenderedDocxExport(docx_bytes=docx_bytes, filename=filename)


def _resolve(kit: Kit, payload: DocumentExportRequest) -> tuple[str, str, _ResolvedArtifact]:
    if kit.status != KitStatus.COMPLETED or not kit.result:
        raise DocumentExportError("This kit has no completed result to export yet.")

    result = ApplicationKitResponse.model_validate(normalize_persisted_result(kit.result))
    company, role = _kit_target(result)
    resolved = (
        _resolve_cover_letter(result, payload)
        if payload.artifact_type == "cover_letter"
        else _resolve_resume(result, payload)
    )
    return company, role, resolved


def _resolve_resume(result: ApplicationKitResponse, payload: DocumentExportRequest) -> _ResolvedArtifact:
    if payload.content_source == "local_edit":
        text = payload.local_edit_text.strip()
        if not text:
            raise DocumentExportError("No local edit content was provided to export.")
        candidate_name = result.resume.document.candidate_name if result.resume and result.resume.document else ""
        return _ResolvedArtifact(candidate_name=candidate_name, document=None, plain_text=payload.local_edit_text)

    if result.resume is None or not result.resume.text.strip():
        raise DocumentExportError("This kit has no generated Resume to export.")
    if result.resume.document is not None:
        document = _to_engine_resume_document(result.resume.document)
        return _ResolvedArtifact(candidate_name=document.candidate_name, document=document, plain_text="")
    return _ResolvedArtifact(candidate_name="", document=None, plain_text=result.resume.text)


def _resolve_cover_letter(result: ApplicationKitResponse, payload: DocumentExportRequest) -> _ResolvedArtifact:
    if payload.content_source == "local_edit":
        text = payload.local_edit_text.strip()
        if not text:
            raise DocumentExportError("No local edit content was provided to export.")
        candidate_name = (
            result.cover_letter.document.sender_name if result.cover_letter and result.cover_letter.document else ""
        )
        return _ResolvedArtifact(candidate_name=candidate_name, document=None, plain_text=payload.local_edit_text)

    if result.cover_letter is None or not result.cover_letter.text.strip():
        raise DocumentExportError("This kit has no generated Cover Letter to export.")
    if result.cover_letter.document is not None:
        document = _to_engine_cover_letter_document(result.cover_letter.document)
        return _ResolvedArtifact(candidate_name=document.sender_name, document=document, plain_text="")
    return _ResolvedArtifact(candidate_name="", document=None, plain_text=result.cover_letter.text)


def _kit_target(result: ApplicationKitResponse) -> tuple[str, str]:
    """Resolve target company/role the same way the frontend's kitTarget() does.

    Checks every artifact that carries the value (LinkedIn outreach, then the
    Cover Letter document) instead of only one, so the filename is not
    "Applicant_Resume.pdf" merely because Outreach was not requested.
    """
    outreach = result.linkedin_outreach
    draft = outreach.drafts[0] if outreach and outreach.drafts else None
    company_ref = next((ref for ref in (outreach.target_context if outreach else []) if ref.field == "company"), None)
    role_ref = next((ref for ref in (outreach.target_context if outreach else []) if ref.field == "role"), None)
    cover_document = result.cover_letter.document if result.cover_letter else None

    company = (
        (draft.target_company if draft else "")
        or (company_ref.excerpt if company_ref else "")
        or (cover_document.recipient_company if cover_document else "")
    )
    role = (
        (draft.target_role if draft else "")
        or (role_ref.excerpt if role_ref else "")
        or (cover_document.target_role if cover_document else "")
    )
    return company, role


def _to_engine_resume_document(document: ResumeDocumentResponse) -> ResumeDocument:
    return ResumeDocument(
        candidate_name=document.candidate_name,
        professional_headline=document.professional_headline,
        contact_lines=list(document.contact_lines),
        summary=document.summary,
        skill_groups=[ResumeSkillGroup(group.label, list(group.items)) for group in document.skill_groups],
        experience=[
            ResumeExperienceEntry(
                employer=entry.employer,
                title=entry.title,
                location=entry.location,
                date_range=entry.date_range,
                bullets=list(entry.bullets),
            )
            for entry in document.experience
        ],
        education=[
            ResumeEducationEntry(
                institution=entry.institution,
                degree=entry.degree,
                location=entry.location,
                date_range=entry.date_range,
                details=list(entry.details),
            )
            for entry in document.education
        ],
        certifications=[ResumeCertificationEntry(item.name, item.date, item.link) for item in document.certifications],
        remaining_sections=[(section.heading, list(section.lines)) for section in document.remaining_sections],
    )


def _to_engine_cover_letter_document(document: CoverLetterDocumentResponse) -> CoverLetterDocument:
    return CoverLetterDocument(
        sender_name=document.sender_name,
        sender_contact_lines=list(document.sender_contact_lines),
        date=document.date,
        recipient_name=document.recipient_name,
        recipient_title=document.recipient_title,
        recipient_company=document.recipient_company,
        recipient_address=list(document.recipient_address),
        target_role=document.target_role,
        greeting=document.greeting,
        body_paragraphs=list(document.body_paragraphs),
        closing=document.closing,
        signature_name=document.signature_name,
    )
