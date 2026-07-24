# ATS-Ninja-V2

## K1 unified Application Kit workspace

Completed Kits now open at `/kits/[kitId]` as one scrollable results workspace.
It places one-click Resume and Cover Letter PDF downloads, answer/outreach copy,
Job Fit gaps, interview review, and evidence warnings alongside all six
artifact summaries. Inline expansion avoids route changes for everyday review;
the individual artifact routes are retained as advanced workspaces. This is a
frontend-only composition over the existing Kit result, PDF export endpoint,
trust/evidence records, and lifecycle poller—no backend business rules changed.

A deterministic-first, truth-grounded AI career SaaS. From a candidate's resume
and a job description it generates an application kit that stays honest to what
the candidate has actually done.

Resume and Cover Letter artifacts retain backward-compatible text and LaTeX
fields and can include optional structured presentation data. Classic and
Modern templates change presentation only; browser Print / Save as PDF uses no
external service and intentionally excludes application UI messages.

> **Status: Phase 2 backend complete; Design Phase D2 private-local dogfooding polish.**
> The engine produces a tailored **resume, cover letter, and application answers**
> and now assembles them into a versioned, truth-grounded **ApplicationKit**
> (`application-kit/v5`): every candidate-specific claim in generated prose is
> validated against the candidate's own evidence, and anything unsupported is
> removed (or the artifact withheld) before delivery — with a structured
> claim/evidence trace. **ApplicationKit v5** adds an honest `MatchReport` (three
> separate scores — original-resume keyword match, tailored-resume keyword match,
> and evidence-based role alignment — plus deterministic confidence, five honest
> fit categories, a constructive recommendation, and the internal ATS quality
> report) and a transparent, evidence-linked **change ledger** with safe,
> persisted accept/reject/restore actions (truth-grounding removals are
> permanent). Kits carry a revision counter and regeneration lineage. The async API + Celery/Redis worker persist this contract
> to PostgreSQL. A structured `JobFitArtifact` now adds deterministic requirement
> coverage, fit band, strengths, honest adjacency/working knowledge, and visible
> gaps. A typed `InterviewPrepArtifact` adds evidence-bounded questions, answer
> guides, single-context STAR outlines, study topics, and honest gap handling.
> A typed `LinkedInOutreachArtifact` adds concise recruiter, hiring-manager,
> employee, follow-up, referral, and genuine shared-context drafts with explicit
> candidate/target/recipient/relationship provenance. It generates drafts only;
> sending, LinkedIn access, authentication, and billing remain future work.
> The Next.js frontend now provides the approved responsive **Signal** shell and
> privately usable local workflows: real Kit submission and polling, all six
> ApplicationKit v4 workspaces, trust-first summaries, bounded evidence
> inspection, unvalidated local editing/compare/reset, safe local
> copy/download, a direct locally-rendered Resume/Cover Letter PDF download,
> recovery handling, and server-backed history. Authentication
> and public SaaS concerns remain intentionally absent.
> See [docs/architecture.md](docs/architecture.md).

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
apps/web          Next.js App Router frontend — D2 private-local dogfooding workflows
infra             Dockerfiles + Docker Compose topology
docs              Architecture documentation + ADRs
```

## Prerequisites

- **Python** ≥ 3.11
- **Node.js** ≥ 20 and **pnpm** (via Corepack: `corepack enable && corepack prepare pnpm@9.15.9 --activate`)
- **Docker** with Compose (for the container topology, and the simplest way to get Postgres + Redis)
- **PostgreSQL** and **Redis** for the API/worker (provided by `docker compose up db redis`)
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

### API (FastAPI) + worker

The API and worker need PostgreSQL and Redis. The simplest way to get both is
`docker compose up db redis` (or the full stack below). Then:

```bash
source .venv/bin/activate
export ATS_API_DATABASE_URL="postgresql+asyncpg://ats:ats@localhost:5432/ats_ninja"
export ATS_API_REDIS_URL="redis://localhost:6379"

(cd apps/api && alembic upgrade head)                       # apply migrations
uvicorn app.main:app --reload --app-dir apps/api            # API on :8000
(cd apps/api && celery -A app.tasks worker -l info -Q kits) # Celery worker (separate process)
```

- Liveness: `GET http://localhost:8000/health`
- Readiness (reports engine version): `GET http://localhost:8000/api/v1/health`
- Submit a kit: `POST http://localhost:8000/api/v1/kits` with
  `{"resume_text": "...", "job_description": "...", "requested_mode": "resume and cover letter"}`
- Extract a local resume file: `POST http://localhost:8000/api/v1/resume-extractions`
  as `multipart/form-data` with a `file` field. It accepts PDF, DOCX, and TXT,
  returns editable plain text and safe metadata, and never changes the Kit JSON
  contract.
- Poll a kit: `GET http://localhost:8000/api/v1/kits/{id}`
- OpenAPI docs: `http://localhost:8000/docs`

### Web (Next.js)

```bash
pnpm --filter @ats-ninja/web dev                      # http://localhost:3000
```

### Use the engine directly (no server)

Generate a versioned, truth-grounded ApplicationKit with JobFit, interview preparation, and outreach drafts:

```python
from ats_engine import generate_application_kit

kit = generate_application_kit(
    resume_text=my_resume_text,
    job_description=my_jd_text,
    requested_mode="resume and cover letter",
    use_llm=False,            # fully deterministic path (provider=None)
)
print(kit.schema_version)                 # "application-kit/v5"
print(kit.match_report.original_ats_match.score)   # submitted-resume keyword match
print(kit.match_report.tailored_ats_match.score)   # final grounded-resume keyword match
print(kit.match_report.alignment_score)            # evidence-based role alignment
print(kit.match_report.fit_category)               # strong_fit .. low_alignment
print(kit.match_report.confidence)                 # high | medium | low
print(kit.resume.change_ledger)                    # transparent, reversible tailoring changes
print(kit.job_fit.fit_band)               # deterministic requirement-coverage band
print(kit.job_fit.must_have_gaps)         # honest risks stay visible
print(kit.interview_prep.questions)       # grounded questions + answer guides
print(kit.interview_prep.star_stories)    # complete only when every STAR field is evidenced
print(kit.linkedin_outreach.drafts)       # drafts only; no sending or LinkedIn access
print(kit.resume.text)                    # tailored resume (fabrications removed)
print(kit.validation.fatal)               # False means nothing was withheld
for claim in kit.resume.claims:           # structured truth-grounding trace
    print(claim.claim_type, claim.status, claim.text)
```

The lower-level `run_pipeline` (raw `PipelineResult`) is still available for
engine-only callers who do not need the ApplicationKit contract.

### Grounding + product-intelligence quality-evaluation harness

```bash
python -m ats_engine.eval    # truth-grounding violations + supported-claim preservation
```

### Containers (requires a running Docker daemon)

The Phase 1 topology is `db` (PostgreSQL), `redis`, a one-shot `migrate`, `api`,
`worker`, and `web`:

```bash
docker compose config     # validate topology (no daemon required)
docker compose up --build # db, redis, migrate, api (:8000), worker, web (:3000)
```

`migrate` applies Alembic migrations to Postgres and exits; `api` and `worker`
start once it succeeds.

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

> The canonical type-check gate is the `mypy --config-file …` form shown above.
> Each package's config scopes `ignore_missing_imports` to the few stub-less
> third-party libs (`diskcache`, `pdfplumber`, `celery`) while keeping all
> first-party code `strict`. A bare `mypy --strict packages/engine/src` from the
> repo root bypasses that config and reports false `import-untyped` errors — use
> the config-file form. See AGENTS.md §11.

## Security & privacy

Never commit real API keys, credentials, `.env` files, private resumes /
candidate documents, generated kits, or local caches. `.env.example` files
document configuration shape only. Secrets come from the environment via typed
settings.

### Resume file extraction

The New Kit flow has **Paste text** and **Upload file** modes. Upload accepts a
text-based PDF, DOCX, or TXT file up to 10 MB. The API validates bytes and
container structure, extracts text locally, and returns a preview for the
candidate to edit. The reviewed text—not the original file—is the only value
submitted to `POST /api/v1/kits`.

Uploads are held only for the extraction request: no binary is persisted in
PostgreSQL, Redis, a worker payload, browser storage, or a permanent upload
directory. No external conversion service or OCR is used. Encrypted PDFs are
rejected; image-only/scanned PDFs receive a clear no-readable-text message.
Legacy `.doc` is not supported; save it as DOCX, PDF, or TXT first. Extraction
does only mechanical Unicode/line-ending cleanup and does not tailor, rewrite,
or infer resume claims. One of those mechanical steps restores the space a PDF
bullet glyph often loses against its text (`"•Managed..."` → `"• Managed..."`)
— see [docs/architecture.md](docs/architecture.md#resume-extraction-local-only)
for why that mattered for downstream parsing, not just readability.

PDF extraction runs three engines (`pypdf`, `PyMuPDF`, `pdfplumber`) and
deterministically scores each candidate on structural fidelity — never on
candidate-content relevance — picking the most faithful one; see
[docs/architecture.md](docs/architecture.md#multi-engine-pdf-extraction-and-atsdocument-quality-audit-fixed)
for the extraction-quality scoring, contact-integrity validation, tenure-
calculation, JD-parsing, and ATS-tailoring fixes this made possible.

### Grounded ATS tailoring and direct PDF download

Job-description parsing separates real requirements/responsibilities from
organizational boilerplate (D&I, benefits, recruitment-process copy), and a
typed requirement category (platform, programming language, cloud, database,
web development, source control, business analysis, and more) drives an
evidence-ordered Technical Skills layout — never a hardcoded template, always
derived from what the candidate's own evidence and the JD actually produced.
The Resume and Cover Letter templates now support a direct **Download PDF**
button — a real, request-scoped, locally-rendered binary PDF with a
standardized `ApplicantName_JobTitle_CompanyName_<Artifact>[_Template].pdf`
filename, no browser print dialog, no external service. See
[docs/architecture.md](docs/architecture.md#grounded-ats-tailoring-typed-requirement-categories-and-direct-pdf-download-fixedadded)
and [ADR-0018](docs/adr/0018-local-pdf-rendering.md).

## ApplicationKit v5: honest scoring and the change ledger

ApplicationKit v5 makes scoring honest and tailoring transparent. The
`MatchReport` reports three deliberately separate scores — the **original**
resume keyword match, the **tailored** resume keyword match, and the
**evidence-based role alignment** — plus deterministic `high`/`medium`/`low`
confidence with reasons, one of five honest fit categories
(`strong_fit` … `low_alignment`), a constructive style-clean recommendation, and
the persisted ATS quality report. A keyword only earns credit when the
candidate's own parsed evidence supports it, so pasting the job description into
a resume, repeating keywords, or padding prose can never raise a score. Every
figure is a deterministic estimate, never a prediction of an employer's decision;
`interview_probability` is preserved for compatibility but is never rendered as a
percentage.

Each artifact carries a transparent, evidence-linked **change ledger**. Ordinary
tailoring changes (summary, targeting clause, bullet rewrites, cover-letter
paragraphs) can be accepted or rejected through
`POST /api/v1/kits/{id}/change-actions`; the batch is deterministic, LLM-free,
re-grounded, re-validated, and bumps a persisted revision (optimistic concurrency
via `expected_revision`, 409 on conflict). Truth-grounding removals are
permanent and can never be restored. Kits also support
`POST /api/v1/kits/{id}/regenerate` (a new linked kit from the same inputs) and
`DELETE /api/v1/kits/{id}`. A static **How scoring works** page explains all of
this. See [ADR-0019](docs/adr/0019-application-kit-v5-match-report-and-change-ledger.md)
and [ADR-0020](docs/adr/0020-change-action-revision-and-irreversibility-policy.md).

## License

Proprietary. All rights reserved.
