from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID

from ats_engine import (
    ChangeAction,
    OutreachAudience,
    OutreachContext,
    OutreachIntent,
    application_kit_from_dict,
    application_kit_to_dict,
    apply_change_actions,
    generate_application_kit,
    is_application_kit_v5,
    normalize_persisted_result,
    resolve_artifact_selection,
)
from ats_engine.generation import mode_from_text
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Kit
from app.schemas import ChangeActionItem, KitCreate, KitStatus

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
    legacy_mode = mode_from_text(
        payload.requested_mode,
        job_description=payload.job_description,
        questions=[payload.questions_text] if payload.questions_text.strip() else [],
    )
    selection = resolve_artifact_selection(
        legacy_mode,
        include_resume=payload.include_resume,
        include_cover_letter=payload.include_cover_letter,
        include_application_answers=payload.include_application_answers,
    )
    kit = Kit(
        status=KitStatus.PENDING,
        resume_text=payload.resume_text,
        job_description=payload.job_description,
        requested_mode=payload.requested_mode,
        questions_text=payload.questions_text,
        include_resume=selection.resume,
        include_cover_letter=selection.cover_letter,
        include_application_answers=selection.application_answers,
        include_job_fit=payload.include_job_fit,
        include_interview_prep=payload.include_interview_prep,
        include_linkedin_outreach=payload.include_linkedin_outreach,
        outreach_context=(
            payload.outreach_context.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
            if payload.outreach_context
            else None
        ),
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

    # Safe timing only: kit id, elapsed milliseconds, and the llm/deterministic
    # mode flag. Never the resume, job description, or any generated content.
    started_at = time.monotonic()
    try:
        application_kit = await asyncio.to_thread(
            generate_application_kit,
            resume_text=kit.resume_text,
            job_description=kit.job_description,
            requested_mode=kit.requested_mode or "",
            questions_text=kit.questions_text or "",
            include_resume=kit.include_resume,
            include_cover_letter=kit.include_cover_letter,
            include_application_answers=kit.include_application_answers,
            use_llm=settings.engine_use_llm,
            include_job_fit=kit.include_job_fit,
            include_interview_prep=kit.include_interview_prep,
            include_linkedin_outreach=kit.include_linkedin_outreach,
            outreach_context=_outreach_context(kit.outreach_context),
        )
    except Exception as exc:  # noqa: BLE001 - any engine failure marks the kit failed, not the worker.
        # Log only the exception type (no message/traceback) so candidate-derived
        # content in an exception cannot reach server logs; persist a client-safe
        # message with no content. See the audit-remediation privacy fix (4C).
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        logger.error(
            "process_kit: engine generation failed for kit %s after %sms (type=%s, llm=%s)",
            kit_id,
            elapsed_ms,
            type(exc).__name__,
            settings.engine_use_llm,
        )
        kit.status = KitStatus.FAILED
        kit.error = _client_safe_error(exc)
        await session.commit()
        return

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    logger.info(
        "process_kit: kit %s generation completed in %sms (llm=%s)", kit_id, elapsed_ms, settings.engine_use_llm
    )

    kit.result = application_kit_to_dict(application_kit)
    kit.status = KitStatus.COMPLETED
    kit.error = None
    await session.commit()


def _outreach_context(raw: dict[str, object] | None) -> OutreachContext | None:
    """Translate persisted transport values into the engine's typed context."""
    if not raw:
        return None
    audience_raw = str(raw.get("audience", ""))
    intent_raw = str(raw.get("requested_intent", ""))
    applied_raw = raw.get("has_applied")
    has_applied = applied_raw if isinstance(applied_raw, bool) else None
    return OutreachContext(
        recipient_name=str(raw.get("recipient_name", "")),
        recipient_title=str(raw.get("recipient_title", "")),
        recipient_company=str(raw.get("recipient_company", "")),
        audience=OutreachAudience(audience_raw) if audience_raw else None,
        requested_intent=OutreachIntent(intent_raw) if intent_raw else None,
        has_applied=has_applied,
        application_date=str(raw.get("application_date", "")),
        application_status=str(raw.get("application_status", "")),
        referral_contact_name=str(raw.get("referral_contact_name", "")),
        shared_affiliation=str(raw.get("shared_affiliation", "")),
        mutual_connection=str(raw.get("mutual_connection", "")),
        prior_meeting=str(raw.get("prior_meeting", "")),
        prior_conversation=str(raw.get("prior_conversation", "")),
        personalization_note=str(raw.get("personalization_note", "")),
        portfolio_url=str(raw.get("portfolio_url", "")),
    )


@dataclass(slots=True)
class ChangeActionOutcome:
    """Result of applying a change-action batch, mapped to an HTTP status by the router."""

    status: str  # "ok" | "not_found" | "not_completed" | "conflict" | "invalid"
    kit: Kit | None = None
    errors: list[str] = field(default_factory=list)


async def apply_kit_change_actions(
    session: AsyncSession,
    kit_id: UUID,
    *,
    expected_revision: int,
    actions: list[ChangeActionItem],
) -> ChangeActionOutcome:
    """Apply a batch of accept/reject/restore actions to a completed v5 kit.

    Deterministic and LLM-free. **Atomic** optimistic concurrency: the JSON
    artifact, revision, and timestamp are written by a single conditional UPDATE
    guarded on ``revision = expected_revision``. If exactly one row is not
    affected, another request advanced the revision first and this batch is
    refused with a 409 conflict. Two simultaneous requests for the same revision
    therefore cannot both succeed — the loser never overwrites the winner. On
    PostgreSQL this is a genuine atomic compare-and-set; the Python-side revision
    check below is only a fast, friendly pre-check for the common serial case.
    """
    kit = await session.get(Kit, kit_id)
    if kit is None:
        return ChangeActionOutcome(status="not_found")
    if kit.status != KitStatus.COMPLETED or kit.result is None:
        return ChangeActionOutcome(status="not_completed", kit=kit)
    if not is_application_kit_v5(kit.result):
        return ChangeActionOutcome(status="not_completed", kit=kit, errors=["Change actions require a v5 kit."])
    if kit.revision != expected_revision:
        return ChangeActionOutcome(status="conflict", kit=kit, errors=["Revision conflict."])

    normalized = normalize_persisted_result(kit.result)
    if normalized is None:
        return ChangeActionOutcome(status="not_completed", kit=kit)
    application_kit = application_kit_from_dict(normalized)
    application_kit.revision = expected_revision

    result = await asyncio.to_thread(
        apply_change_actions,
        kit=application_kit,
        resume_text=kit.resume_text,
        job_description=kit.job_description,
        actions=[ChangeAction(item.change_id, item.action) for item in actions],
        expected_revision=expected_revision,
    )
    if result.conflict:
        return ChangeActionOutcome(status="conflict", kit=kit, errors=result.errors)
    if result.errors:
        return ChangeActionOutcome(status="invalid", kit=kit, errors=result.errors)

    new_revision = result.kit.revision
    new_result = application_kit_to_dict(result.kit)
    # Atomic compare-and-set: only the request whose expected_revision still
    # matches the stored revision wins; a concurrent winner leaves rowcount 0.
    updated = cast(
        "CursorResult[Any]",
        await session.execute(
            update(Kit)
            .where(Kit.id == kit_id, Kit.revision == expected_revision)
            .values(result=new_result, revision=new_revision, updated_at=func.now())
        ),
    )
    if updated.rowcount != 1:
        await session.rollback()
        return ChangeActionOutcome(status="conflict", kit=kit, errors=["Revision conflict."])
    await session.commit()
    # Reload the ORM object eagerly so the sync response serializer never triggers
    # a lazy load outside the async context.
    await session.refresh(kit)
    logger.info("apply_kit_change_actions: kit %s advanced to revision %s", kit_id, new_revision)
    return ChangeActionOutcome(status="ok", kit=kit)


async def delete_kit(session: AsyncSession, kit_id: UUID) -> bool:
    """Hard-delete a local kit row. Returns False when the kit does not exist.

    Never logs candidate content — only the kit id.
    """
    kit = await session.get(Kit, kit_id)
    if kit is None:
        return False
    await session.delete(kit)
    await session.commit()
    logger.info("delete_kit: kit %s deleted", kit_id)
    return True


async def regenerate_kit(session: AsyncSession, kit_id: UUID) -> Kit | None:
    """Create a new pending kit from a source kit's stored inputs and selection.

    The new kit links to the source via ``parent_kit_id`` and starts at revision
    0. The source kit is never modified. The caller enqueues generation.
    """
    source = await session.get(Kit, kit_id)
    if source is None:
        return None
    new_kit = Kit(
        status=KitStatus.PENDING,
        resume_text=source.resume_text,
        job_description=source.job_description,
        requested_mode=source.requested_mode,
        questions_text=source.questions_text,
        include_resume=source.include_resume,
        include_cover_letter=source.include_cover_letter,
        include_application_answers=source.include_application_answers,
        include_job_fit=source.include_job_fit,
        include_interview_prep=source.include_interview_prep,
        include_linkedin_outreach=source.include_linkedin_outreach,
        outreach_context=source.outreach_context,
        parent_kit_id=source.id,
        revision=0,
    )
    session.add(new_kit)
    await session.commit()
    await session.refresh(new_kit)
    logger.info("regenerate_kit: kit %s regenerated from %s", new_kit.id, kit_id)
    return new_kit


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
