from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable
from uuid import UUID

from celery import Celery
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings

"""Job queue abstraction — the service-facing dispatcher boundary.

The API depends only on the :class:`JobQueue` interface. `CeleryJobQueue`
dispatches to the Celery/Redis broker in production; `InlineJobQueue` runs the
job in-process for tests and single-process usage. Only the kit id crosses the
broker — the worker loads all state from PostgreSQL. Request handlers never
import the task implementation: dispatch is **by task name**, so the producer
stays decoupled from the worker's task code.
"""

# Producer/consumer contract: the worker (app.tasks) registers a task under this
# exact name. Kept here, in the dispatcher boundary, so app.tasks imports it
# (never the reverse) and the API can dispatch without importing the worker.
GENERATE_KIT_TASK = "generate_kit"


class QueueUnavailableError(RuntimeError):
    """Raised when the broker cannot accept a job (e.g. Redis is unreachable)."""


@runtime_checkable
class JobQueue(Protocol):
    async def enqueue_kit(self, kit_id: UUID) -> None:
        """Schedule generation for a kit. Returns once the job is accepted."""
        ...


class CeleryJobQueue:
    """Dispatches kit generation onto the Celery/Redis broker, by task name."""

    def __init__(self, celery_app: Celery) -> None:
        self._celery = celery_app

    async def enqueue_kit(self, kit_id: UUID) -> None:
        # `send_task` is a synchronous broker publish; run it off the event loop.
        # Only the kit id is sent — never resume/JD text or the result payload.
        try:
            await asyncio.to_thread(self._celery.send_task, GENERATE_KIT_TASK, args=[str(kit_id)])
        except Exception as exc:  # broker unreachable / publish failure
            raise QueueUnavailableError(str(exc)) from exc


class InlineJobQueue:
    """Runs the generation job immediately, in-process (tests / single-process).

    Uses its own session, like the real worker, so the code path matches
    production. Imports the service lazily so importing this module (and thus the
    API) does not pull in the engine.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    async def enqueue_kit(self, kit_id: UUID) -> None:
        from app.services import process_kit

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
