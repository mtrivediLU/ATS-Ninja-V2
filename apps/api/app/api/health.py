from __future__ import annotations

from ats_engine import __version__ as engine_version
from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

"""Health endpoints.

``/health`` (liveness) is unversioned so container/orchestrator health checks
have a stable path. ``{prefix}/health`` (readiness) additionally reports the
engine version, proving the API is wired to ``packages/engine``.
"""

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str


class ReadinessResponse(HealthResponse):
    engine_version: str


@router.get("/health", tags=["health"], response_model=HealthResponse)
def liveness() -> HealthResponse:
    """Liveness probe: the process is up and serving."""
    settings = get_settings()
    return HealthResponse(status="ok", service=settings.app_name, environment=settings.environment)


def readiness() -> ReadinessResponse:
    """Readiness probe: dependencies (currently the engine) are importable."""
    settings = get_settings()
    return ReadinessResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
        engine_version=engine_version,
    )
