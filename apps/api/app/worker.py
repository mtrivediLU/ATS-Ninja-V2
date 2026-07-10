from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from arq.connections import RedisSettings

from app.config import get_settings
from app.db import create_db_engine, create_sessionmaker
from app.services import process_kit

"""Async worker entrypoint (arq).

Run separately from the API with:

    arq app.worker.WorkerSettings

The worker owns its own database engine/sessionmaker (independent of the API
process), so it scales horizontally on its own. Each ``generate_kit`` job runs
the engine for one kit and persists the outcome via the shared kit service.
"""

logger = logging.getLogger(__name__)


async def generate_kit(ctx: dict[str, Any], kit_id: str) -> None:
    """arq task: generate the kit identified by ``kit_id``."""
    sessionmaker = ctx["sessionmaker"]
    settings = ctx["settings"]
    async with sessionmaker() as session:
        await process_kit(session, UUID(kit_id), settings)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    engine = create_db_engine(settings.database_url, settings.database_echo)
    ctx["engine"] = engine
    ctx["sessionmaker"] = create_sessionmaker(engine)
    ctx["settings"] = settings
    logger.info("Worker started; database engine initialized.")


async def shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()
    logger.info("Worker shut down; database engine disposed.")


class WorkerSettings:
    """arq worker configuration (discovered by the ``arq`` CLI)."""

    functions = [generate_kit]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = get_settings().worker_max_jobs
