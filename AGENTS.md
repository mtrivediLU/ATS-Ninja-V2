# AGENTS.md — Engineering contract for ATS-Ninja-V2

This file is the standing contract for **any** AI coding agent (Claude Code,
Codex, Cursor, or others) and human engineers working in this repository. Read
it before making changes. It encodes decisions that are not obvious from the
code alone and must not be violated without an explicit, documented reason.

---

## 1. Product purpose

ATS-Ninja-V2 is a commercial, AI-powered career SaaS. From a candidate's resume
and a job description it generates a complete **application kit**:

- an ATS-optimized, tailored resume
- a tailored cover letter
- a job-fit analysis
- interview preparation based on the candidate's strengths and gaps
- LinkedIn networking / outreach drafts
- downloadable application artifacts

Today the engine produces the tailored **resume, cover letter, application
answers, job-fit analysis, and interview preparation** and assembles them into a
versioned, truth-grounded **ApplicationKit** (`application-kit/v3`, see
`ats_engine.kit`). LinkedIn outreach remains a future capability and is not yet
implemented. Never describe an unimplemented feature as done.

## 2. The core principle: deterministic-first, truth-grounded generation

This is the product's differentiator and the most important rule in this repo.

- **Deterministic-first.** Python does deterministic work wherever reasonably
  possible: parsing, evidence extraction, requirement normalization, matching,
  scoring, gap classification, validation, claim verification, and caching.
- **LLMs do judgment and prose only.** They provide semantic judgment and
  high-quality wording, nothing more.
- **LLM output is untrusted until validated.** Treat every model response as
  untrusted text. It must pass the deterministic validation gates before it is
  considered deliverable. Re-validate rewritten prose against the candidate's
  evidence and reject anything that introduces an unsupported metric or a tool
  the source did not contain.
- **Detection is not enough — unsupported claims must be *removed*.** As of Phase
  2A the grounded orchestrator (`ats_engine.kit`) runs a truth gate over **every**
  generated artifact (resume summary/bullets, cover letter, *and* answers): each
  candidate-specific claim is extracted, classified against the candidate's
  evidence, and — if unsupported — deterministically excised (or the artifact
  withheld and the kit marked `fatal`). No fabricated employer, title, metric,
  dollar value, team size, unsupported skill/expertise, certification, degree,
  tenure, or management claim may reach the final `ApplicationKit`. Repair is
  removal (never "soften a fabricated fact into acceptance") and is bounded to a
  single deterministic pass. See ADR-0009/0011.
- **Candidate evidence is the single source of truth.** Every candidate-specific
  claim must be backed by evidence from the uploaded resume.
- **Never fabricate candidate claims** to improve ATS alignment. Inventing an
  employer, a metric, a skill, or a title to score better is a product-defining
  failure, not a bug to tolerate.
- **Never silently swallow a validation failure.** Surface it; classify it
  (see `ats_engine.validation.severity`); block delivery when it is truth-critical
  or structural.
- **STAR stories are single-context evidence products.** Never blend employers,
  roles, or education into one event. Never infer a project, action, result,
  metric, client, team size, or leadership from a skill. Mark a STAR candidate
  complete only when all material fields are explicitly evidenced by the same
  source context; an incomplete truthful outline is preferable to fabrication.

## 3. Architecture boundaries

A modular monolith with a separately-executable async worker (added later).
Avoid premature microservices; avoid unnecessary enterprise abstractions.

```
packages/engine   Pure-Python career intelligence engine (ats_engine)
apps/api          FastAPI backend (transport, persistence, orchestration)
apps/web          Next.js App Router frontend (presentation only)
infra             Docker + future deployment assets
docs              Architecture documentation + ADRs
```

### `packages/engine` (`ats-engine`) — owns the domain

Responsibilities: parsing, candidate evidence, JD requirements, normalization,
matching, scoring, gap analysis, truth validation, generation orchestration,
provider abstractions, caching, and typed domain models.

Hard constraints:

- **No dependency on FastAPI, Next.js, Streamlit, or any frontend code.**
- **No LLM-vendor SDK dependency.** Providers are reached through the
  `LLMProvider` interface (`ats_engine.providers`). There must be **zero
  Streamlit imports** anywhere under `packages/engine`.
- Independently usable: importable and runnable from a notebook, a test, the API,
  or a worker, with no web framework present.
- Public surface is `ats_engine` and its documented subpackages. Do not force
  callers to import private modules.

### `apps/api` — owns transport & orchestration

Owns: API contracts, application services, persistence, kit lifecycle, and async
job orchestration. It **orchestrates** the engine; it must not reimplement domain
logic. Future: authentication, credits, billing integration.

Constraints: no FastAPI framework code leaks into the engine; centralized
environment-based settings; versioned API prefix. As of Phase 1 it owns the
async kit lifecycle (persistence + queue + worker) but still has **no** auth,
Stripe, or product frontend flows.

Persistence & queue discipline:

- Persistence is async SQLAlchemy 2.x + Alembic. Use **portable** column types
  (`Uuid`, generic `JSON`) so the same models/migration run on PostgreSQL and on
  the SQLite used by tests. Every schema change ships an Alembic migration.
- Infrastructure sits behind interfaces. The API depends on the `JobQueue`
  interface, never a concrete broker; `CeleryJobQueue` (Celery over Redis) is
  production, `InlineJobQueue` is for tests. Dispatch is by task name — request
  handlers never import the worker task implementation. Task payloads carry only
  the kit id; the worker loads all state from PostgreSQL (never the Celery result
  backend, which is disabled).
- The kit service is the single code path the API and the worker share; the
  worker adds no business logic. It calls the engine's `generate_application_kit`
  orchestrator and persists the versioned ApplicationKit through the engine's
  serialization boundary (`application_kit_to_dict`) — the grounding/truth logic
  and prompts live in `ats_engine`, never in `apps/api` or the Celery task. An
  engine failure marks the kit `failed` — it must never crash the worker. The
  persisted result is normalized on read, so a kit stored under the older Phase 1
  shape is adapted, not crashed (ADR-0012).
- Tests are hermetic: SQLite + inline queue + `engine_use_llm=False`. No test may
  require a running PostgreSQL, Redis, or model server.

### `apps/web` — owns presentation only

Next.js (App Router) + TypeScript + Tailwind. The frontend must **never** own
resume scoring, gap logic, claim validation, evidence logic, or any other
career-product business rule. Those live in the engine and are reached through
the API.

## 4. LLM provider abstraction

- LLM vendors belong behind interfaces/adapters. The engine depends only on
  `ats_engine.providers.LLMProvider` (a `Protocol` with `identity` and
  `complete`). The bundled `OllamaProvider` talks to a local Ollama server over
  stdlib HTTP — no SDK.
- **Never hardcode a specific provider into core domain models or logic.** Adding
  a hosted provider (OpenAI, Anthropic, Azure, ...) means adding a sibling
  adapter that implements the Protocol; domain code does not change.
- Providers are optional. Every pipeline step must work with `provider=None`
  (deterministic fallback). A missing/unreachable provider is a normal state, not
  an error.

## 5. Testing expectations

- Meaningful tests accompany migrated engine capabilities and new code.
- Preserve behavioral regression coverage for the strategic domain logic
  (evidence matrix, gap ladder, claim validation, deterministic scoring,
  completeness). Do not delete or weaken legitimate tests to make a build green.
- The API health endpoints are tested. New endpoints get tests.
- Run tests deterministically (`use_llm=False` / `provider=None`) so the suite
  never depends on a running model.

## 6. Typing expectations

- Python: strong typing everywhere. `packages/engine` and `apps/api` pass
  `mypy --strict`. Use typed domain models (dataclasses) rather than loose dicts
  where it adds clarity.
- TypeScript: `strict` mode; `tsc --noEmit` must pass.

## 7. Dependency-management expectations

- Python deps live in each package's `pyproject.toml`. Keep the engine's runtime
  dependencies light and portable (low operational cost, minimal vendor lock-in).
  Prefer removing heavy dependencies when a deterministic implementation is
  equivalent (see ADR-0002).
- Node deps live in `apps/web/package.json`; the pnpm workspace lockfile
  (`pnpm-lock.yaml`) is committed. Use the pinned `packageManager` (pnpm).
- Record every dependency in the correct manifest and commit lockfiles.

## 8. Secrets & security rules

- **Never hardcode secrets.** Configuration comes from the environment via typed
  settings (`ats_engine.config.EngineSettings`, `app.config.Settings`).
- Never commit real API keys, credentials, `.env` files, private resumes /
  candidate personal documents, generated application kits, or local caches.
  `.env.example` files document the shape only.
- Avoid global mutable state and god modules.

## 9. Migration discipline (from legacy `ATS-Ninja`)

- The legacy repo (`../ATS-Ninja`, a Streamlit app) is **read-only** source
  material. Never modify or commit to it.
- Do not blindly copy it. Preserve valuable **validated domain logic and
  behavior**; replace legacy scaffolding and framework coupling.
- Do not rewrite proven legacy domain logic without a concrete, documented
  reason. Do not migrate Streamlit UI, generated artifacts, private candidate
  data, local caches, `.env` files, or dead code.

## 10. Git & commit expectations

- Work on a branch; do not commit directly to a protected default unless that is
  the established workflow. Do not push unless the environment is explicitly
  configured for a safe automatic push.
- Before committing: review `git status` and the full diff, inspect untracked
  files, and check for secrets, private resume/candidate files, `.env` files,
  generated caches, and accidental large artifacts.
- Use clear, conventional commit messages (`feat:`, `fix:`, `docs:`, `chore:`,
  `refactor:`, `test:`).

## 11. Quality gates (run before declaring work done)

From the repository root, in the shared Python virtualenv and the pnpm workspace:

```bash
# Engine
pytest packages/engine
ruff check packages/engine && ruff format --check packages/engine
mypy --config-file packages/engine/pyproject.toml packages/engine/src
# Zero Streamlit imports under the engine (must print nothing):
! grep -rn "streamlit" packages/engine/src

# API
pytest apps/api
ruff check apps/api && ruff format --check apps/api
mypy --config-file apps/api/pyproject.toml apps/api/app

# Web
pnpm --filter @ats-ninja/web lint
pnpm --filter @ats-ninja/web typecheck
pnpm --filter @ats-ninja/web build

# Containers (requires a running Docker daemon)
docker compose config
```

**Canonical mypy commands.** The type-check gate is `mypy --config-file
<package>/pyproject.toml <package>/src` (or, equivalently, running `mypy` from
inside the package directory). This form is canonical because each package's
`[tool.mypy]` config holds the **scoped** `ignore_missing_imports` overrides for
the few third-party libraries that ship no type stubs (`diskcache` and
`pdfplumber` for the engine; `celery` for the API). First-party ATS-Ninja code is
always under full `strict = true`.

Do **not** rely on a bare `mypy --strict packages/engine/src` run from the
repository root: without `--config-file` it does not discover the per-package
config, so it reports false `import-untyped` errors for those stub-less
third-party libraries. That is a working-directory artifact, not a first-party
typing failure — always use the config-file form above.

Do not mark a task complete while a required gate is failing. If a genuine
pre-existing behavior cannot be migrated safely, document it accurately instead
of hiding the failure.
