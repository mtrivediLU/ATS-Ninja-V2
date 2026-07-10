# ADR-0006 — Replace the arq worker with Celery (Redis broker)

- Status: Accepted
- Date: 2026-07-10
- Supersedes: the queue/worker implementation choice in [ADR-0005](0005-async-kit-lifecycle.md)

## Context

Phase 1 (ADR-0005) implemented the async kit lifecycle with **arq** as the
Redis-backed task queue. arq is lightweight and async-native, which fit the
FastAPI + async-SQLAlchemy stack, but for the production task-transport layer we
want the industry-standard, operationally mature option with the broadest
ecosystem, tooling, and team familiarity. This is a focused architecture
correction to the queue/worker transport only — nothing else about Phase 1
changes.

## Decision

Replace arq with **Celery**, using **Redis as the broker**. The change is
surgical: it touches only the queue/worker implementation and directly related
configuration, startup wiring, dependencies, tests, the Compose worker command,
and documentation. Preserved unchanged: the API contract (`POST/GET /kits`),
the `pending → processing → completed | failed` lifecycle, async
SQLAlchemy/PostgreSQL persistence, Alembic migrations, the `Kit` and response
schemas, and the `JobQueue` dispatcher boundary.

### Boundary and state

- The service-facing **`JobQueue`** interface is kept. `ArqJobQueue` is replaced
  by **`CeleryJobQueue`**, which dispatches **by task name** (`send_task`), so
  request handlers never import the worker task implementation. `InlineJobQueue`
  (in-process) is retained for tests and single-process runs.
- **`services.py` stays isolated** from the task implementation: it owns the kit
  lifecycle transitions and is the only place that calls the engine; both the API
  and the Celery task call into it. The task module imports the service, never
  the reverse.
- **PostgreSQL remains the single source of truth** for kit status, results,
  validation info, and failures. The Celery **result backend is disabled**
  (`result_backend=None`, `task_ignore_result=True`) — it is never used as
  application state.
- **Task args carry only the kit id** (a JSON string). Resume/JD text, bytes, and
  the generated/validation payloads never cross Redis. The worker loads all state
  from PostgreSQL.

### Startup wiring change

arq required creating a Redis connection **pool** during the FastAPI lifespan
(`create_pool` / `RedisSettings`) and closing it on shutdown. Celery manages its
own broker connection lazily on first dispatch, so that wiring is removed. The
lifespan now only initializes the async DB sessionmaker and installs the
`CeleryJobQueue` dispatcher onto app state — there is no broker pool to open or
close in the API process.

### Async/sync bridge

Celery tasks are synchronous while the service layer is async. Each task runs its
coroutine on a fresh event loop (`asyncio.run`) with a short-lived engine created
and disposed inside that same loop, avoiding cross-event-loop reuse of asyncpg
connections and keeping the worker free of global mutable state. The engine's
synchronous `run_pipeline` continues to run in a thread (`asyncio.to_thread`).

### Reliability decisions (deliberate)

- `task_acks_late = True` + `task_reject_on_worker_lost = True`: acknowledge only
  after completion and requeue if a worker dies mid-task → **at-least-once**
  delivery. We do **not** claim exactly-once.
- `worker_prefetch_multiplier = 1`: long tasks are dispatched fairly and a lost
  worker drags down minimal in-flight work.
- `broker_transport_options.visibility_timeout = 3600s`: Redis re-delivery window
  set well above the longest expected kit run, so an in-flight task is not
  spuriously redelivered.
- **Bounded retry (max 3)** with exponential backoff (10/20/40s, capped 5 min)
  for **explicitly classified transient infrastructure failures only** (database
  connectivity: `OperationalError`, `InterfaceError`, `ConnectionError`,
  `TimeoutError`, `OSError`). Engine/validation/deterministic failures are handled
  inside `process_kit` (kit → failed, persisted) and are **never retried**. On
  retry exhaustion or an unexpected non-transient error, the kit is marked failed
  so it is never left stuck in `processing`.
- **Duplicate/terminal protection**: `process_kit` (and `mark_kit_failed`) skip a
  kit already in a terminal state, so at-least-once redelivery cannot reprocess or
  clobber a finished kit.
- Engine failures never crash the worker and never expose tracebacks to clients
  (clients read kit state only from PostgreSQL).

## Consequences

- Standard, battle-tested task transport with a large ecosystem (monitoring,
  routing, retries) and broad operational familiarity, at the cost of a heavier
  dependency than arq.
- The API process no longer manages a broker connection pool; startup is simpler.
- Delivery semantics are explicit and documented; correctness rests on
  PostgreSQL lifecycle state, not on the broker or a result backend.
- Validated end-to-end in containers (Postgres + Redis + Celery worker),
  including API and worker restarts with the completed kit still retrievable.
