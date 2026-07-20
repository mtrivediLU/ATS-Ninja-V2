from __future__ import annotations

import io
import uuid

import httpx
import pytest
from conftest import SAMPLE_JD, SAMPLE_RESUME
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Kit
from app.schemas import KitStatus


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
