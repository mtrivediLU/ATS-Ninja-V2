from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from ats_engine import application_kit_to_dict, generate_application_kit
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Kit
from app.schemas import KitCreate, KitStatus

"""Kit application service.

This layer owns the kit lifecycle transitions and is the ONLY place that calls
the engine. It contains no HTTP or queue concerns, so it is equally usable from
an API request handler and from the async worker.
"""

logger = logging.getLogger(__name__)

# Client-facing failure text. The exception's message/args are deliberately
# excluded: they could echo resume text, a provider prompt, generated content, a
# filesystem path, an environment value, or a secret. Only the exception *type*
# (a safe, fixed identifier) is surfaced; full detail stays in server logs.
_CLIENT_ERROR_PREFIX = "Kit generation failed"


def _client_safe_error(exc: Exception) -> str:
    """A persisted, client-safe failure message that never leaks content."""
    return f"{_CLIENT_ERROR_PREFIX} ({type(exc).__name__})."


async def create_kit(session: AsyncSession, payload: KitCreate) -> Kit:
    """Persist a new kit in the ``pending`` state and return it."""
    kit = Kit(
        status=KitStatus.PENDING,
        resume_text=payload.resume_text,
        job_description=payload.job_description,
        requested_mode=payload.requested_mode,
        questions_text=payload.questions_text,
        include_job_fit=payload.include_job_fit,
    )
    session.add(kit)
    await session.commit()
    await session.refresh(kit)
    return kit


async def get_kit(session: AsyncSession, kit_id: UUID) -> Kit | None:
    """Load a kit by id, or ``None`` if it does not exist."""
    return await session.get(Kit, kit_id)


async def list_kits(session: AsyncSession, *, limit: int, offset: int) -> tuple[list[Kit], int]:
    """Return a page of kits (newest first) and the total count."""
    total = (await session.execute(select(func.count()).select_from(Kit))).scalar_one()
    rows = (
        (await session.execute(select(Kit).order_by(Kit.created_at.desc()).limit(limit).offset(offset))).scalars().all()
    )
    return list(rows), int(total)


async def process_kit(session: AsyncSession, kit_id: UUID, settings: Settings) -> None:
    """Generate a kit's ApplicationKit and persist it.

    This is the unit of work the async worker executes. The engine's
    ``generate_application_kit`` orchestrator is synchronous and potentially
    CPU/IO bound, so it runs in a worker thread (``asyncio.to_thread``) to avoid
    blocking the event loop. All truth-grounding happens inside the orchestrator:
    the persisted ApplicationKit already has every unsupported claim removed (or,
    if it could not be removed, the affected artifact withheld and flagged
    ``fatal``). This service adds no business logic; it only drives the lifecycle
    and persists the versioned contract through the engine's serialization
    boundary (`application_kit_to_dict`).
    """
    kit = await session.get(Kit, kit_id)
    if kit is None:
        logger.warning("process_kit: kit %s not found", kit_id)
        return
    if kit.status in (KitStatus.COMPLETED, KitStatus.FAILED):
        # Duplicate/terminal protection: at-least-once delivery may redeliver a
        # kit that already reached a terminal state. Never reprocess it.
        logger.info("process_kit: kit %s already terminal (%s); skipping", kit_id, kit.status)
        return

    kit.status = KitStatus.PROCESSING
    await session.commit()

    try:
        application_kit = await asyncio.to_thread(
            generate_application_kit,
            resume_text=kit.resume_text,
            job_description=kit.job_description,
            requested_mode=kit.requested_mode or "",
            questions_text=kit.questions_text or "",
            use_llm=settings.engine_use_llm,
            include_job_fit=kit.include_job_fit,
        )
    except Exception as exc:  # noqa: BLE001 - any engine failure marks the kit failed, not the worker.
        # Log only the exception type (no message/traceback) so candidate-derived
        # content in an exception cannot reach server logs; persist a client-safe
        # message with no content. See the audit-remediation privacy fix (4C).
        logger.error("process_kit: engine generation failed for kit %s (type=%s)", kit_id, type(exc).__name__)
        kit.status = KitStatus.FAILED
        kit.error = _client_safe_error(exc)
        await session.commit()
        return

    kit.result = application_kit_to_dict(application_kit)
    kit.status = KitStatus.COMPLETED
    kit.error = None
    await session.commit()


async def mark_kit_failed(session: AsyncSession, kit_id: UUID, error: str) -> None:
    """Persist a terminal failure for a kit.

    Used by the worker's infrastructure-failure and retry-exhaustion paths so a
    kit is never left stuck in ``processing`` when the failure happened outside
    ``process_kit``'s own engine-failure handling. Best-effort and idempotent:
    a missing or already-terminal kit is left untouched.
    """
    kit = await session.get(Kit, kit_id)
    if kit is None:
        logger.warning("mark_kit_failed: kit %s not found", kit_id)
        return
    if kit.status in (KitStatus.COMPLETED, KitStatus.FAILED):
        return
    kit.status = KitStatus.FAILED
    kit.error = error
    await session.commit()
