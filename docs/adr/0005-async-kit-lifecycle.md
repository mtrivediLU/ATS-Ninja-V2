# ADR-0005 — Async kit lifecycle: async SQLAlchemy + arq/Redis worker behind a queue interface

- Status: Superseded by [ADR-0006](0006-replace-arq-with-celery.md) (queue/worker only)
- Date: 2026-07-10
- Phase: 1

> **Note:** The async kit lifecycle, async SQLAlchemy/PostgreSQL persistence,
> Alembic migrations, and the `JobQueue` dispatcher boundary described here are
> still current. Only the queue/worker *implementation* changed: the arq worker
> was replaced by **Celery (Redis broker)**. See ADR-0006. References to arq
> below are historical.

## Context

Phase 0 delivered a deterministic engine callable in-process. To turn it into a
real product capability the API needs to (a) persist submitted work and its
result, and (b) run generation asynchronously — generation is potentially slow
(the LLM path can take tens of seconds), so it must not block a request. This
must stay portable, testable, low-cost, and free of premature enterprise
machinery, and it must not weaken the truth-grounding guarantees.

## Decision

**Persistence — async SQLAlchemy 2.x + Alembic + PostgreSQL.** The API is async
(FastAPI), so the database layer is async (`asyncpg`). A single `kits` table
models the lifecycle (`pending → processing → completed | failed`) with inputs,
a JSON result, and timestamps. Column types are chosen to be **portable**
(`Uuid`, generic `JSON`), so the identical models and migration run on
PostgreSQL in production and on in-memory SQLite in tests. Schema changes go
through Alembic (async `env.py`); a one-shot `migrate` Compose service applies
them before `api`/`worker` start.

**Queueing — a `JobQueue` interface with an arq/Redis implementation.** The API
depends only on `JobQueue`. `ArqJobQueue` enqueues onto Redis for a separate
worker; `InlineJobQueue` runs the job in-process for tests and single-process
use. arq was chosen over Celery/RQ/Dramatiq because it is async-native
(matching the FastAPI + async-SQLAlchemy stack), lightweight, and Redis-only —
no broker sprawl, minimal lock-in, no heavyweight enterprise abstractions.

**Worker — a separate process sharing the image and the kit service.** Run with
`arq app.worker.WorkerSettings`. The synchronous, CPU/IO-bound `run_pipeline`
runs via `asyncio.to_thread` so it never blocks the worker's event loop. The kit
service (`process_kit`) is the single code path both the worker and the inline
queue execute, so tests exercise exactly what production runs.

## Consequences

- The API returns `202` immediately; generation happens out-of-band and scales
  by running more worker replicas independently of request-serving.
- Infrastructure lives behind an interface (like the engine's `LLMProvider`),
  so tests are hermetic (SQLite + inline queue, no Postgres/Redis) while the
  real path is a drop-in.
- Truth-grounding is unchanged: validation runs inside `run_pipeline`; the result
  records `validation_errors` and the fatal subset. An engine failure marks the
  kit `failed` without crashing the worker.
- Portable types keep one migration valid across engines; if a Postgres-specific
  feature (e.g. `JSONB` indexing) is later needed, it can be added as a
  Postgres-only migration step without breaking SQLite tests.
- Validated end-to-end in containers (Postgres + Redis + worker), including the
  live-LLM path, with all truth-grounding gates passing.
