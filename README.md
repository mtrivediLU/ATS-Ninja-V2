# ATS-Ninja-V2

A deterministic-first, truth-grounded AI career SaaS. From a candidate's resume
and a job description it generates an application kit that stays honest to what
the candidate has actually done.

> **Status: Phase 0 (foundation).** The engine produces a tailored **resume,
> cover letter, and application answers** as LaTeX artifacts. Job-fit narrative,
> interview prep, LinkedIn outreach, authentication, billing, and persistence are
> **planned** and not yet implemented. See [docs/architecture.md](docs/architecture.md).

## Why it is different

- **Truth-grounded.** Every candidate claim is backed by evidence from the
  resume. Invented employers, metrics, skills, or titles are blocked.
- **Deterministic-first.** Parsing, evidence extraction, matching, scoring, gap
  classification, validation, and caching are deterministic. The LLM only writes
  prose, and its output is validated before it is trusted.
- **Portable & low-cost.** The engine has no web-framework or LLM-vendor SDK
  dependency and runs fully without an LLM.

Read [AGENTS.md](AGENTS.md) — the standing engineering contract — before contributing.

## Repository layout

```
packages/engine   Pure-Python domain engine (ats_engine): parsing, evidence,
                  scoring, validation, caching, providers, generation, models
apps/api          FastAPI backend (Phase 0: health + settings, engine-ready)
apps/web          Next.js App Router frontend (TypeScript + Tailwind) — product shell
infra             Dockerfiles + Docker Compose topology
docs              Architecture documentation + ADRs
```

## Prerequisites

- **Python** ≥ 3.11
- **Node.js** ≥ 20 and **pnpm** (via Corepack: `corepack enable && corepack prepare pnpm@9.15.9 --activate`)
- **Docker** with Compose (optional; only for the container topology)
- **Ollama** (optional; the engine degrades to a deterministic path without it)

## Setup

### Python engine + API (shared virtualenv)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e "packages/engine[dev]"   # install the engine first
pip install -e "apps/api[dev]"
```

### Web

```bash
pnpm install
```

## Run

### API (FastAPI)

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --app-dir apps/api      # http://localhost:8000
```

- Liveness: `GET http://localhost:8000/health`
- Readiness (reports engine version): `GET http://localhost:8000/api/v1/health`
- OpenAPI docs: `http://localhost:8000/docs`

### Web (Next.js)

```bash
pnpm --filter @ats-ninja/web dev                      # http://localhost:3000
```

### Use the engine directly (no server)

```python
from ats_engine import run_pipeline

result = run_pipeline(
    resume_text=my_resume_text,
    job_description=my_jd_text,
    requested_mode="resume and cover letter",
    use_llm=False,            # fully deterministic path
)
print(result.resume_text)
print(result.validation_errors)  # [] means every truth-grounding gate passed
```

### Containers (requires a running Docker daemon)

```bash
docker compose config     # validate topology (no daemon required)
docker compose build      # build api + web images
docker compose up         # api on :8000, web on :3000
```

## Quality gates

```bash
source .venv/bin/activate

# Engine
pytest packages/engine
ruff check packages/engine && ruff format --check packages/engine
mypy --config-file packages/engine/pyproject.toml packages/engine/src

# API
pytest apps/api
ruff check apps/api && ruff format --check apps/api
mypy --config-file apps/api/pyproject.toml apps/api/app

# Web
pnpm --filter @ats-ninja/web lint
pnpm --filter @ats-ninja/web typecheck
pnpm --filter @ats-ninja/web build
```

## Security & privacy

Never commit real API keys, credentials, `.env` files, private resumes /
candidate documents, generated kits, or local caches. `.env.example` files
document configuration shape only. Secrets come from the environment via typed
settings.

## License

Proprietary. All rights reserved.
