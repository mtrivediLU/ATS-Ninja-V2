from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.services import process_kit

"""Job queue abstraction.

The API depends only on the :class:`JobQueue` interface. In production the
`ArqJobQueue` enqueues work onto Redis for the separately-running worker to pick
up. In tests (and single-process usage) the `InlineJobQueue` runs the job
immediately in-process, so the whole lifecycle is exercised without Redis. This
mirrors the engine's provider-abstraction philosophy: infrastructure lives
behind an interface, never hardcoded into request handlers.

The generation job name is shared with the worker so both refer to the same task.
"""

GENERATE_KIT_TASK = "generate_kit"


@runtime_checkable
class JobQueue(Protocol):
    async def enqueue_kit(self, kit_id: UUID) -> None:
        """Schedule generation for a kit. Returns once the job is accepted."""
        ...


class ArqJobQueue:
    """Enqueues kit generation onto Redis for the arq worker."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def enqueue_kit(self, kit_id: UUID) -> None:
        await self._redis.enqueue_job(GENERATE_KIT_TASK, str(kit_id))


class InlineJobQueue:
    """Runs the generation job immediately, in-process.

    Uses its own session (like the real worker would), not the request session,
    so the code path matches production and the result is committed independently.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    async def enqueue_kit(self, kit_id: UUID) -> None:
        async with self._sessionmaker() as session:
            await process_kit(session, kit_id, self._settings)


def get_job_queue(request: Request) -> JobQueue:
    """FastAPI dependency returning the configured job queue."""
    queue: JobQueue | None = getattr(request.app.state, "job_queue", None)
    if queue is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job queue is not available.",
        )
    return queue
