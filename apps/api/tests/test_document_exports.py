from __future__ import annotations

import io
import uuid
from copy import deepcopy

import httpx
import pytest
from conftest import SAMPLE_JD, SAMPLE_RESUME
from docx import Document as ReadDocxDocument
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Kit
from app.schemas import KitStatus

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _create_completed_kit(client: httpx.AsyncClient, *, include_cover_letter: bool = True) -> str:
    response = await client.post(
        "/api/v1/kits",
        json={
            "resume_text": SAMPLE_RESUME,
            "job_description": SAMPLE_JD,
            "include_resume": True,
            "include_cover_letter": include_cover_letter,
            "include_application_answers": False,
        },
    )
    assert response.status_code == 202
    kit_id: str = response.json()["id"]
    fetched = await client.get(f"/api/v1/kits/{kit_id}")
    assert fetched.json()["status"] == "completed"
    return kit_id


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _docx_text(docx_bytes: bytes) -> str:
    document = ReadDocxDocument(io.BytesIO(docx_bytes))
    return "\n".join(p.text for p in document.paragraphs)


async def test_content_disposition_is_exposed_for_cross_origin_fetch(client: httpx.AsyncClient) -> None:
    """Content-Disposition is not on the CORS-safelisted response-header list.

    The browser's fetch() silently returns null for a header the server
    doesn't explicitly expose, even though curl/httpx can always see it —
    this is what actually broke the direct-download filename in a real
    browser despite every non-CORS test passing.
    """
    kit_id = await _create_completed_kit(client)
    response = await client.post(
        "/api/v1/document-exports/pdf",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": "classic"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200
    exposed = response.headers.get("access-control-expose-headers", "")
    assert "content-disposition" in exposed.lower()


@pytest.mark.parametrize("template_id", ["classic", "modern"])
async def test_resume_pdf_export_returns_selectable_pdf(client: httpx.AsyncClient, template_id: str) -> None:
    kit_id = await _create_completed_kit(client)
    response = await client.post(
        "/api/v1/document-exports/pdf",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": template_id},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert disposition.endswith('.pdf"')
    assert len(response.content) > 500
    assert response.content.startswith(b"%PDF")
    text = _pdf_text(response.content)
    # Classic renders the candidate name upper-cased by design (matches the
    # app's on-screen Classic template), so this check is case-insensitive.
    assert "jordan rivera" in text.lower()
    assert "Acme Analytics" in text
    # No application chrome ever reaches the downloaded document.
    assert "Not revalidated" not in text
    assert "Trust" not in text
    assert "Print / Save as PDF" not in text


@pytest.mark.parametrize("template_id", ["classic", "modern"])
async def test_cover_letter_pdf_export_returns_selectable_pdf(client: httpx.AsyncClient, template_id: str) -> None:
    kit_id = await _create_completed_kit(client)
    response = await client.post(
        "/api/v1/document-exports/pdf",
        json={"kit_id": kit_id, "artifact_type": "cover_letter", "template_id": template_id},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    text = _pdf_text(response.content)
    assert "jordan rivera" in text.lower()


async def test_resume_export_filename_uses_standardized_convention(client: httpx.AsyncClient) -> None:
    kit_id = await _create_completed_kit(client)
    response = await client.post(
        "/api/v1/document-exports/pdf",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": "classic"},
    )
    disposition = response.headers["content-disposition"]
    assert "Jordan_Rivera" in disposition
    assert "_Resume_Classic.pdf" in disposition


async def test_cover_letter_export_filename_uses_standardized_convention(client: httpx.AsyncClient) -> None:
    kit_id = await _create_completed_kit(client)
    response = await client.post(
        "/api/v1/document-exports/pdf",
        json={"kit_id": kit_id, "artifact_type": "cover_letter", "template_id": "modern"},
    )
    disposition = response.headers["content-disposition"]
    assert "_Cover_Letter_Modern.pdf" in disposition


async def test_local_edit_source_is_exported_and_not_persisted(client: httpx.AsyncClient) -> None:
    kit_id = await _create_completed_kit(client)
    edited_text = "EDITED CANDIDATE NAME\nLocally edited resume body text that should appear in the PDF only."
    response = await client.post(
        "/api/v1/document-exports/pdf",
        json={
            "kit_id": kit_id,
            "artifact_type": "resume",
            "template_id": "classic",
            "content_source": "local_edit",
            "local_edit_text": edited_text,
        },
    )
    assert response.status_code == 200
    text = _pdf_text(response.content)
    assert "Locally edited resume body text" in text

    # The stored kit result is untouched by the local edit.
    fetched = await client.get(f"/api/v1/kits/{kit_id}")
    stored_text = fetched.json()["result"]["resume"]["text"]
    assert "Locally edited resume body text" not in stored_text


async def test_local_edit_without_text_returns_client_error(client: httpx.AsyncClient) -> None:
    kit_id = await _create_completed_kit(client)
    response = await client.post(
        "/api/v1/document-exports/pdf",
        json={
            "kit_id": kit_id,
            "artifact_type": "resume",
            "template_id": "classic",
            "content_source": "local_edit",
            "local_edit_text": "   ",
        },
    )
    assert response.status_code == 422


async def test_export_for_unavailable_artifact_returns_client_error(client: httpx.AsyncClient) -> None:
    kit_id = await _create_completed_kit(client, include_cover_letter=False)
    response = await client.post(
        "/api/v1/document-exports/pdf",
        json={"kit_id": kit_id, "artifact_type": "cover_letter", "template_id": "classic"},
    )
    assert response.status_code == 422


async def test_delivered_resume_remains_exportable_from_partially_completed_kit(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    kit_id = await _create_completed_kit(client)
    async with sessionmaker() as session:
        kit = await session.get(Kit, uuid.UUID(kit_id))
        assert kit is not None
        kit.status = KitStatus.PARTIALLY_COMPLETED
        await session.commit()

    pdf = await client.post(
        "/api/v1/document-exports/pdf",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": "classic"},
    )
    docx = await client.post(
        "/api/v1/document-exports/docx",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": "classic"},
    )
    assert pdf.status_code == 200
    assert docx.status_code == 200
    assert "jordan rivera" in _pdf_text(pdf.content).lower()
    assert "jordan rivera" in _docx_text(docx.content).lower()


async def test_failed_v7_artifact_is_not_exported_even_if_stale_text_exists(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    kit_id = await _create_completed_kit(client)
    async with sessionmaker() as session:
        kit = await session.get(Kit, uuid.UUID(kit_id))
        assert kit is not None and kit.result is not None
        changed = dict(kit.result)
        reports = dict(changed["delivery_reports"])
        reports["resume"] = {**reports.get("resume", {}), "state": "failed"}
        changed["delivery_reports"] = reports
        changed["state"] = "partially_completed"
        kit.result = changed
        kit.status = KitStatus.PARTIALLY_COMPLETED
        await session.commit()

    response = await client.post(
        "/api/v1/document-exports/pdf",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": "classic"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("endpoint", ["pdf", "docx"])
async def test_failed_artifact_blocks_local_edits_too(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    endpoint: str,
) -> None:
    kit_id = await _create_completed_kit(client)
    async with sessionmaker() as session:
        kit = await session.get(Kit, uuid.UUID(kit_id))
        assert kit is not None and kit.result is not None
        changed = dict(kit.result)
        reports = dict(changed["delivery_reports"])
        reports["resume"] = {**reports["resume"], "state": "failed"}
        changed["delivery_reports"] = reports
        changed["state"] = "needs_input_review"
        kit.result = changed
        kit.status = KitStatus.NEEDS_INPUT_REVIEW
        await session.commit()

    response = await client.post(
        f"/api/v1/document-exports/{endpoint}",
        json={
            "kit_id": kit_id,
            "artifact_type": "resume",
            "template_id": "classic",
            "content_source": "local_edit",
            "local_edit_text": "Unsafe stale local content",
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("endpoint", ["pdf", "docx"])
async def test_needs_review_kit_exports_only_its_delivered_sibling(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    endpoint: str,
) -> None:
    kit_id = await _create_completed_kit(client)
    async with sessionmaker() as session:
        kit = await session.get(Kit, uuid.UUID(kit_id))
        assert kit is not None and kit.result is not None
        changed = dict(kit.result)
        reports = dict(changed["delivery_reports"])
        reports["resume"] = {**reports["resume"], "state": "generated"}
        reports["cover_letter"] = {**reports["cover_letter"], "state": "needs_input_review"}
        changed["delivery_reports"] = reports
        changed["state"] = "needs_input_review"
        kit.result = changed
        kit.status = KitStatus.NEEDS_INPUT_REVIEW
        await session.commit()

    delivered = await client.post(
        f"/api/v1/document-exports/{endpoint}",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": "classic"},
    )
    withheld = await client.post(
        f"/api/v1/document-exports/{endpoint}",
        json={"kit_id": kit_id, "artifact_type": "cover_letter", "template_id": "classic"},
    )
    assert delivered.status_code == 200
    assert withheld.status_code == 422


async def test_rejected_legacy_v6_artifact_is_not_exported_when_stale_text_exists(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    kit_id = await _create_completed_kit(client)
    async with sessionmaker() as session:
        kit = await session.get(Kit, uuid.UUID(kit_id))
        assert kit is not None and kit.result is not None
        changed = dict(kit.result)
        changed["schema_version"] = "application-kit/v6"
        changed.pop("state", None)
        changed.pop("delivery_reports", None)
        resume = dict(changed["resume"])
        resume_validation = dict(resume["validation"])
        resume_validation.update({"status": "rejected", "fatal": True})
        resume["validation"] = resume_validation
        changed["resume"] = resume
        validation = dict(changed["validation"])
        validation.update({"passed": False, "fatal": True})
        changed["validation"] = validation
        kit.result = changed
        await session.commit()

    response = await client.post(
        "/api/v1/document-exports/pdf",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": "classic"},
    )
    assert response.status_code == 422


async def test_export_for_unknown_kit_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/document-exports/pdf",
        json={"kit_id": str(uuid.uuid4()), "artifact_type": "resume", "template_id": "classic"},
    )
    assert response.status_code == 404


async def test_export_for_kit_without_completed_result_returns_client_error(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with sessionmaker() as session:
        kit = Kit(
            status=KitStatus.PENDING,
            resume_text=SAMPLE_RESUME,
            job_description=SAMPLE_JD,
        )
        session.add(kit)
        await session.commit()
        await session.refresh(kit)
        kit_id = str(kit.id)

    response = await client.post(
        "/api/v1/document-exports/pdf",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": "classic"},
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# DOCX export (mirrors the PDF export suite above)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("template_id", ["classic", "modern"])
async def test_resume_docx_export_returns_readable_docx(client: httpx.AsyncClient, template_id: str) -> None:
    kit_id = await _create_completed_kit(client)
    response = await client.post(
        "/api/v1/document-exports/docx",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": template_id},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == DOCX_MEDIA_TYPE
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert disposition.endswith('.docx"')
    assert response.content[:2] == b"PK"  # a real OOXML (zip) package
    text = _docx_text(response.content)
    assert "jordan rivera" in text.lower()
    assert "Acme Analytics" in text
    assert "Not revalidated" not in text
    assert "Trust" not in text


@pytest.mark.parametrize("template_id", ["classic", "modern"])
async def test_cover_letter_docx_export_returns_readable_docx(client: httpx.AsyncClient, template_id: str) -> None:
    kit_id = await _create_completed_kit(client)
    response = await client.post(
        "/api/v1/document-exports/docx",
        json={"kit_id": kit_id, "artifact_type": "cover_letter", "template_id": template_id},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == DOCX_MEDIA_TYPE
    text = _docx_text(response.content)
    assert "jordan rivera" in text.lower()


async def test_docx_export_filename_uses_the_same_standardized_convention(client: httpx.AsyncClient) -> None:
    kit_id = await _create_completed_kit(client)
    response = await client.post(
        "/api/v1/document-exports/docx",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": "classic"},
    )
    disposition = response.headers["content-disposition"]
    assert "Jordan_Rivera" in disposition
    assert "_Resume_Classic.docx" in disposition


async def test_docx_local_edit_source_is_exported_and_not_persisted(client: httpx.AsyncClient) -> None:
    kit_id = await _create_completed_kit(client)
    edited_text = "EDITED CANDIDATE NAME\nLocally edited resume body text that should appear in the DOCX only."
    response = await client.post(
        "/api/v1/document-exports/docx",
        json={
            "kit_id": kit_id,
            "artifact_type": "resume",
            "template_id": "classic",
            "content_source": "local_edit",
            "local_edit_text": edited_text,
        },
    )
    assert response.status_code == 200
    text = _docx_text(response.content)
    assert "Locally edited resume body text" in text

    fetched = await client.get(f"/api/v1/kits/{kit_id}")
    stored_text = fetched.json()["result"]["resume"]["text"]
    assert "Locally edited resume body text" not in stored_text


async def test_docx_export_for_unavailable_artifact_returns_client_error(client: httpx.AsyncClient) -> None:
    kit_id = await _create_completed_kit(client, include_cover_letter=False)
    response = await client.post(
        "/api/v1/document-exports/docx",
        json={"kit_id": kit_id, "artifact_type": "cover_letter", "template_id": "classic"},
    )
    assert response.status_code == 422


async def test_docx_export_for_unknown_kit_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/document-exports/docx",
        json={"kit_id": str(uuid.uuid4()), "artifact_type": "resume", "template_id": "classic"},
    )
    assert response.status_code == 404


async def test_pdf_and_docx_exports_reflect_the_same_current_revision(client: httpx.AsyncClient) -> None:
    """Both formats must render the same persisted revision's content."""
    kit_id = await _create_completed_kit(client)
    pdf_response = await client.post(
        "/api/v1/document-exports/pdf",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": "classic"},
    )
    docx_response = await client.post(
        "/api/v1/document-exports/docx",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": "classic"},
    )
    pdf_text = _pdf_text(pdf_response.content).lower()
    docx_text = _docx_text(docx_response.content).lower()
    assert "jordan rivera" in pdf_text
    assert "jordan rivera" in docx_text
    assert "acme analytics" in pdf_text
    assert "acme analytics" in docx_text


async def test_pdf_and_docx_exports_preserve_certification_credential_ids(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    kit_id = await _create_completed_kit(client)
    credential_id = "SYNTHETIC-CREDENTIAL-042"
    async with sessionmaker() as session:
        kit = await session.get(Kit, uuid.UUID(kit_id))
        assert kit is not None and kit.result is not None
        changed = deepcopy(kit.result)
        document = changed["resume"]["document"]
        document["certifications"] = [
            {
                "name": "Synthetic Analytics Certification",
                "date": "2026",
                "link": "",
                "credential_id": credential_id,
            }
        ]
        kit.result = changed
        await session.commit()

    pdf_response = await client.post(
        "/api/v1/document-exports/pdf",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": "classic"},
    )
    docx_response = await client.post(
        "/api/v1/document-exports/docx",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": "classic"},
    )

    assert pdf_response.status_code == 200
    assert docx_response.status_code == 200
    assert credential_id in _pdf_text(pdf_response.content)
    assert credential_id in _docx_text(docx_response.content)
