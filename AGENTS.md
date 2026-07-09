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

Today (Phase 0) the engine produces the tailored **resume, cover letter, and
application answers** as LaTeX artifacts. Job-fit narrative, interview prep, and
LinkedIn outreach are **future** capabilities and are not yet implemented. Never
describe an unimplemented feature as done.

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
- **Candidate evidence is the single source of truth.** Every candidate-specific
  claim must be backed by evidence from the uploaded resume.
- **Never fabricate candidate claims** to improve ATS alignment. Inventing an
  employer, a metric, a skill, or a title to score better is a product-defining
  failure, not a bug to tolerate.
- **Never silently swallow a validation failure.** Surface it; classify it
  (see `ats_engine.validation.severity`); block delivery when it is truth-critical
  or structural.

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

Eventually owns: API contracts, application services, persistence, kit lifecycle,
authentication, credits, billing integration, and async job orchestration. It
**orchestrates** the engine; it must not reimplement domain logic.

Constraints: no FastAPI framework code leaks into the engine; centralized
environment-based settings; versioned API prefix. In Phase 0 it exposes only
health + settings plumbing — **no** auth, Stripe, fake persistence, or fake kit
endpoints.

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

Do not mark a task complete while a required gate is failing. If a genuine
pre-existing behavior cannot be migrated safely, document it accurately instead
of hiding the failure.
