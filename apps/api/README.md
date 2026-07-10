# ats-api

The ATS-Ninja-V2 FastAPI backend.

**Phase 0 scope (implemented):** application factory, environment-based
settings, a versioned API prefix, `GET /health` (liveness) and
`GET /api/v1/health` (readiness reporting the engine version), and tests.

**Not yet implemented (future phases):** kit-generation endpoints, authentication,
credits/billing, persistence (SQLAlchemy 2.x + Alembic + PostgreSQL), Redis, and
the async worker. The structure is built to adopt these cleanly. No placeholder
endpoints pretend these exist.

All career business logic lives in `packages/engine` (`ats-engine`); this service
orchestrates it and owns transport/persistence concerns only.

## Run locally

```bash
# from the repo root, in the shared virtualenv
pip install -e "packages/engine[dev]"   # engine first
pip install -e "apps/api[dev]"

uvicorn app.main:app --reload --app-dir apps/api   # http://localhost:8000
```

- Liveness: `GET http://localhost:8000/health`
- Readiness: `GET http://localhost:8000/api/v1/health`
- OpenAPI docs: `http://localhost:8000/docs`

## Quality gates

```bash
pytest apps/api
ruff check apps/api
ruff format --check apps/api
mypy --config-file apps/api/pyproject.toml apps/api/app
```
