from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.document_export import DocumentExportError, build_export
from app.schemas import DocumentExportRequest
from app.services import get_kit

"""Local PDF export endpoint.

A single request-scoped, synchronous export: read the already-persisted,
already-validated kit result (or accept a request-scoped local edit that is
never persisted), render it to PDF, and return the bytes directly. No queue,
no external service, no upload — see docs/adr/0018-local-pdf-rendering.md.
"""

router = APIRouter(prefix="/document-exports", tags=["document-exports"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


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
