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
    # The versioned ApplicationKit contract with typed artifacts.
    assert result["schema_version"] == "application-kit/v3"
    assert result["job_fit"] is not None
    assert result["job_fit"]["requirements"]
    assert result["job_fit"]["consistency"]["passed"] is True
    assert kit["include_job_fit"] is True
    assert kit["include_interview_prep"] is True
    assert result["interview_prep"] is not None
    assert result["interview_prep"]["questions"]
    assert result["interview_prep"]["consistency"]["passed"] is True
    assert result["resume"]["text"]
    assert result["cover_letter"]["text"]
    assert result["resume"]["latex"].startswith("\\documentclass")
    assert result["resume"]["interview_probability"] is not None
    # No fabrication was rejected/withheld; the kit is trusted.
    assert result["validation"]["fatal"] is False
    assert kit["error"] is None


async def test_get_unknown_kit_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/api/v1/kits/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_completed_kit_with_legacy_phase1_result_is_served(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A kit persisted under the pre-Phase-2A result schema must not crash GET."""
    from app.models import Kit

    legacy_result = {
        "resume_text": "Candidate Header\nProfessional Summary\nExperienced analyst.",
        "cover_letter_text": "Dear Hiring Manager, I am applying.",
        "answers_text": "",
        "resume_latex": "\\documentclass{article}\\begin{document}x\\end{document}",
        "cover_letter_latex": "",
        "interview_probability": 68,
        "validation_errors": [],
        "fatal_validation_errors": [],
        "engine_metadata": {"llm_available": False},
    }
    async with sessionmaker() as session:
        kit = Kit(
            status=KitStatus.COMPLETED,
            resume_text="r",
            job_description="j",
            result=legacy_result,
        )
        session.add(kit)
        await session.commit()
        await session.refresh(kit)
        kit_id = kit.id

    response = await client.get(f"/api/v1/kits/{kit_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    # Adapted into the canonical response under an explicit legacy marker.
    assert body["result"]["schema_version"] == "phase-1/legacy"
    assert body["result"]["resume"]["text"].startswith("Candidate Header")
    assert any("legacy" in warning.lower() for warning in body["result"]["warnings"])


async def test_submit_kit_rejects_empty_inputs(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/kits", json={"resume_text": "", "job_description": "x"})
    assert response.status_code == 422


async def test_openapi_exposes_interview_prep_request_and_typed_response(client: httpx.AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schemas = response.json()["components"]["schemas"]
    create_properties = schemas["KitCreate"]["properties"]
    assert create_properties["include_interview_prep"]["default"] is True
    assert "InterviewPrepArtifactResponse" in schemas
    prep_properties = schemas["InterviewPrepArtifactResponse"]["properties"]
    assert {
        "strategy_summary",
        "focus_areas",
        "questions",
        "star_stories",
        "technical_study_topics",
        "gap_handling",
        "interviewer_questions",
        "validation",
        "consistency",
        "claims",
    } <= prep_properties.keys()


async def test_submit_kit_can_persistently_disable_job_fit(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/kits",
        json={
            "resume_text": SAMPLE_RESUME,
            "job_description": SAMPLE_JD,
            "include_job_fit": False,
        },
    )
    assert response.status_code == 202
    fetched = await client.get(f"/api/v1/kits/{response.json()['id']}")
    body = fetched.json()
    assert body["include_job_fit"] is False
    assert body["result"]["schema_version"] == "application-kit/v3"
    assert body["result"]["job_fit"] is None
    assert body["include_interview_prep"] is True
    assert body["result"]["interview_prep"] is not None


async def test_submit_kit_can_persistently_disable_interview_prep_independently(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/kits",
        json={
            "resume_text": SAMPLE_RESUME,
            "job_description": SAMPLE_JD,
            "include_job_fit": True,
            "include_interview_prep": False,
        },
    )
    assert response.status_code == 202
    fetched = await client.get(f"/api/v1/kits/{response.json()['id']}")
    body = fetched.json()
    assert body["include_job_fit"] is True
    assert body["include_interview_prep"] is False
    assert body["result"]["job_fit"] is not None
    assert body["result"]["interview_prep"] is None


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
        assert done.result["schema_version"] == "application-kit/v3"
        assert done.result["job_fit"] is not None
        assert done.result["interview_prep"] is not None
        assert done.result["resume"]["text"]
        assert done.result["validation"]["passed"] is True


async def test_process_kit_marks_failed_on_engine_error(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(**_kwargs: object) -> None:
        raise RuntimeError("engine boom")

    # Patch the engine entrypoint the service calls; a crash must fail the kit,
    # not the worker.
    monkeypatch.setattr("app.services.generate_application_kit", boom)

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
        # Client-safe: the raw exception message is NOT leaked; only the type name.
        assert "engine boom" not in failed.error
        assert "RuntimeError" in failed.error
        assert failed.result is None


async def test_process_kit_failure_does_not_leak_sensitive_exception_content(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A badly-constructed exception carrying candidate/secret content must not
    reach the persisted, client-facing error (audit remediation 4C)."""
    secret = "SSN 123-45-6789 resume /home/test-candidate/private/resume.pdf sk-provider-key-abcdef"

    def leaky(**_kwargs: object) -> None:
        raise ValueError(secret)

    monkeypatch.setattr("app.services.generate_application_kit", leaky)

    async with sessionmaker() as session:
        kit = await create_kit(session, KitCreate(resume_text="x", job_description="y"))
        kit_id = kit.id

    async with sessionmaker() as session:
        await process_kit(session, kit_id, settings)

    async with sessionmaker() as session:
        failed = await get_kit(session, kit_id)
        assert failed is not None and failed.error is not None
        assert secret not in failed.error
        assert "123-45-6789" not in failed.error
        assert "/home/test-candidate/private/resume.pdf" not in failed.error
        assert "sk-provider-key" not in failed.error
        assert "ValueError" in failed.error  # safe type name only


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
