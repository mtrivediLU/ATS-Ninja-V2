# ATS-Ninja-V2 — Architecture

## Structured candidate documents and browser print

Resume and Cover Letter artifacts retain their existing plain-text and optional
LaTeX fields and may include structured document data assembled from the
already-grounded engine plans. No browser-side candidate-fact inference is used.
Older persisted Kits fall back to conservative text parsing and then verbatim
display. The web template view has one dedicated, flowing print root for the
selected document; controls, trust UI, and fallback notices are deliberately
excluded from Print / Save as PDF. No external PDF service is used.

Status: **Phase 2 backend complete; Design Phase D2 private-local dogfooding polish**. This
document distinguishes what is **completed**, what **architecture is
established**, and what is **future** planned work. It never describes
unimplemented functionality as done.

---

## 1. Current system architecture

ATS-Ninja-V2 is a **modular monolith** with a clean domain core and thin
application shells. Three deployable/importable units plus infra and docs:

```
┌───────────────────────────────────────────────────────────────────────┐
│                            apps/web (Next.js)                          │
│  Presentation only. No business logic. Talks to the API over HTTP.     │
└───────────────────────────────▲───────────────────────────────────────┘
                                 │ HTTP
┌───────────────────────────────┴───────────────────────────────────────┐
│                           apps/api (FastAPI)                           │
│  Kit lifecycle endpoints, settings, health. Persistence + job queue.   │
│  Future: auth, billing. Orchestrates the engine; owns no domain logic. │
└───┬──────────────────────▲──────────────────────────▲─────────────────┘
    │ dispatch (Celery)    │ SQLAlchemy (async)        │ in-process import
    ▼                      ▼                           │  (ats_engine)
┌─────────────┐   ┌──────────────────┐                 │
│   Redis     │   │   PostgreSQL     │                 │
│Celery broker│   │  kits table      │                 │
└──────┬──────┘   └────────▲─────────┘                 │
       │ consume           │ persist result            │
┌──────┴────────────────────┴──────┐                   │
│    apps/api Celery worker         │───────────────────┘
│  generate_application_kit per kit │  in-process import (ats_engine)
└───────────────────────────────────┘
                                 │
┌────────────────────────────────┴──────────────────────────────────────┐
│                      packages/engine (ats_engine)                      │
│  Pure-Python domain core. Deterministic-first, truth-grounded.         │
│  parsing · evidence · scoring · validation · caching · providers ·     │
│  generation · models · config                                          │
│  No web framework. No LLM-vendor SDK. Zero Streamlit imports.          │
└────────────────────────────────────────────────────────────────────────┘
```

### Frontend workflows (Design Phase D2)

`apps/web` preserves the approved Signal application foundation: centralized
semantic tokens, responsive desktop/sidebar, tablet/rail, mobile/drawer and
bottom-navigation layouts, route-based artifact tabs, a responsive evidence
panel, and accessible UI primitives. D1 connected that foundation to the real
Kit lifecycle through a small typed fetch client, cancellable polling, dynamic
Kit routes, six ApplicationKit v4 workspaces, real evidence traces, and
server-backed paginated history. D2 adds a route-backed trust/content view,
artifact trust summaries, a unified state presentation vocabulary, trace filters
and keyboard navigation, local edit/dirty/compare/reset/discard flows, copy and
safe downloads, history active filters/load-more, recovery copy, Job Fit gap
emphasis, Interview focus mode, and Outreach per-draft local editing.

All D2 summaries are presentation aggregates of `ClaimResponse` and
`ArtifactValidationResponse`; they do not calculate grounding, scores, fit bands,
STAR completeness, relationship validity, or a confidence/readiness score.
Evidence excerpts remain bounded server values. Because the contract carries no
claim character offsets, the frontend renders explicit trace markers below
content rather than inferring claim locations with browser text matching.

Manual edits remain React-only and are never persisted, sent to the API, stored
in browser storage, or called revalidated. Reload restores server-generated
content. The D2 development-only `/states/d2` route isolates typed unavailable,
partial, old-format, and malformed-response fixtures from real Kit history.

Primary artifact selection is persisted as three explicit booleans while
`requested_mode` remains backward-compatible (ADR-0017). Local document edits
are deliberately unsaved and marked as not revalidated because no edit/ground
endpoint exists. Artifact regeneration, authentication, billing, and public
hosting remain later or out-of-scope work. D2 does not change the API, engine,
persistence authority, or queue payloads.

### Resume extraction (local-only)

`POST /api/v1/resume-extractions` is a separate multipart endpoint for PDF,
DOCX, and TXT resumes. Its parser implementation lives in the engine parsing
boundary; the API reads a bounded request, maps only client-safe failures, and
closes the transient multipart upload. The response contains normalized text and
safe metadata only. It deliberately does not persist a binary, use a permanent
upload directory, put document data into a URL, or pass bytes to Redis/Celery.

The frontend presents the returned text for explicit editing and submits that
reviewed string to the unchanged `POST /api/v1/kits` JSON contract. PDF parsing
is text-only (no OCR); encrypted or image-only PDFs are rejected. DOCX parsing
validates its ZIP package against traversal and decompression limits and ignores
macros, embedded objects, external links, and metadata. Legacy `.doc` is not
supported.

#### PDF-upload false Resume withholding (fixed)

**Symptom.** A completed Kit with a real, valid uploaded-PDF resume had its
Resume artifact withheld with a generic message, and the header showed "Target
company unavailable" even though the job description clearly named a company.

**Root cause (two independent, stacking defects, neither introduced by nor
unique to the PDF path, but both first exposed by it):**

1. `pypdf`'s `extract_text()` frequently places a bullet glyph directly against
   its text with no literal space codepoint (`"•Managed cloud..."`) — the
   visual gap in the source PDF is glyph positioning, not a space character.
   The heuristic bullet detector (`ats_engine.parsing.resume._is_bullet`)
   required a trailing space (`\s+`), so these lines were read as plain header
   text instead of being attached to their employer. Verified against real
   sample PDFs: `pypdf`-extracted bullets matched the old regex 0/19 times;
   the same PDFs run through the pre-existing `pdfplumber`-based extractor
   (`ats_engine.parsing.pdf`) matched 19/19 — confirming the defect was
   specific to the new extraction path, not the underlying documents.
2. `ats_engine.generation.planning._select_experience` silently dropped any
   experience entry that ended up with zero bullets, while
   `ats_engine.validation.completeness.validate_completeness` still counted
   that entry against the source profile. An employer that lost its bullets to
   defect (1) — or one that is genuinely bulletless in the candidate's own
   resume (a common convention for brief/early-career roles) — vanished from
   the rendered Resume while the completeness check still expected it,
   producing a fatal `"completeness: resume has N experience entries, source
   has M"` error and a correctly-conservative (but avoidable) withholding.

Separately, the "Target company unavailable" header was a **display bug**, not
a data problem: `apps/web/lib/product.ts`'s `kitTarget()` read target
company/role only from the (optional) LinkedIn Outreach artifact. Any Kit that
didn't request LinkedIn Outreach showed "unavailable" even when the same
already-extracted value was sitting on the Cover Letter artifact's
`document.recipient_company` / `target_role`.

**Fix (all narrowly scoped, no validation threshold changed):**

- `ats_engine.parsing.resume._is_bullet`: match `\s*` (not `\s+`) after the
  marker, consistent with `_clean_bullet`'s existing stripping regex.
- `ats_engine.parsing.document_extraction.normalize_extracted_text`: insert a
  space after a bullet-like marker glued to a following letter, so the
  reviewed extraction preview also reads correctly.
- `ats_engine.generation.planning._select_experience`: keep an experience
  entry even with zero bullets (header/dates only) instead of dropping it —
  `generate_resume_text` already renders that case correctly, and dropping it
  is exactly the kind of silent content loss `validate_completeness` exists to
  catch.
- `apps/web/lib/product.ts` `kitTarget()`: fall back to the Cover Letter
  document's `recipient_company` / `target_role` before declaring "target
  company unavailable"; still deterministic, still never guesses from prose.
- `apps/web/lib/product.ts` `safeWithheldReason()` + `artifact-route.tsx`:
  the withheld-state reason now reads `validation.errors` (where the fatal
  reason actually lives — the UI had been reading the near-always-empty
  `validation.warnings`) and maps recognized categories (`completeness:`,
  unsupported/invented claims, missing identity, structural/LaTeX) to a safe,
  specific, actionable message instead of the generic fallback. Truth-critical
  and structural withholding itself is unchanged; only its explanation
  improved.

**What did not change:** truth-grounding, anti-fabrication, claim validation,
`validate_completeness`'s thresholds, the target-role/candidate-identity
separation, and the no-binary-into-Celery boundary. A resume that is
genuinely incomplete (an employer with bullets in the source that the
*rendered* resume drops) still fails `validate_completeness` and is still
withheld — covered by
`packages/engine/tests/test_completeness_regression.py::test_genuinely_incomplete_resume_is_still_caught_by_completeness_validation`.

**Processing duration.** The long processing time observed on the original
affected Kit (~198s) was a separate, additive factor: local development
defaults to `ATS_API_ENGINE_USE_LLM=true` with an Ollama provider, and one
extraction call hit a transport timeout before a later attempt succeeded —
visible in the worker log as `LLM JSON generation failed on attempt 0` followed
by a `generate_kit[...] succeeded in 200.9s`. This did not cause the
withholding (the same completeness defect reproduces in well under a second in
deterministic mode — `ATS_API_ENGINE_USE_LLM=false`); it just made the failing
Kit slow in addition to being wrong. `apps/api/app/services.py` now logs a
safe `kit id / elapsed ms / llm flag` timing line on every completion and
failure (never resume, job description, or generated content) so a future slow
Kit is diagnosable from logs alone.

**Troubleshooting a withheld Resume:**

- Check the Kit's safe validation reason first: the UI now shows a specific
  category (structural incompleteness, unsupported claims, missing identity)
  instead of a generic message.
- For a structural-incompleteness reason, re-open the "Extracted resume text"
  preview (upload flow) or the pasted text and confirm every employer that has
  detail bullets in the original document still has them after extraction —
  look for a bullet-marker line that reads as plain text.
- `docker compose logs worker --since=30m | grep '<kit-id>'` shows the safe
  `generation completed in Nms (llm=...)` line for that Kit; no candidate
  content is ever logged.
- A Kit generated before this fix keeps its original (frozen) result — it is
  not automatically regenerated. Create a new Kit with the same input to get
  the corrected behavior.

### Async kit lifecycle (Phase 1, completed)

The API and a separately-runnable worker share one image and the same kit
service, but run as independent processes so each scales on its own:

```
POST /api/v1/kits   → persist Kit(status=pending) in Postgres → dispatch via Celery/Redis → 202
worker (Celery)     → dequeue → status=processing → generate_application_kit (in a thread)
                    → persist KitResult + status=completed|failed
GET  /api/v1/kits/{id} → current status; full result once completed
```

- **Persistence**: async SQLAlchemy 2.x (`asyncpg`) with an Alembic migration.
  Column types (`Uuid`, generic `JSON`) are portable, so the same models and
  migration run on PostgreSQL (prod) and SQLite (tests).
- **Queue**: the API depends only on a `JobQueue` interface. `CeleryJobQueue`
  (Celery over Redis) is used in production and dispatches **by task name** —
  only the kit id crosses the broker; `InlineJobQueue` runs jobs in-process for
  tests and single-process usage. Infrastructure stays behind an interface,
  mirroring the engine's provider abstraction. PostgreSQL (not the Celery result
  backend, which is disabled) is the single source of truth for kit state.
- **Worker**: `celery -A app.tasks worker`. The synchronous, potentially
  CPU/IO-bound `generate_application_kit` runs via `asyncio.to_thread` on a per-task event
  loop so it never blocks. Delivery is at-least-once (`acks_late`,
  `reject_on_worker_lost`, prefetch 1); a terminal/duplicate guard in
  `process_kit` protects finished kits, and only classified transient
  infrastructure failures are retried (bounded, backing off). An engine crash
  fails the kit, not the worker. See [ADR-0006](adr/0006-replace-arq-with-celery.md).
- **Truth-grounding is preserved**: the engine's validation gates run inside
  `run_pipeline`. As of Phase 2A the worker calls `generate_application_kit`
  (which wraps `run_pipeline` with the grounding gate) and persists a versioned
  ApplicationKit. No auth or billing in this phase; resume extraction is a
  request-local preflight and never enters the worker payload.

### ApplicationKit + grounded generation (Phase 2A, completed)

Phase 2A makes truth-grounding an explicit, structured **product contract** and
guarantees that no fabricated candidate-specific claim reaches the final output.

**Generation audit (why this phase exists).** An audit of the real pipeline found
that generation-time checks rejected *some* unsupported rewrites (metrics, known
skills) in favor of deterministic fallbacks, but: (1) application answers received
almost no claim validation; (2) cover-letter and summary prose had no
employer/title/novel-skill/certification/degree checks; and (3) when the final
validators *did* detect a fabrication, the content was flagged as a string but
**never removed** — and the kit still shipped `completed`. Detection was not
absence. See [ADR-0009](adr/0009-validation-wrapped-generation.md).

**The grounded orchestrator** (`ats_engine.kit`, called by the worker via the kit
service) composes the proven engine and adds a truth gate:

```
generate_application_kit(resume, jd, mode, provider?)
  → resolve providers (primary / optional fallback / deterministic)   [ADR-0010]
  → run_pipeline (parse → evidence → plan → AI prose → validate)
  → build deterministic evidence view of the candidate
  → GROUND every artifact's prose (summary, bullets, cover letter, answers):
       extract structured claims → classify support against evidence
         supported  → keep
         unsupported→ remove (repair) ; if not removable → reject/withhold  [ADR-0011]
  → RE-RENDER text + LaTeX from the sanitized plans (clean by construction)
  → re-run the engine's artifact validators
  → assemble ApplicationKit (schema application-kit/v4) with a full claim trace
```

- **Versioned contract** ([ADR-0007](adr/0007-application-kit-contract.md)):
  `ApplicationKit` (schema `application-kit/v4`) with typed `ResumeArtifact` /
  `CoverLetterArtifact` / `AnswerArtifact`, a `ValidationSummary`, and
  persistence-safe `GenerationMetadata`. It models only today's real artifacts.
- **Claim/evidence trace** ([ADR-0008](adr/0008-claim-evidence-traceability.md)):
  each candidate-specific claim becomes a `ClaimRecord`
  (`supported`/`repaired`/`rejected`) with bounded `EvidenceRef`s, so the kit
  answers *"why was ATS-Ninja allowed to say this about the candidate?"*
- **Removal, not just detection**
  ([ADR-0011](adr/0011-repair-vs-rejection-policy.md)): unsupported claims are
  deterministically excised (sentence for prose, span for bullets) in a single
  bounded pass; an artifact that cannot be cleaned is withheld and the kit is
  marked `fatal`.
- **All artifacts**: the gate runs over the resume, cover letter, **and** answers
  — cover letters and answers can hallucinate candidate facts too.
- **Persistence**: no database migration is required — the result stays a JSON
  column; only its shape changes. A completed kit written under the Phase 1 shape
  is adapted at the serialization boundary, not crashed
  ([ADR-0012](adr/0012-result-schema-evolution.md)).
- **Proof**: an adversarial anti-fabrication suite injects fabricated employers,
  titles, metrics, dollar values, team sizes, skills, certifications, degrees,
  tenures, and management claims and asserts each is **absent from the final
  ApplicationKit**; a quality-evaluation harness (`python -m ats_engine.eval`)
  reports truth-grounding violations and supported-claim preservation across
  synthetic cases.

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
| `generation` | Plans + resume/cover-letter/answer generation, LaTeX rendering, pipeline, evidence-bound prompt contract | Completed |
| `kit` | Versioned `ApplicationKit` contract, JSON serialization boundary (+ legacy adapter), grounding gate, provider routing, orchestrator | Completed (Phase 2A) |
| `eval` | Phase 2A quality-evaluation harness (synthetic cases; `python -m ats_engine.eval`) | Completed (Phase 2A) |
| `job_fit` | Deterministic requirement assessment, fit policy, bounded narrative, consistency validation | Completed (Phase 2B1) |
| `interview_prep` | Deterministic questions/answer guides, single-context STAR policy, honest gaps, bounded narrative validation | Completed (Phase 2B2) |
| `linkedin_outreach` | Deterministic concise drafts, evidence-class separation, relationship/action grounding, length validation | Completed (Phase 2B3) |

### Grounded JobFitArtifact (Phase 2B1, completed)

ApplicationKit v2 adds an optional typed `job_fit` artifact, generated by
default and disabled with the persisted `include_job_fit=false` request option.
Its authoritative structure comes from the existing evidence matrix and gap
ladder. A reproducible requirement-coverage index weights required requirements
twice as heavily as preferred ones and assigns fixed evidence credit (A=100,
B=80, adjacency=55, working knowledge=35, missing=0). Central thresholds map
coverage to low (<50), partial (50–<70), competitive (70–<85), and strong (≥85).
This index is not a probability; the existing calibrated interview probability
and literal ATS keyword score remain separate fields.

Provider prose receives only a bounded structured brief and cannot change any
score or classification. Candidate-claim grounding runs first, then JobFit
consistency validation checks score/band, requirement dispositions, target
company/title history, and must-have visibility. One bounded repair replaces a
contradictory narrative with the deterministic narrative and records the
violation. V1 and Phase 1 JSON results remain readable; unknown schemas remain
unknown. Migration 0002 persists only the request option—the artifact remains in
the existing PostgreSQL JSON result column. See [ADR-0014](adr/0014-application-kit-v2-job-fit.md).

### Grounded InterviewPrepArtifact (Phase 2B2, completed)

ApplicationKit v3 adds optional typed `interview_prep`, default-on through the
persisted `include_interview_prep=true` request option. It is independently
selectable from JobFit: when interview preparation is requested without a
persisted JobFitArtifact, the engine calculates one internal deterministic fit
assessment and does not duplicate or expose it.

Questions, answer guides, focus areas, study topics, gap handling, positioning,
and interviewer questions come from the candidate Profile, JDProfile, evidence
matrix, and authoritative JobFit classifications. A provider may rewrite only a
bounded strategy summary. Candidate grounding, interview consistency, STAR
integrity, and gap checks run before a single deterministic fallback pass.

Every STAR candidate is built from exactly one professional or education source
bullet. A story is `complete` only when that bullet explicitly provides
Situation, Task, Action, and Result; otherwise the artifact labels the outline
`incomplete` and names its missing components. Metrics/results remain on the
same bullet, education stays education, and contribution/support wording is not
upgraded to ownership. Migration 0003 stores only the reproducibility option;
v2, v1, and Phase 1 results remain readable while unknown schemas remain
uninterpreted. See [ADR-0015](adr/0015-application-kit-v3-interview-prep.md).

### Grounded LinkedInOutreachArtifact (Phase 2B3, completed)

ApplicationKit v4 adds optional typed `linkedin_outreach`, default-on through
persisted `include_linkedin_outreach=true`. Optional bounded `outreach_context`
stores only explicit recipient, application, referral, or shared-context facts
needed to reproduce drafts. Outreach remains independently selectable; the
engine may calculate internal fit data without persisting JobFit or InterviewPrep.

Drafts distinguish candidate evidence, JD target context, recipient facts, and
relationship/action facts. Exact typed target and personalization values are
validated by their own provenance gates and never promoted to candidate
evidence. Unsupported relationships, application status, recipient/company
facts, links, attachments, classification upgrades, and complete-alignment
claims are repaired to a deterministic fallback or withheld. Central product
limits govern connection notes, direct messages, follow-ups, and referral
requests without claiming they are current LinkedIn platform limits. Providers
may improve only the bounded strategy summary. The product neither accesses
LinkedIn nor sends messages. See
[ADR-0016](adr/0016-application-kit-v4-linkedin-outreach.md).

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
- [ADR-0005](adr/0005-async-kit-lifecycle.md) — Async kit lifecycle: async SQLAlchemy + a Redis-backed worker behind a queue interface (queue/worker impl superseded by ADR-0006).
- [ADR-0006](adr/0006-replace-arq-with-celery.md) — Replace the arq worker with Celery (Redis broker); at-least-once delivery, bounded transient retries, Postgres as source of truth.
- [ADR-0007](adr/0007-application-kit-contract.md) — Versioned ApplicationKit contract with typed artifacts.
- [ADR-0008](adr/0008-claim-evidence-traceability.md) — Claim/evidence traceability model and privacy trade-off.
- [ADR-0009](adr/0009-validation-wrapped-generation.md) — Validation-wrapped generation orchestration (the grounding gate).
- [ADR-0010](adr/0010-provider-routing.md) — Vendor-neutral provider routing (primary / fallback / deterministic).
- [ADR-0011](adr/0011-repair-vs-rejection-policy.md) — Repair-vs-rejection policy for unsupported claims.
- [ADR-0012](adr/0012-result-schema-evolution.md) — Result schema evolution and Phase 1 compatibility (no DB migration).
- [ADR-0013](adr/0013-cache-identity-versioning.md) — Cache identity and contract versioning.
- [ADR-0014](adr/0014-application-kit-v2-job-fit.md) — ApplicationKit v2 and grounded JobFitArtifact.
- [ADR-0015](adr/0015-application-kit-v3-interview-prep.md) — ApplicationKit v3 and grounded InterviewPrepArtifact.
- [ADR-0016](adr/0016-application-kit-v4-linkedin-outreach.md) — ApplicationKit v4 and grounded LinkedInOutreachArtifact.

## 7. Future / planned work (not yet implemented)

- **Engine**: production multi-provider routing/optimization and future product
  intelligence beyond the completed Phase 2 artifacts.
- **API**: authentication, credits, Stripe billing; PDF-upload ingestion;
  richer kit querying/filtering and result pagination. (Kit endpoints,
  async SQLAlchemy + Alembic + PostgreSQL persistence, Redis, and the async
  worker are **done** — Phase 1.)
- **Web**: authenticated product flows (upload → kit → result) once the API
  exposes them behind auth.
- **Infra**: production deployment manifests; managed Postgres/Redis; worker
  autoscaling. (The local `db`, `redis`, `migrate`, and `worker` services are
  **enabled** in `compose.yaml` — Phase 1.)
