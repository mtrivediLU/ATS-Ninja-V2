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
    assert result["schema_version"] == "application-kit/v5"
    assert result["job_fit"] is not None
    assert result["job_fit"]["requirements"]
    assert result["job_fit"]["consistency"]["passed"] is True
    assert kit["include_job_fit"] is True
    assert kit["include_interview_prep"] is True
    assert result["interview_prep"] is not None
    assert result["interview_prep"]["questions"]
    assert result["interview_prep"]["consistency"]["passed"] is True
    assert kit["include_linkedin_outreach"] is True
    assert result["linkedin_outreach"] is not None
    assert result["linkedin_outreach"]["drafts"]
    assert result["linkedin_outreach"]["relationship_validation"]["passed"] is True
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


async def test_openapi_exposes_product_intelligence_requests_and_typed_responses(client: httpx.AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schemas = response.json()["components"]["schemas"]
    create_properties = schemas["KitCreate"]["properties"]
    assert {"include_resume", "include_cover_letter", "include_application_answers"} <= create_properties.keys()
    assert create_properties["include_interview_prep"]["default"] is True
    assert create_properties["include_linkedin_outreach"]["default"] is True
    assert "outreach_context" in create_properties
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
    assert "LinkedInOutreachArtifactResponse" in schemas
    outreach_properties = schemas["LinkedInOutreachArtifactResponse"]["properties"]
    assert {
        "strategy_summary",
        "drafts",
        "validation",
        "consistency",
        "relationship_validation",
        "claims",
        "target_context",
        "relationship_context",
    } <= outreach_properties.keys()


async def test_submit_kit_supports_all_six_independent_artifacts(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/kits",
        json={
            "resume_text": SAMPLE_RESUME,
            "job_description": SAMPLE_JD,
            "questions_text": "Why this role?",
            "include_resume": True,
            "include_cover_letter": True,
            "include_application_answers": True,
            "include_job_fit": True,
            "include_interview_prep": True,
            "include_linkedin_outreach": True,
        },
    )
    assert response.status_code == 202
    created = response.json()
    assert created["include_resume"] is True
    assert created["include_cover_letter"] is True
    assert created["include_application_answers"] is True

    body = (await client.get(f"/api/v1/kits/{created['id']}")).json()
    result = body["result"]
    assert result["resolved_mode"] == "RCQ"
    assert result["resume"] is not None
    assert result["cover_letter"] is not None
    assert result["answers"] is not None
    assert result["job_fit"] is not None
    assert result["interview_prep"] is not None
    assert result["linkedin_outreach"] is not None


async def test_submit_kit_respects_explicit_false_primary_flags(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/kits",
        json={
            "resume_text": SAMPLE_RESUME,
            "job_description": SAMPLE_JD,
            "include_resume": False,
            "include_cover_letter": False,
            "include_application_answers": False,
            "include_job_fit": True,
            "include_interview_prep": False,
            "include_linkedin_outreach": False,
        },
    )
    assert response.status_code == 202
    body = (await client.get(f"/api/v1/kits/{response.json()['id']}")).json()
    assert body["include_resume"] is False
    assert body["include_cover_letter"] is False
    assert body["include_application_answers"] is False
    assert body["result"]["resume"] is None
    assert body["result"]["cover_letter"] is None
    assert body["result"]["answers"] is None
    assert body["result"]["job_fit"] is not None


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
    assert body["result"]["schema_version"] == "application-kit/v5"
    assert body["result"]["job_fit"] is None
    assert body["include_interview_prep"] is True
    assert body["result"]["interview_prep"] is not None
    assert body["result"]["linkedin_outreach"] is not None


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
    assert body["result"]["linkedin_outreach"] is not None


async def test_submit_kit_can_disable_outreach_and_persist_typed_context(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    context = {
        "recipient_name": "Avery Chen",
        "recipient_title": "Engineering Manager",
        "recipient_company": "Northstar Analytics",
        "audience": "hiring_manager",
        "requested_intent": "follow_up",
        "has_applied": True,
        "application_date": "2026-07-16",
        "shared_affiliation": "Carleton alumni network",
        "portfolio_url": "https://portfolio.example/jordan",
    }
    response = await client.post(
        "/api/v1/kits",
        json={
            "resume_text": SAMPLE_RESUME,
            "job_description": SAMPLE_JD,
            "include_linkedin_outreach": False,
            "outreach_context": context,
        },
    )
    assert response.status_code == 202
    kit_id = response.json()["id"]
    body = (await client.get(f"/api/v1/kits/{kit_id}")).json()
    assert body["include_linkedin_outreach"] is False
    assert body["result"]["linkedin_outreach"] is None

    from app.models import Kit

    async with sessionmaker() as session:
        persisted = await session.get(Kit, uuid.UUID(kit_id))
        assert persisted is not None
        assert persisted.include_linkedin_outreach is False
        assert persisted.outreach_context == context


async def test_submit_kit_generates_personalized_outreach_without_persisted_fit_or_prep(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/kits",
        json={
            "resume_text": SAMPLE_RESUME,
            "job_description": SAMPLE_JD,
            "include_job_fit": False,
            "include_interview_prep": False,
            "outreach_context": {
                "recipient_name": "Avery Chen",
                "audience": "recruiter",
                "has_applied": True,
                "application_status": "submitted",
            },
        },
    )
    assert response.status_code == 202
    body = (await client.get(f"/api/v1/kits/{response.json()['id']}")).json()
    assert body["result"]["job_fit"] is None
    assert body["result"]["interview_prep"] is None
    outreach = body["result"]["linkedin_outreach"]
    assert outreach is not None
    assert any("Avery Chen" in draft["text"] for draft in outreach["drafts"])
    assert any(draft["id"] == "post-application-follow-up" for draft in outreach["drafts"])
    assert outreach["relationship_validation"]["passed"] is True


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
        assert done.result["schema_version"] == "application-kit/v5"
        assert done.result["job_fit"] is not None
        assert done.result["interview_prep"] is not None
        assert done.result["linkedin_outreach"] is not None
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


# --------------------------------------------------------------------------- #
# ApplicationKit v5: match report, change actions, lineage
# --------------------------------------------------------------------------- #
async def _create_completed_kit(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/kits",
        json={
            "resume_text": SAMPLE_RESUME,
            "job_description": SAMPLE_JD,
            "include_resume": True,
            "include_cover_letter": True,
        },
    )
    assert response.status_code == 202
    kit_id = response.json()["id"]
    fetched = await client.get(f"/api/v1/kits/{kit_id}")
    body = fetched.json()
    assert body["status"] == "completed"
    return body


async def test_new_kit_is_v5_with_match_report_and_revision(client: httpx.AsyncClient) -> None:
    body = await _create_completed_kit(client)
    result = body["result"]
    assert result["schema_version"] == "application-kit/v5"
    assert result["match_report"] is not None
    report = result["match_report"]
    assert 0 <= report["original_ats_match"]["score"] <= 100
    assert 0 <= report["alignment_score"] <= 100
    assert report["fit_category"] in {"strong_fit", "good_fit", "partial_fit", "stretch_role", "low_alignment"}
    assert report["disclaimer"]
    assert body["revision"] == 0
    assert body["parent_kit_id"] is None
    assert "stages_ms" in result["stage_timings"]
    # The resume change ledger is present.
    assert isinstance(result["resume"]["change_ledger"], list)


async def test_change_action_round_trip_increments_revision(client: httpx.AsyncClient) -> None:
    body = await _create_completed_kit(client)
    kit_id = body["id"]
    ledger = body["result"]["resume"]["change_ledger"]
    reversible = next(record for record in ledger if record["reversible"])
    response = await client.post(
        f"/api/v1/kits/{kit_id}/change-actions",
        json={"expected_revision": 0, "actions": [{"change_id": reversible["id"], "action": "accept"}]},
    )
    assert response.status_code == 200
    assert response.json()["revision"] == 1
    # Persisted: a fresh GET reflects the new revision.
    refetched = await client.get(f"/api/v1/kits/{kit_id}")
    assert refetched.json()["revision"] == 1


async def test_change_action_revision_conflict_returns_409(client: httpx.AsyncClient) -> None:
    body = await _create_completed_kit(client)
    kit_id = body["id"]
    reversible = next(r for r in body["result"]["resume"]["change_ledger"] if r["reversible"])
    response = await client.post(
        f"/api/v1/kits/{kit_id}/change-actions",
        json={"expected_revision": 5, "actions": [{"change_id": reversible["id"], "action": "accept"}]},
    )
    assert response.status_code == 409


async def test_change_action_irreversible_rejection_returns_422(client: httpx.AsyncClient) -> None:
    body = await _create_completed_kit(client)
    kit_id = body["id"]
    ledger = body["result"]["resume"]["change_ledger"]
    irreversible = next((r for r in ledger if not r["reversible"]), None)
    if irreversible is None:
        pytest.skip("no irreversible ledger record in this deterministic kit")
    response = await client.post(
        f"/api/v1/kits/{kit_id}/change-actions",
        json={"expected_revision": 0, "actions": [{"change_id": irreversible["id"], "action": "reject"}]},
    )
    assert response.status_code == 422


async def test_change_action_unknown_id_returns_422(client: httpx.AsyncClient) -> None:
    body = await _create_completed_kit(client)
    kit_id = body["id"]
    response = await client.post(
        f"/api/v1/kits/{kit_id}/change-actions",
        json={"expected_revision": 0, "actions": [{"change_id": "does::not::exist", "action": "accept"}]},
    )
    assert response.status_code == 422


async def test_delete_kit(client: httpx.AsyncClient) -> None:
    body = await _create_completed_kit(client)
    kit_id = body["id"]
    response = await client.delete(f"/api/v1/kits/{kit_id}")
    assert response.status_code == 204
    assert (await client.get(f"/api/v1/kits/{kit_id}")).status_code == 404
    # Deleting a missing kit is a 404.
    assert (await client.delete(f"/api/v1/kits/{uuid.uuid4()}")).status_code == 404


async def test_regenerate_creates_linked_kit(client: httpx.AsyncClient) -> None:
    body = await _create_completed_kit(client)
    source_id = body["id"]
    response = await client.post(f"/api/v1/kits/{source_id}/regenerate")
    assert response.status_code == 202
    regenerated = response.json()
    assert regenerated["id"] != source_id
    assert regenerated["parent_kit_id"] == source_id
    assert regenerated["revision"] == 0
    # The source kit is untouched.
    assert (await client.get(f"/api/v1/kits/{source_id}")).status_code == 200
    # Regenerating a missing kit is a 404.
    assert (await client.post(f"/api/v1/kits/{uuid.uuid4()}/regenerate")).status_code == 404


async def test_pdf_export_uses_current_revision(client: httpx.AsyncClient) -> None:
    body = await _create_completed_kit(client)
    kit_id = body["id"]
    reversible = next(r for r in body["result"]["resume"]["change_ledger"] if r["reversible"])
    await client.post(
        f"/api/v1/kits/{kit_id}/change-actions",
        json={"expected_revision": 0, "actions": [{"change_id": reversible["id"], "action": "reject"}]},
    )
    export = await client.post(
        "/api/v1/document-exports/pdf",
        json={"kit_id": kit_id, "artifact_type": "resume", "template_id": "classic"},
    )
    assert export.status_code == 200
    assert export.headers["content-type"] == "application/pdf"
