from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.queue import JobQueue, QueueUnavailableError, get_job_queue
from app.schemas import KitCreate, KitList, KitRead, KitSummary
from app.services import create_kit, get_kit, list_kits

"""Kit lifecycle endpoints.

`POST` accepts inputs, persists a pending kit, and enqueues generation
(returning 202 immediately — generation is asynchronous). `GET` reports status
and returns the result once completed. No authentication in this phase.
"""

router = APIRouter(prefix="/kits", tags=["kits"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
QueueDep = Annotated[JobQueue, Depends(get_job_queue)]


@router.post("", response_model=KitRead, status_code=status.HTTP_202_ACCEPTED)
async def submit_kit(payload: KitCreate, session: SessionDep, queue: QueueDep) -> KitRead:
    """Create a kit and enqueue its generation. Returns the pending kit (202).

    The kit is persisted (source of truth) before it is dispatched. If the broker
    is unreachable, the kit remains ``pending`` and a clean ``503`` is returned
    (no traceback leaks to the client); it can be re-dispatched later.
    """
    kit = await create_kit(session, payload)
    try:
        await queue.enqueue_kit(kit.id)
    except QueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Kit accepted but could not be queued; the broker is unavailable. Try again shortly.",
        ) from exc
    return KitRead.model_validate(kit)


@router.get("/{kit_id}", response_model=KitRead)
async def read_kit(kit_id: UUID, session: SessionDep) -> KitRead:
    """Return a kit's current status and, once completed, its result."""
    kit = await get_kit(session, kit_id)
    if kit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kit not found")
    return KitRead.model_validate(kit)


@router.get("", response_model=KitList)
async def list_kits_endpoint(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KitList:
    """Return a page of kits, newest first."""
    rows, total = await list_kits(session, limit=limit, offset=offset)
    return KitList(
        items=[KitSummary.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
