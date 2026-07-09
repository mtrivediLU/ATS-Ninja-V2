# infra

Local Docker and future deployment/infrastructure assets for ATS-Ninja-V2.

## Contents

- `docker/api.Dockerfile` — FastAPI backend image (installs the engine + API).
- `docker/web.Dockerfile` — Next.js frontend image (standalone output, non-root).
- `../compose.yaml` — Phase 0 local topology (`api` + `web` only).

## Usage

Requires a running Docker daemon (Docker Desktop or `colima start`).

```bash
# from the repository root
docker compose config      # validate the topology (no daemon required)
docker compose build       # build the api + web images
docker compose up          # run both services
```

- API: http://localhost:8000 (`/health`, `/api/v1/health`, `/docs`)
- Web: http://localhost:3000

## Phase 0 topology

Only `api` and `web` run today — the services that genuinely exist. PostgreSQL,
Redis, and the async worker are documented as future services in `compose.yaml`
but are not enabled, to avoid running unused infrastructure. The topology is
structured so those services drop in without reshaping the existing two.
