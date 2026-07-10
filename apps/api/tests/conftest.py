from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Base, create_sessionmaker
from app.main import create_app
from app.queue import InlineJobQueue

"""Hermetic API test fixtures.

Tests run against an in-memory SQLite database (via aiosqlite + StaticPool so a
single shared connection is used) and the in-process InlineJobQueue, so the full
kit lifecycle is exercised without a real PostgreSQL or Redis. The engine runs
fully deterministically (``engine_use_llm=False``), so tests are offline and
reproducible.
"""


@pytest.fixture
def settings() -> Settings:
    return Settings(engine_use_llm=False)


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest_asyncio.fixture
async def client(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings=settings)
    app.state.sessionmaker = sessionmaker
    app.state.job_queue = InlineJobQueue(sessionmaker, settings)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


# Synthetic, non-personal inputs that the deterministic pipeline handles cleanly.
SAMPLE_RESUME = (
    "Jordan Rivera\n"
    "555-201-3344 | jordan.rivera@oldschool.edu | linkedin.com/in/jordanrivera\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Acme Analytics Toronto, ON\n"
    "Senior Data Engineer Jan 2020 - Mar 2024\n"
    "- Architected and built a centralized data warehouse using PostgreSQL, creating a\n"
    "unified source of truth serving millions of users across the platform.\n"
    "- Optimized deployment workflows, maintaining 100% uptime for critical\n"
    "production services and reducing release time by 40%.\n"
    "Beta Retail Group Ottawa, ON\n"
    "Data Analyst Jun 2016 - Dec 2019\n"
    "- Built SQL reporting for a team of 12 analysts.\n"
    "EDUCATION\n"
    "Carleton University Ottawa, ON\n"
    "Bachelor of Computer Science 2012 - 2016\n"
)

SAMPLE_JD = (
    "Job Title: AI Engineer\n"
    "Company: Northstar Analytics\n"
    "Location: Toronto, Ontario hybrid\n"
    "Required qualifications:\n"
    "- Python for production data and AI systems\n"
    "- SQL and data warehouse experience\n"
    "- ETL pipelines and stakeholder communication\n"
    "Preferred qualifications:\n"
    "- Azure, Docker, Tableau, Power BI, and Java microservices\n"
    "Responsibilities:\n"
    "- Develop analytics pipelines and reporting for business teams.\n"
    "The team uses Python, SQL, Azure, Docker, Tableau, and ETL patterns."
)
