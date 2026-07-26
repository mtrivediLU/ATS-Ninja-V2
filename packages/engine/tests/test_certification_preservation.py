from __future__ import annotations

from ats_engine.generation.document_render import render_resume_text_from_document
from ats_engine.generation.html_renderer import render_resume_html
from ats_engine.generation.latex_renderer import build_resume_context, resume_to_latex
from ats_engine.kit.contract import ResumeCertificationEntry, ResumeDocument
from ats_engine.kit.serialization import _resume_document_from_dict, _resume_document_to_dict


def test_credential_id_round_trips_through_document_serialization_and_renderers() -> None:
    document = ResumeDocument(
        candidate_name="Alex Morgan",
        certifications=[
            ResumeCertificationEntry(
                name="Microsoft Certified: Power BI Data Analyst Associate (PL-300)",
                date="2025",
                credential_id="ABC-123",
            )
        ],
    )

    serialized = _resume_document_to_dict(document)
    restored = _resume_document_from_dict(serialized)

    assert restored is not None
    assert restored.certifications[0].credential_id == "ABC-123"

    text = render_resume_text_from_document(restored)
    assert "Credential ID: ABC-123" in text
    assert "Credential ID: ABC-123" in render_resume_html(restored, "classic")

    latex_context = build_resume_context(text, {"name": "Alex Morgan"})
    assert latex_context["certifications"][0]["credential_id"] == "ABC-123"
    assert "Credential ID: ABC-123" in resume_to_latex(text, {"name": "Alex Morgan"})
