# ATS-Ninja-V2 — Architecture

Status: **Phase 0 (foundation)**. This document distinguishes what is
**completed**, what **architecture is established**, and what is **future**
planned work. It never describes unimplemented functionality as done.

---

## 1. Current system architecture

ATS-Ninja-V2 is a **modular monolith** with a clean domain core and thin
application shells. Three deployable/importable units plus infra and docs:

```
┌───────────────────────────────────────────────────────────────────────┐
│                            apps/web (Next.js)                          │
│  Presentation only. No business logic. Talks to the API over HTTP.     │
└───────────────────────────────▲───────────────────────────────────────┘
                                 │ HTTP (future: kit endpoints)
┌───────────────────────────────┴───────────────────────────────────────┐
│                           apps/api (FastAPI)                           │
│  Transport, settings, health. Future: persistence, auth, billing,      │
│  kit lifecycle, async job orchestration. Orchestrates the engine.      │
└───────────────────────────────▲───────────────────────────────────────┘
                                 │ in-process import (ats_engine)
┌───────────────────────────────┴───────────────────────────────────────┐
│                      packages/engine (ats_engine)                      │
│  Pure-Python domain core. Deterministic-first, truth-grounded.         │
│  parsing · evidence · scoring · validation · caching · providers ·     │
│  generation · models · config                                          │
│  No web framework. No LLM-vendor SDK. Zero Streamlit imports.          │
└────────────────────────────────────────────────────────────────────────┘
```

### Engine module map (`packages/engine/src/ats_engine`)

| Module | Responsibility | Status |
| --- | --- | --- |
| `models` | Typed domain dataclasses shared across the engine | Completed |
| `config` | `EngineSettings` (env-driven, framework-independent) | Completed |
| `parsing` | PDF text, contacts, resume `Profile`, JD `JDProfile` (heuristic + optional LLM) | Completed |
| `evidence` | Gap ladder (`classify_keyword`), evidence matrix, adjacency clusters, interview probability | Completed |
| `scoring` | Deterministic ATS keyword scoring + before/after coverage analysis | Completed |
| `validation` | Claim, style, output-format, LaTeX, completeness gates; deterministic style repair; severity classification | Completed |
| `caching` | Content-hash cache (disk-backed, degrades to no-op) | Completed |
| `providers` | `LLMProvider` interface + `OllamaProvider` (stdlib HTTP) | Completed |
| `generation` | Plans + resume/cover-letter/answer generation, LaTeX rendering, pipeline | Completed |

### Request/data flow (deterministic pipeline)

```
resume (PDF/text) + job description
        │
        ▼  parsing            → Profile (candidate source of truth) + JDProfile
        ▼  evidence           → evidence matrix (gap ladder per JD keyword)
        ▼  planning           → ResumePlan / CoverLetterPlan / AnswerPlan
        ▼  generation         → resume/cover/answers text + LaTeX artifacts
        ▼  validation gates   → claims, style, latex, output-format, completeness
        ▼  severity           → fatal (block) vs warning (surface)
      PipelineResult (with validation_errors)
```

The LLM (a `provider`) participates only in parsing quality and prose writing.
With `provider=None` the entire pipeline runs deterministically. Provider output
is re-validated against the candidate's evidence; unsupported metrics or newly
introduced tools cause the grounded original to be kept.

## 2. Package / application boundaries

See [AGENTS.md](../AGENTS.md) §3 for the enforced constraints. Summary:

- The engine depends on **nothing** web/LLM-vendor-specific. It is importable and
  runnable standalone.
- The API orchestrates the engine; it never reimplements domain logic.
- The web app is presentation-only; **no** scoring/gap/claim/evidence logic.
- LLM vendors sit behind `LLMProvider`; no provider is hardcoded into domain code.

## 3. Legacy ATS-Ninja audit findings

The previous implementation (`../ATS-Ninja`, read-only) is a Streamlit app with a
genuinely strong deterministic core under `core/`. Key findings:

- **Streamlit coupling in `core/` was minimal** — a single magic string
  (`requested_mode == "streamlit_default"`) in the pipeline. All real Streamlit
  usage (`st.*`, session state, secrets, caching) lived in `app.py`, which is not
  domain logic.
- **The engine works fully without an LLM.** Every generation step has a
  deterministic fallback; the LLM only raises quality. This is the product's
  strongest asset and was preserved exactly.
- **The LLM layer was hardwired to Ollama via LangChain** (`core/llm.py`), a
  vendor + heavy-framework coupling that violates the provider-abstraction rule.
- **Content-hash caching** (`core/llm_cache.py`) used a hardcoded repo-relative
  `.cache/llm` path (a Streamlit-lifecycle assumption).
- **Validation-severity policy** (which errors block delivery) lived in `app.py`
  (`_is_fatal_validation_error`) — that is domain policy, misplaced in the UI.
- **The test suite embedded real candidate PII** (a real person's resume,
  employers, certifications, and absolute local file paths).
- **Dead/superseded code**: `core/resume_generator.py::generate_tailored_resume`
  (an old LangChain `LLMChain` path superseded by the planning engine).
- **Binary PDF rendering** (`core/pdf_generator.py`) pulled heavy native
  dependencies (WeasyPrint/ReportLab) for an output-format concern.

## 4. Migrated capabilities (completed)

Migrated into `ats_engine`, preserving behavior, with strong typing and tests:

- **Parsing**: PDF text extraction with wrapped-line repair; contact/mode parsing;
  resume `Profile` extraction (heuristic + optional LLM with a completeness floor
  and fabricated-employer guards); JD `JDProfile` extraction; line-reference
  grounding helper.
- **Evidence / gap ladder** (strategic): `classify_keyword` →
  proven (A) / medium (B) / honest adjacency / working-knowledge (C) / genuine
  gap (missing); the evidence matrix; candidate-agnostic adjacency clusters;
  calibrated interview probability.
- **Scoring**: deterministic ATS keyword scoring and before/after coverage
  analysis (re-implemented without scikit-learn — see ADR-0002).
- **Validation / truth-grounding** (strategic): claim validator (blocks invented
  employers, unsupported metrics, foreign emails, altered titles, over-claimed
  tools), style validator + deterministic repair, output-format validator, LaTeX
  validator, completeness validator, and severity classification.
- **Caching**: framework-independent content-hash cache, configurable directory.
- **Providers**: `LLMProvider` interface + `OllamaProvider` over stdlib HTTP.
- **Generation**: grounded plan construction, resume/cover-letter/answer
  generation, LaTeX rendering, and the end-to-end pipeline.
- **Tests**: the legacy regression behaviors were preserved with **synthetic,
  non-personal** fixtures (62 engine tests).

## 5. Intentionally rejected / deferred legacy components

| Legacy component | Decision | Reason |
| --- | --- | --- |
| Streamlit UI (`app.py`, session state, `st.*`) | **Rejected** | UI, not domain; replaced by the API + Next.js boundary. |
| LangChain / `langchain-ollama` coupling | **Rejected** | Vendor + heavy-framework lock-in; replaced by the `LLMProvider` adapter over stdlib HTTP (ADR-0003). |
| scikit-learn TF-IDF for keyword extraction | **Rejected** | Degenerate on a single document; replaced by an equivalent dependency-light extractor (ADR-0002). |
| Real candidate PII in tests + hardcoded local paths | **Rejected** | Privacy; replaced with synthetic fixtures. |
| `generate_tailored_resume` (LangChain `LLMChain`) | **Rejected** | Dead/superseded by the planning engine. |
| WeasyPrint/ReportLab binary PDF rendering | **Deferred** | Heavy native deps conflict with portability; the LaTeX artifact already serves as the downloadable output. Revisit when server-side rasterization is a real requirement. |
| Streamlit magic string `streamlit_default` | **Rejected** | Replaced by an explicit `default_mode` parameter. |
| `_is_fatal_validation_error` in the UI | **Migrated (relocated)** | Domain policy moved into `ats_engine.validation.severity`. |

## 6. Major architecture decisions

Recorded as ADRs under [`docs/adr/`](adr/):

- [ADR-0001](adr/0001-monorepo-modular-monolith.md) — Monorepo, modular monolith with a future worker.
- [ADR-0002](adr/0002-deterministic-keyword-extraction.md) — Replace scikit-learn TF-IDF with a dependency-light deterministic extractor.
- [ADR-0003](adr/0003-llm-provider-abstraction.md) — LLM provider abstraction; Ollama over stdlib HTTP; no vendor SDK in the engine.
- [ADR-0004](adr/0004-defer-binary-pdf-rendering.md) — Defer binary PDF rendering; ship LaTeX artifacts.

## 7. Future / planned work (not yet implemented)

- **Engine**: job-fit analysis narrative, interview preparation, LinkedIn
  outreach drafts; a composed `generate_kit` once the underlying capabilities
  exist (no fake facade before then).
- **API**: kit endpoints, SQLAlchemy 2.x + Alembic + PostgreSQL persistence,
  Redis, async worker, authentication, credits, Stripe billing.
- **Web**: authenticated product flows (upload → kit) once the API exposes them.
- **Infra**: enable `db`, `redis`, and `worker` services in `compose.yaml`;
  deployment manifests.
