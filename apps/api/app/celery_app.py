from __future__ import annotations

from celery import Celery

from app.config import get_settings

"""Celery application (Redis broker).

This module is intentionally light: it constructs and configures the Celery app
but imports **no** task code and **no** engine code, so the API process (which
imports it only to dispatch by task name) stays decoupled from the worker's task
implementation. The worker imports ``app.tasks`` (which registers the task).

Reliability decisions for long-running kit generation are made explicitly here
and documented in ADR-0006 (docs/adr/):

- ``task_acks_late`` + ``task_reject_on_worker_lost``: acknowledge a message only
  after the task finishes, and requeue it if a worker dies mid-task. This gives
  **at-least-once** delivery; PostgreSQL kit state (plus the terminal/duplicate
  guard in ``process_kit``) protects application behavior. We do NOT claim
  exactly-once.
- ``worker_prefetch_multiplier = 1``: a worker holds at most one extra message,
  so long tasks are dispatched fairly and a lost worker drags down as little
  in-flight work as possible.
- ``broker_transport_options.visibility_timeout``: the Redis re-delivery window
  is set well above the longest expected kit runtime, so a still-running task is
  not spuriously redelivered to another worker.
- No result backend: Celery results are NOT used as application state. All kit
  status/results/failures live in PostgreSQL, the single source of truth.
- Task args carry only the kit id (a string) — never resume/JD text, bytes, or
  the generated payload.
"""

# One hour: comfortably longer than any expected kit-generation run, so Redis
# does not redeliver an in-flight task.
_VISIBILITY_TIMEOUT_SECONDS = 60 * 60


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery("ats_ninja")
    app.conf.update(
        broker_url=settings.redis_url,
        # PostgreSQL is the source of truth; do not persist results in the broker.
        result_backend=None,
        task_ignore_result=True,
        task_store_errors_even_if_ignored=False,
        # Only JSON crosses the wire; the task payload is just the kit id.
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_default_queue="kits",
        worker_concurrency=settings.worker_concurrency,
        # Delivery reliability for long-running, idempotency-guarded work.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_track_started=False,
        broker_connection_retry_on_startup=True,
        broker_transport_options={"visibility_timeout": _VISIBILITY_TIMEOUT_SECONDS},
    )
    return app


celery_app = create_celery_app()
