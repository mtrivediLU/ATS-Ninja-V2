from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

"""Async SQLAlchemy 2.x database layer.

Engine and sessionmaker are constructed from a URL so any runtime (the API
lifespan, the async worker, or a test) can build its own — there is no global
mutable engine. The FastAPI request dependency reads the sessionmaker off
``app.state``, which the lifespan (production) or the test fixture populates.
"""


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def create_db_engine(url: str, echo: bool = False) -> AsyncEngine:
    """Create an async engine. ``pool_pre_ping`` guards against stale connections."""
    return create_async_engine(url, echo=echo, pool_pre_ping=True, future=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory. ``expire_on_commit=False`` keeps objects usable after commit."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    sessionmaker: async_sessionmaker[AsyncSession] | None = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise RuntimeError("Database sessionmaker is not configured on app.state.")
    return sessionmaker


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped async session."""
    sessionmaker = get_sessionmaker(request)
    async with sessionmaker() as session:
        yield session
