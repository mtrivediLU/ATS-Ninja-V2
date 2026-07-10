from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import kits
from app.api.health import ReadinessResponse, liveness, readiness
from app.celery_app import celery_app
from app.config import Settings, get_settings
from app.db import create_db_engine, create_sessionmaker
from app.queue import CeleryJobQueue

"""FastAPI application factory.

Owns the async kit lifecycle: persistence (async SQLAlchemy) and a Celery/Redis
job queue whose work is executed by a separate worker (`app.tasks`).
Authentication, billing, and product frontend flows are out of scope.

Startup wiring: unlike a broker connection-pool model (which required creating
and later closing a Redis pool during the lifespan), Celery manages its own
broker connection lazily on first dispatch. So the lifespan only sets up the
database sessionmaker and installs the `CeleryJobQueue` dispatcher onto app
state — there is no broker pool to open or close here.
"""

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown: initialize the DB sessionmaker and the job dispatcher.

    Creating the async engine does not open a connection (that happens lazily on
    first query), so startup never blocks on the database. The Celery dispatcher
    holds no connection; the broker is contacted only when a kit is enqueued.
    """
    settings = get_settings()
    app.state.settings = settings

    if getattr(app.state, "sessionmaker", None) is None:
        engine = create_db_engine(settings.database_url, settings.database_echo)
        app.state.db_engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)

    if getattr(app.state, "job_queue", None) is None:
        app.state.job_queue = CeleryJobQueue(celery_app)

    try:
        yield
    finally:
        db_engine = getattr(app.state, "db_engine", None)
        if db_engine is not None:
            await db_engine.dispose()


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
