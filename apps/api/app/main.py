from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import kits
from app.api.health import ReadinessResponse, liveness, readiness
from app.config import Settings, get_settings
from app.db import create_db_engine, create_sessionmaker
from app.queue import ArqJobQueue

"""FastAPI application factory.

Phase 1 adds the async kit lifecycle: persistence (async SQLAlchemy) and a
Redis-backed job queue whose work is executed by a separate worker
(`app.worker`). Authentication, billing, and product frontend flows are still
out of scope. The lifespan wires the database sessionmaker and the job queue
onto app state; both are tolerant of a missing Redis so ``/health`` stays up in
degraded/dev environments.
"""

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown: initialize the DB sessionmaker and the job queue.

    Creating the async engine does not open a connection (that happens lazily on
    first query), so startup never blocks on the database. Redis connection is
    attempted but tolerated: if it is unavailable, kit submission returns 503
    while the rest of the API keeps working.
    """
    settings = get_settings()
    app.state.settings = settings

    if getattr(app.state, "sessionmaker", None) is None:
        engine = create_db_engine(settings.database_url, settings.database_echo)
        app.state.db_engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)

    if getattr(app.state, "job_queue", None) is None:
        try:
            pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            app.state.redis_pool = pool
            app.state.job_queue = ArqJobQueue(pool)
        except Exception:
            logger.warning(
                "Redis unavailable at %s; kit submission is disabled until it is reachable.",
                settings.redis_url,
            )

    try:
        yield
    finally:
        db_engine = getattr(app.state, "db_engine", None)
        if db_engine is not None:
            await db_engine.dispose()
        redis_pool = getattr(app.state, "redis_pool", None)
        if redis_pool is not None:
            await redis_pool.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Unversioned liveness for infra health checks.
    app.add_api_route("/health", liveness, methods=["GET"], tags=["health"])

    # Versioned API surface.
    v1 = APIRouter(prefix=settings.api_v1_prefix)
    v1.add_api_route("/health", readiness, methods=["GET"], tags=["health"], response_model=ReadinessResponse)
    v1.include_router(kits.router)
    app.include_router(v1)

    return app


app = create_app()
