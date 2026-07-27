# ats-api

The ATS-Ninja-V2 FastAPI backend.

**Current scope:** the async **kit lifecycle** plus delivery-first
ApplicationKit v7 and the default-on grounded JobFitArtifact,
InterviewPrepArtifact, and LinkedInOutreachArtifact — persistence
(async SQLAlchemy 2.x + Alembic + PostgreSQL), a Redis-backed job queue, a
separately-runnable worker, and kit endpoints — on top of the Phase 0 health +
settings plumbing.

- `GET /health` — liveness (unversioned, for infra probes)
- `GET /api/v1/health` — readiness (reports the engine version)
- `POST /api/v1/resume-extractions` — transient multipart PDF, DOCX, or TXT
  extraction; returns safe metadata plus editable text and stores no binary
- `POST /api/v1/kits` — submit reviewed resume text + JD; persists a pending kit, enqueues
  generation, returns `202` with the kit
- `GET /api/v1/kits/{id}` — kit lifecycle status and the persisted result when
  the engine produced one, including honest partial/fallback outcomes
- `GET /api/v1/kits?limit=&offset=` — list kits (newest first)
- `POST /api/v1/document-exports/pdf` — synchronous, request-scoped local PDF
  export of a delivered Resume or Cover Letter from a completed or partially
  completed Kit (generated content or an explicitly supplied local edit, never
  persisted); returns `application/pdf` with a standardized
  `Content-Disposition` filename.
- `POST /api/v1/document-exports/docx` — the equivalent request-scoped,
  single-column Word export, with the same delivery-state and persistence
  rules. See
  [docs/architecture.md](../../docs/architecture.md#grounded-ats-tailoring-typed-requirement-categories-and-direct-pdf-download-fixedadded)
  [ADR-0018](../../docs/adr/0018-local-pdf-rendering.md), and
  [ADR-0021](../../docs/adr/0021-results-first-application-kit-and-docx-export.md).

**Not yet implemented:** authentication, credits/billing, OCR, legacy `.doc`
ingestion, LinkedIn access, contact discovery, or message sending. No placeholder endpoints
pretend these exist.

Resume extraction accepts files up to 10 MB and is deliberately separate from
Kit creation. It validates extensions, browser MIME where supplied, bytes, PDF
structure, and DOCX ZIP bounds; it rejects encrypted and image-only PDFs. Text
is normalized mechanically only, returned for explicit user review, then sent by
the browser through the unchanged JSON Kit contract. Uploaded bytes are never
persisted in PostgreSQL/Redis, passed to Celery, logged, or sent externally.

PDF text runs through three extraction engines (`pypdf`, `PyMuPDF`,
`pdfplumber`); the response's `extraction_engine` field names whichever one
scored highest on structural fidelity (never candidate-content relevance),
and `manual_review_recommended` flags when even the best candidate still
looks structurally uncertain — both fields are additive/optional and safe to
ignore for older clients. See
[docs/architecture.md](../../docs/architecture.md#multi-engine-pdf-extraction-and-atsdocument-quality-audit-fixed).

Creation accepts independent, persisted `include_resume`,
`include_cover_letter`, `include_application_answers`, `include_job_fit`,
`include_interview_prep`, and `include_linkedin_outreach` booleans plus optional
bounded `outreach_context`. The three legacy document-selection flags (resume,
cover letter, and answers) are optional for backward compatibility: omitted
values preserve the existing `requested_mode` behavior; new clients should send
them explicitly. For delivery-state roll-up, a requested resume and cover
letter are the primary documents; answers and the other four typed artifacts
are secondary. Interview preparation or
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
      generate_application_kit (thread) ─────▶ Postgres
                                                (completed | partially_completed |
                                                 needs_input_review | failed)
GET /kits/{id} ◀── current status / result
```

The API depends only on a `JobQueue` interface (`app.queue`): `CeleryJobQueue` in
production, `InlineJobQueue` (in-process) for tests. The DB session factory lives
on `app.state`, populated by the lifespan (prod) or the test fixtures.

`app.services.process_kit` logs a safe timing line — kit id, elapsed
milliseconds, whether `ATS_API_ENGINE_USE_LLM` was on, terminal state, finding
count, and detector codes — on every completion and failure. It never logs a
finding's fact/source span, resume, job description, provider prompt, exception
message, or generated content. Useful for diagnosing a slow or degraded Kit:
`docker compose logs worker | grep '<kit-id>'`. With the LLM path enabled, a
slow first provider call (cold Ollama model load, or lock contention between
concurrent profile/JD extraction calls) adds latency but is independent of
artifact delivery state.

## Delivery-first response contract

ApplicationKit v7 exposes a top-level delivery `state`, JD-owned
`target_role`/`target_company`/`target_confidence`, and a `delivery_reports`
entry for every artifact. Document states are `generated`,
`generated_with_fallback`, `needs_input_review`, `failed`, and
`not_requested`. `partially_completed` exists only at kit/API lifecycle level.
A source-preserving fallback is delivered content and has a real ATS v2
delivered score; it is not represented as `n/a`.

The API lifecycle values are:

- non-terminal: `pending`, `processing`;
- delivered terminal: `completed`, `partially_completed`; and
- review/failure terminal: `needs_input_review`, `failed`.

`completed` means every requested primary (Resume/Cover Letter) and secondary
artifact was delivered. `partially_completed` preserves successfully delivered
siblings when a requested artifact failed. Exports and change actions accept a
partially completed Kit, but export resolution separately requires the selected
document's delivery report to be `generated` or
`generated_with_fallback`. A `needs_input_review` kit can retain a delivered
sibling; selected-artifact delivery reports, rather than the kit roll-up alone,
authorize exports and change actions.

The two new terminal strings are additive values on the existing `/api/v1`
surface; there is no version-header negotiation. Clients must tolerate added
enum values and stop polling for them. Migration `0007_delivery_statuses`
widens `kits.status` from portable `String(20)` to `String(32)` on both
PostgreSQL and SQLite without rewriting old rows.

Persisted JSON compatibility stays at the engine serialization boundary. V1-v6
kits retain their original `schema_version` and content while the read view
infers missing v7 delivery reports/state from historical artifact validation.
Known unversioned Phase 1 records retain the `phase-1/legacy` marker; unknown
schemas are returned as `unknown` without invented artifacts. Compatibility
reads never rewrite stored result JSON or backfill the separate lifecycle
status on an old row; consumers should use `result.state` and delivery reports
when displaying historical delivery. See
[ADR-0023](../../docs/adr/0023-delivery-first-validation-and-application-kit-v7.md).

## Run locally

```bash
# in the shared virtualenv, from the repo root
pip install -e "packages/engine[dev]"   # engine first
pip install -e "apps/api[dev]"

# Requires a reachable PostgreSQL and Redis (see compose.yaml for local ones).
export ATS_API_DATABASE_URL="postgresql+asyncpg://ats:ats@localhost:5432/ats_ninja"
export ATS_API_REDIS_URL="redis://localhost:6379"
# Default-on. See rollback note below before changing.
export ENGINE_DELIVERY_FIRST=1

# Apply migrations, then run the API and the worker (separate processes):
(cd apps/api && alembic upgrade head)
uvicorn app.main:app --reload --app-dir apps/api          # API on :8000
(cd apps/api && celery -A app.tasks worker -l info -Q kits) # worker

# Or run the whole topology in containers:
docker compose up --build                                  # db, redis, migrate, api, worker, web
```

### Delivery-first rollback

`ENGINE_DELIVERY_FIRST` accepts `0`, `false`, `no`, or `off` to disable the
calibrated delivery-first optimizer after both API and worker processes are
restarted. This one-release rollback selects the retained PR-21 score-only
optimization path and skips delivery-first quality proposals. It does not
disable detector fixes, grounding, ApplicationKit v7 delivery states, or
migration 0007. Compose passes the value to both API and worker.
Record affected kit IDs and finding codes when using the switch, then restore
the default. `ENGINE_TAILORING_V2` is the separate tailoring-path compatibility
flag.

## Migrations

```bash
cd apps/api
alembic upgrade head                 # apply
alembic revision -m "describe change"  # create a new revision (edit before applying)
alembic downgrade -1                 # roll back one
```

Migration 0007 is additive for existing data. Downgrading narrows the status
column again without rewriting rows; every currently defined status still fits
the old 20-character width. The extra width is headroom for explicit lifecycle
labels, not a data conversion.

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
