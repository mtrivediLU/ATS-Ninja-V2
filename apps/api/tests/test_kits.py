from __future__ import annotations

import uuid

import httpx
import pytest
from conftest import SAMPLE_JD, SAMPLE_RESUME
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.schemas import KitCreate, KitStatus
from app.services import create_kit, get_kit, mark_kit_failed, process_kit


async def test_submit_kit_runs_lifecycle_to_completion(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/kits",
        json={
            "resume_text": SAMPLE_RESUME,
            "job_description": SAMPLE_JD,
            "requested_mode": "resume and cover letter",
        },
    )
    assert response.status_code == 202
    created = response.json()
    kit_id = created["id"]
    assert created["status"] in {"pending", "processing", "completed"}

    # The inline queue processed the job synchronously; the kit is now complete.
    fetched = await client.get(f"/api/v1/kits/{kit_id}")
    assert fetched.status_code == 200
    kit = fetched.json()
    assert kit["status"] == "completed"
    result = kit["result"]
    assert result["resume_text"]
    assert result["cover_letter_text"]
    assert result["resume_latex"].startswith("\\documentclass")
    assert result["interview_probability"] is not None
    # Every truth-grounding gate passed.
    assert result["validation_errors"] == []
    assert result["fatal_validation_errors"] == []
    assert kit["error"] is None


async def test_get_unknown_kit_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/api/v1/kits/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_submit_kit_rejects_empty_inputs(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/kits", json={"resume_text": "", "job_description": "x"})
    assert response.status_code == 422


async def test_list_kits_paginates(client: httpx.AsyncClient) -> None:
    for _ in range(3):
        resp = await client.post(
            "/api/v1/kits",
            json={"resume_text": SAMPLE_RESUME, "job_description": SAMPLE_JD},
        )
        assert resp.status_code == 202

    listing = await client.get("/api/v1/kits", params={"limit": 2, "offset": 0})
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] >= 3
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0
    # Summary items do not leak inputs or full result payloads.
    assert set(body["items"][0].keys()) == {"id", "status", "created_at", "updated_at"}


# ---------------------------------------------------------------------------
# Service-layer tests (no HTTP): the worker executes exactly this code path.
# ---------------------------------------------------------------------------


async def test_process_kit_completes_and_persists_result(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker() as session:
        kit = await create_kit(
            session,
            KitCreate(resume_text=SAMPLE_RESUME, job_description=SAMPLE_JD, requested_mode="resume and cover letter"),
        )
        kit_id = kit.id
        assert kit.status == KitStatus.PENDING

    async with sessionmaker() as session:
        await process_kit(session, kit_id, settings)

    async with sessionmaker() as session:
        done = await get_kit(session, kit_id)
        assert done is not None
        assert done.status == KitStatus.COMPLETED
        assert done.result is not None
        assert done.result["resume_text"]
        assert done.result["validation_errors"] == []


async def test_process_kit_marks_failed_on_engine_error(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(**_kwargs: object) -> None:
        raise RuntimeError("engine boom")

    # Patch the engine entrypoint the service calls; a crash must fail the kit,
    # not the worker.
    monkeypatch.setattr("app.services.run_pipeline", boom)

    async with sessionmaker() as session:
        kit = await create_kit(session, KitCreate(resume_text="x", job_description="y"))
        kit_id = kit.id

    async with sessionmaker() as session:
        await process_kit(session, kit_id, settings)

    async with sessionmaker() as session:
        failed = await get_kit(session, kit_id)
        assert failed is not None
        assert failed.status == KitStatus.FAILED
        assert failed.error is not None
        assert "engine boom" in failed.error
        assert failed.result is None


async def test_process_kit_missing_id_is_noop(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    # Must not raise for an unknown id.
    async with sessionmaker() as session:
        await process_kit(session, uuid.uuid4(), settings)


async def test_process_kit_skips_already_terminal_kit(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Duplicate/terminal protection: a redelivered, already-completed kit is not reprocessed."""
    async with sessionmaker() as session:
        kit = await create_kit(session, KitCreate(resume_text=SAMPLE_RESUME, job_description=SAMPLE_JD))
        kit_id = kit.id

    async with sessionmaker() as session:
        await process_kit(session, kit_id, settings)

    async with sessionmaker() as session:
        completed = await get_kit(session, kit_id)
        assert completed is not None and completed.status == KitStatus.COMPLETED
        original_result = completed.result

    # Second (duplicate) invocation must be a no-op.
    async with sessionmaker() as session:
        await process_kit(session, kit_id, settings)

    async with sessionmaker() as session:
        again = await get_kit(session, kit_id)
        assert again is not None
        assert again.status == KitStatus.COMPLETED
        assert again.result == original_result


async def test_mark_kit_failed_sets_terminal_failure(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker() as session:
        kit = await create_kit(session, KitCreate(resume_text="x", job_description="y"))
        kit_id = kit.id

    async with sessionmaker() as session:
        await mark_kit_failed(session, kit_id, "infrastructure boom")

    async with sessionmaker() as session:
        failed = await get_kit(session, kit_id)
        assert failed is not None
        assert failed.status == KitStatus.FAILED
        assert failed.error == "infrastructure boom"


async def test_mark_kit_failed_is_noop_on_completed_kit(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """A late infra-failure must not overwrite an already-completed kit."""
    async with sessionmaker() as session:
        kit = await create_kit(session, KitCreate(resume_text=SAMPLE_RESUME, job_description=SAMPLE_JD))
        kit_id = kit.id

    async with sessionmaker() as session:
        await process_kit(session, kit_id, settings)

    async with sessionmaker() as session:
        await mark_kit_failed(session, kit_id, "should be ignored")

    async with sessionmaker() as session:
        kit = await get_kit(session, kit_id)
        assert kit is not None
        assert kit.status == KitStatus.COMPLETED
        assert kit.error is None
