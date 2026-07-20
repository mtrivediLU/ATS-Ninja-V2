"""Short-lived, local resume document extraction endpoint."""

from __future__ import annotations

from typing import Annotated

from ats_engine.parsing import ResumeExtractionError, extract_resume_document
from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status

from app.config import Settings
from app.schemas import ResumeExtractionResponse

router = APIRouter(prefix="/resume-extractions", tags=["resume-extractions"])


@router.post("", response_model=ResumeExtractionResponse, status_code=status.HTTP_200_OK)
async def extract_resume(
    request: Request,
    file: Annotated[UploadFile, File(description="PDF, DOCX, or TXT resume")],
) -> ResumeExtractionResponse:
    """Extract one resume in memory; no binary is persisted or queued."""
    settings: Settings = request.app.state.settings
    try:
        content = await _read_limited(file, settings.resume_upload_max_bytes)
        extracted = extract_resume_document(
            filename=file.filename,
            content_type=file.content_type,
            content=content,
            max_bytes=settings.resume_upload_max_bytes,
            max_pdf_pages=settings.resume_upload_max_pdf_pages,
            max_text_characters=settings.resume_text_max_characters,
        )
        return ResumeExtractionResponse(
            filename=extracted.filename,
            mime_type=extracted.mime_type,
            size_bytes=extracted.size_bytes,
            extraction_method=extracted.extraction_method,
            text=extracted.text,
            character_count=extracted.character_count,
            page_count=extracted.page_count,
            warnings=list(extracted.warnings),
            truncated=extracted.truncated,
        )
    except ResumeExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from None
    finally:
        # Starlette may spool multipart parts to a temporary file. Closing it
        # here makes cleanup explicit on success and every parser failure.
        await file.close()


async def _read_limited(file: UploadFile, maximum: int) -> bytes:
    """Read at most one byte past the configured limit without retaining a path."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(min(64 * 1024, maximum + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise ResumeExtractionError("file_too_large", "The uploaded file exceeds the 10 MB limit.")
        chunks.append(chunk)
    return b"".join(chunks)
