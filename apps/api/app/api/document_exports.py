from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.document_export import DocumentExportError, build_docx_export, build_export
from app.schemas import DocumentExportRequest
from app.services import get_kit

"""Local PDF and DOCX export endpoints.

A single request-scoped, synchronous export: read the already-persisted,
already-validated kit result (or accept a request-scoped local edit that is
never persisted), render it, and return the bytes directly. No queue, no
external service, no upload — see docs/adr/0018-local-pdf-rendering.md and
docs/adr/0021-docx-export.md.
"""

router = APIRouter(prefix="/document-exports", tags=["document-exports"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.post("/pdf")
async def export_pdf(payload: DocumentExportRequest, session: SessionDep) -> Response:
    kit = await get_kit(session, payload.kit_id)
    if kit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kit not found")

    try:
        # WeasyPrint rendering is synchronous and CPU-bound; run it off the
        # event loop the same way the worker offloads engine generation.
        export = await asyncio.to_thread(build_export, kit, payload)
    except DocumentExportError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return Response(
        content=export.pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{export.filename}"'},
    )


@router.post("/docx")
async def export_docx(payload: DocumentExportRequest, session: SessionDep) -> Response:
    kit = await get_kit(session, payload.kit_id)
    if kit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kit not found")

    try:
        # python-docx is pure Python but still synchronous/CPU-bound; keep it
        # off the event loop for the same reason as the PDF export above.
        export = await asyncio.to_thread(build_docx_export, kit, payload)
    except DocumentExportError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return Response(
        content=export.docx_bytes,
        media_type=DOCX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{export.filename}"'},
    )
