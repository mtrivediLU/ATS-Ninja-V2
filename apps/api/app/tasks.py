from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.config import Settings, get_settings
from app.db import create_db_engine, create_sessionmaker
from app.queue import GENERATE_KIT_TASK
from app.services import mark_kit_failed, process_kit

"""Celery worker task: generate an application kit.

The task carries only the kit id. It loads all kit state from PostgreSQL, runs
the existing shared kit lifecycle (`app.services.process_kit` → the real
`ats_engine.generate_application_kit`), and persists the outcome back to PostgreSQL.

Async bridge: the service layer is async (async SQLAlchemy), while Celery tasks
are synchronous. Each task runs its coroutine on a fresh event loop
(`asyncio.run`) with a short-lived engine created and disposed within that same
loop — avoiding cross-event-loop reuse of asyncpg connections and keeping the
worker free of global mutable state.

Failure policy:
- Engine/validation failures are handled inside `process_kit` (kit → failed,
  persisted). They never reach this task, so they are terminal and never retried.
- Only classified **transient infrastructure** failures (DB connectivity) that
  escape `process_kit` are retried, with bounded, backing-off attempts.
- On retry exhaustion or an unexpected non-transient error, the kit is marked
  failed so it is never left stuck in ``processing`` and no traceback reaches
  clients (they only ever read kit state from PostgreSQL).
"""

logger = logging.getLogger(__name__)

MAX_RETRIES = 3

# Transient (retryable) failures: broker/database connectivity blips only.
# NOT included: application/validation/deterministic errors (engine failures are
# already handled inside process_kit and never reach here).
TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    OperationalError,
    InterfaceError,
    ConnectionError,
    TimeoutError,
    OSError,
)


def is_transient_error(exc: BaseException) -> bool:
    """Classify whether a failure escaping ``process_kit`` is worth retrying."""
    return isinstance(exc, TRANSIENT_EXCEPTIONS)


def retry_countdown(retries: int) -> int:
    """Bounded exponential backoff (seconds): 10, 20, 40, ... capped at 5 minutes."""
    return int(min(300, 10 * 2**retries))


def _run(operation: Callable[[AsyncSession, Settings], Awaitable[None]]) -> None:
    """Run an async kit operation on a fresh loop + short-lived engine."""
    settings = get_settings()

    async def _main() -> None:
        engine = create_db_engine(settings.database_url, settings.database_echo)
        sessionmaker = create_sessionmaker(engine)
        try:
            async with sessionmaker() as session:
                await operation(session, settings)
        finally:
            await engine.dispose()

    asyncio.run(_main())


def _process(kit_id: UUID) -> None:
    _run(lambda session, settings: process_kit(session, kit_id, settings))


def _fail(kit_id: UUID, error: str) -> None:
    _run(lambda session, _settings: mark_kit_failed(session, kit_id, error))


def _generate_kit_body(task: Any, kit_id: str) -> None:
    """Testable task body: run generation, classify failures, retry or fail.

    Separated from the Celery binding so it can be unit-tested with a fake task
    (``self``) and monkeypatched ``_process`` / ``_fail``.
    """
    kid = UUID(kit_id)
    try:
        _process(kid)
    except TRANSIENT_EXCEPTIONS as exc:
        retries = task.request.retries
        if retries < task.max_retries:
            logger.warning("generate_kit: transient failure for kit %s (attempt %s): %r", kid, retries, exc)
            # task.retry() raises celery.exceptions.Retry (control flow); Celery
            # chains the original exception via exc=exc.
            raise task.retry(exc=exc, countdown=retry_countdown(retries)) from exc
        logger.error("generate_kit: transient failure exhausted for kit %s: %r", kid, exc)
        _fail(kid, f"transient infrastructure failure after {retries} retries: {type(exc).__name__}")
    except Exception as exc:  # noqa: BLE001 - non-transient/unexpected: terminal, do not retry.
        logger.exception("generate_kit: unexpected worker failure for kit %s", kid)
        _fail(kid, f"unexpected worker failure: {type(exc).__name__}")


@celery_app.task(bind=True, name=GENERATE_KIT_TASK, max_retries=MAX_RETRIES)  # type: ignore[untyped-decorator]
def generate_kit(self: Any, kit_id: str) -> None:
    """Celery entrypoint. Thin binding over the testable body."""
    _generate_kit_body(self, kit_id)
