# ats-api

The ATS-Ninja-V2 FastAPI backend.

**Current scope:** the async **kit lifecycle** plus ApplicationKit v4 and the
default-on grounded JobFitArtifact, InterviewPrepArtifact, and
LinkedInOutreachArtifact — persistence
(async SQLAlchemy 2.x + Alembic + PostgreSQL), a Redis-backed job queue, a
separately-runnable worker, and kit endpoints — on top of the Phase 0 health +
settings plumbing.

- `GET /health` — liveness (unversioned, for infra probes)
- `GET /api/v1/health` — readiness (reports the engine version)
- `POST /api/v1/resume-extractions` — transient multipart PDF, DOCX, or TXT
  extraction; returns safe metadata plus editable text and stores no binary
- `POST /api/v1/kits` — submit reviewed resume text + JD; persists a pending kit, enqueues
  generation, returns `202` with the kit
- `GET /api/v1/kits/{id}` — kit status and, once completed, its result
- `GET /api/v1/kits?limit=&offset=` — list kits (newest first)

**Not yet implemented:** authentication, credits/billing, OCR, legacy `.doc`
ingestion, LinkedIn access, contact discovery, or message sending. No placeholder endpoints
pretend these exist.

Resume extraction accepts files up to 10 MB and is deliberately separate from
Kit creation. It validates extensions, browser MIME where supplied, bytes, PDF
structure, and DOCX ZIP bounds; it rejects encrypted and image-only PDFs. Text
is normalized mechanically only, returned for explicit user review, then sent by
the browser through the unchanged JSON Kit contract. Uploaded bytes are never
persisted in PostgreSQL/Redis, passed to Celery, logged, or sent externally.

Creation accepts independent, persisted `include_resume`,
`include_cover_letter`, `include_application_answers`, `include_job_fit`,
`include_interview_prep`, and `include_linkedin_outreach` booleans plus optional
bounded `outreach_context`. The three primary flags are optional for backward
compatibility: omitted values preserve the existing `requested_mode` behavior;
new clients should send them explicitly. Interview preparation or
outreach may use an internal deterministic fit assessment even when JobFit
persistence is disabled; completed results remain in PostgreSQL's existing JSON
result column. Migration 0005 stores the resolved primary selection, while
migration 0004 stores the outreach option and only the context needed to
reproduce the requested drafts.

All career business logic lives in `packages/engine` (`ats-engine`); this service
persists, queues, and orchestrates it — it owns no domain logic.

## Architecture

```
POST /kits ──▶ Postgres (Kit: pending) ──▶ Redis (Celery broker) ──▶ 202
                                              │
        worker (celery -A app.tasks worker -Q kits) dequeues
                                              │
      generate_application_kit (thread) ─────▶ Postgres (Kit: completed|failed)
GET /kits/{id} ◀── current status / result
```

The API depends only on a `JobQueue` interface (`app.queue`): `CeleryJobQueue` in
production, `InlineJobQueue` (in-process) for tests. The DB session factory lives
on `app.state`, populated by the lifespan (prod) or the test fixtures.

`app.services.process_kit` logs a safe timing line — kit id, elapsed
milliseconds, and whether `ATS_API_ENGINE_USE_LLM` was on — on every
completion and failure, never the resume, job description, or generated
content. Useful for diagnosing a slow Kit: `docker compose logs worker | grep
'<kit-id>'`. With the LLM path enabled, a slow first provider call (cold
Ollama model load, or lock contention between the concurrent profile/JD
extraction calls) adds latency but is independent of whether an artifact ends
up withheld — those are two different failure classes and the log line
disambiguates which one you're looking at.

## Run locally

```bash
# in the shared virtualenv, from the repo root
pip install -e "packages/engine[dev]"   # engine first
pip install -e "apps/api[dev]"

# Requires a reachable PostgreSQL and Redis (see compose.yaml for local ones).
export ATS_API_DATABASE_URL="postgresql+asyncpg://ats:ats@localhost:5432/ats_ninja"
export ATS_API_REDIS_URL="redis://localhost:6379"

# Apply migrations, then run the API and the worker (separate processes):
(cd apps/api && alembic upgrade head)
uvicorn app.main:app --reload --app-dir apps/api          # API on :8000
(cd apps/api && celery -A app.tasks worker -l info -Q kits) # worker

# Or run the whole topology in containers:
docker compose up --build                                  # db, redis, migrate, api, worker, web
```

## Migrations

```bash
cd apps/api
alembic upgrade head                 # apply
alembic revision -m "describe change"  # create a new revision (edit before applying)
alembic downgrade -1                 # roll back one
```

## Quality gates

```bash
pytest apps/api
ruff check apps/api
ruff format --check apps/api
mypy --config-file apps/api/pyproject.toml apps/api/app
```

Tests are hermetic: they use in-memory SQLite (async) and the in-process queue,
with the engine forced onto its deterministic path (`engine_use_llm=False`), so
no PostgreSQL, Redis, or model server is required.
