from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from ats_engine import application_kit_to_dict, generate_application_kit
from conftest import SAMPLE_JD, SAMPLE_RESUME
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base, create_sessionmaker
from app.models import Kit
from app.schemas import ChangeActionItem, KitStatus
from app.services import apply_kit_change_actions

"""Real PostgreSQL atomic-concurrency test for change actions.

SQLite cannot model PostgreSQL's concurrent-transaction semantics, so this test
only runs when ``ATS_API_TEST_POSTGRES_URL`` points at a reachable PostgreSQL
(the Docker smoke stack sets it). It fires two change-action requests for the
same revision concurrently and asserts that exactly one succeeds and the other
receives a conflict — the atomic conditional UPDATE must never let both win.
"""

POSTGRES_URL = os.environ.get("ATS_API_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="Set ATS_API_TEST_POSTGRES_URL to a reachable PostgreSQL to run the concurrency test.",
)


@pytest_asyncio.fixture
async def pg_engine() -> AsyncIterator[AsyncEngine]:
    assert POSTGRES_URL is not None
    engine = create_async_engine(POSTGRES_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_sessionmaker(pg_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(pg_engine)


async def _seed_completed_v5_kit(sessionmaker: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    kit_result = generate_application_kit(
        resume_text=SAMPLE_RESUME,
        job_description=SAMPLE_JD,
        use_llm=False,
        include_resume=True,
        include_cover_letter=False,
    )
    async with sessionmaker() as session:
        kit = Kit(
            status=KitStatus.COMPLETED,
            resume_text=SAMPLE_RESUME,
            job_description=SAMPLE_JD,
            requested_mode="",
            questions_text="",
            include_resume=True,
            include_cover_letter=False,
            include_application_answers=False,
            result=application_kit_to_dict(kit_result),
            revision=0,
        )
        session.add(kit)
        await session.commit()
        return kit.id


async def _apply(sessionmaker: async_sessionmaker[AsyncSession], kit_id: uuid.UUID, change_id: str) -> str:
    async with sessionmaker() as session:
        outcome = await apply_kit_change_actions(
            session,
            kit_id,
            expected_revision=0,
            actions=[ChangeActionItem(change_id=change_id, action="accept")],
        )
        return outcome.status


async def test_concurrent_change_actions_are_atomic(pg_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    kit_id = await _seed_completed_v5_kit(pg_sessionmaker)

    # Two independent sessions both read revision 0 and try to advance it.
    results = await asyncio.gather(
        _apply(pg_sessionmaker, kit_id, "resume::summary"),
        _apply(pg_sessionmaker, kit_id, "resume::summary"),
    )

    assert sorted(results) == ["conflict", "ok"], f"expected exactly one winner, got {results}"

    # The winner advanced the revision exactly once.
    async with pg_sessionmaker() as session:
        kit = await session.get(Kit, kit_id)
        assert kit is not None
        assert kit.revision == 1
