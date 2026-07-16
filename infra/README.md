# infra

Local Docker and future deployment/infrastructure assets for ATS-Ninja-V2.

## Contents

- `docker/api.Dockerfile` — FastAPI backend image (installs the engine + API). The
  same image runs the API server, the one-shot migration step, and the Celery
  worker.
- `docker/web.Dockerfile` — Next.js frontend image (standalone output, non-root).
- `../compose.yaml` — local development topology (see below).

## Usage

Requires a running Docker daemon (Docker Desktop or `colima start`).

```bash
# from the repository root
docker compose config      # validate the topology (no daemon required)
docker compose up --build  # build images and run the full stack
```

- API: http://localhost:8000 (`/health`, `/api/v1/health`, `/docs`)
- Web: http://localhost:3000

## Current topology

The stack runs the persisted, asynchronous kit lifecycle (Phase 1) that generates
a versioned, truth-grounded ApplicationKit (Phase 2A):

| Service | Image | Role |
| --- | --- | --- |
| `db` | `postgres:16-alpine` | PostgreSQL — the authoritative store of kit state/results. |
| `redis` | `redis:7-alpine` | Redis — the **Celery broker** (not used as result storage). |
| `migrate` | `ats-ninja-v2/api:dev` | One-shot `alembic upgrade head`; runs to completion, then `api`/`worker` start. |
| `api` | `ats-ninja-v2/api:dev` | FastAPI backend (`POST/GET /api/v1/kits`). |
| `worker` | `ats-ninja-v2/api:dev` | Celery worker (`celery -A app.tasks worker -Q kits`) running the ApplicationKit generation. |
| `web` | built from `web.Dockerfile` | Next.js frontend (presentation only). |

Startup ordering is enforced with health checks and
`depends_on: { condition: service_completed_successfully }` on `migrate`. The
Celery task payload is the **kit id only**; the worker loads all state from
PostgreSQL. See [ADR-0005](../docs/adr/0005-async-kit-lifecycle.md) and
[ADR-0006](../docs/adr/0006-replace-arq-with-celery.md).

## Not yet implemented

Production deployment manifests, managed Postgres/Redis, object storage for
downloadable artifacts, and worker autoscaling are **future** work and are not
part of this compose file. Candidate documents are not persisted to disk today —
resume/JD text lives only in the `kits` table.
