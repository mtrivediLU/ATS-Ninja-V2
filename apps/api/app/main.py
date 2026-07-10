from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import ReadinessResponse, liveness, readiness
from app.config import Settings, get_settings

"""FastAPI application factory.

Phase 0 intentionally exposes only health/settings plumbing. It does NOT
implement kit generation, auth, billing, or persistence — those arrive in later
phases. The structure (settings, versioned router, lifespan, app factory) is
built so SQLAlchemy 2.x, Alembic, Postgres, Redis, and an async worker can be
adopted without reshaping the app.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan hook (startup/shutdown).

    A natural home for future connection-pool and worker-client setup. For now
    it just pins the resolved settings onto app state.
    """
    app.state.settings = get_settings()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
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

    # Versioned API surface. Future feature routers mount under this prefix.
    v1 = APIRouter(prefix=settings.api_v1_prefix)
    v1.add_api_route("/health", readiness, methods=["GET"], tags=["health"], response_model=ReadinessResponse)
    app.include_router(v1)

    return app


app = create_app()
