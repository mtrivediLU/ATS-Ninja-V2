# ATS-Ninja-V2 — Architecture

## Structured candidate documents and browser print

Resume and Cover Letter artifacts retain their existing plain-text and optional
LaTeX fields and may include structured document data assembled from the
already-grounded engine plans. No browser-side candidate-fact inference is used.
Older persisted Kits fall back to conservative text parsing and then verbatim
display. The web template view has one dedicated, flowing print root for the
selected document; controls, trust UI, and fallback notices are deliberately
excluded from Print / Save as PDF. No external PDF service is used.

Status: **Phase 2 backend complete; Design Phase K1 unified-results private-local dogfooding polish**. This
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

### Frontend workflows (Design Phase K1)

K1 keeps the D2 provider, local-edit, evidence, and full-artifact workspaces,
but makes `/kits/[kitId]` the completed-Kit workspace. It derives six artifact
summaries, trust counts, and warning state from the one `KitProvider` result;
there are no per-card fetches, no additional poller, no browser evidence
classification, and no browser ATS/fit calculation. Common actions expand in
place, while the prior artifact routes remain advanced/deep-link paths.

The shared Quick PDF control still invokes the existing PDF export endpoint;
template selection is presentation-only React session state shared by unified
and advanced document views. Candidate content is not added to browser storage
or URLs. K1 is frontend composition only: no API contract, engine, persistence,
queue, database, or evidence-rule change.

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

#### Multi-engine PDF extraction and ATS/document-quality audit (fixed)

**Symptom.** Real-world resumes exported real PDF-extraction defects into the
generated Resume: corrupted contact fields (a decorative icon glyph glued
directly onto the following email/phone/URL with no space), a word broken by
a genuine PDF line-wrap hyphen surviving unrepaired ("Hi- bernate" instead of
"Hibernate"), a bullet's wrapped tail fragment overwriting the *next*
employer's company name, an inflated years-of-experience figure, a cliché
softener replacing "end-to-end" with "full" (producing a visible
"full, full-stack" duplication when the source already said "full-stack"
nearby), and a JD-domain heuristic that misclassified almost any posting as
"AI" (a bare substring match on "ai" hits "maintain", "training", "certain").

**Root causes (verified against the real reference PDF's safe structural
statistics, never its raw content in this repository):**

1. `document_extraction.py`'s single-engine `pypdf` extraction glues certain
   decorative contact-icon glyphs directly onto the following text with no
   space, and `pypdf.extract_text()`'s line-break placement, when combined
   with the heuristic resume parser's own wrapped-continuation logic, can
   silently drop a hyphen-broken word or let a bullet's wrapped tail leak into
   the next employer's header. The pre-existing `pdfplumber`-based extractor
   (`parsing/pdf.py`, used elsewhere) and Microsoft's `PyMuPDF` library both
   handle these documents markedly better.
2. `ats_engine.generation.planning._career_years` computed elapsed years from
   bare calendar-year integers, so a start month later in the year than the
   end month (e.g. "Nov 2017" to "Apr 2026") rounded up to a full extra year.
3. `ats_engine.validation.repair.soften_banned_style` (and the matching
   `validate_style` ban list) treated "end-to-end" as a cliché to rewrite as
   "full" — a plain, factual technical descriptor, not filler.
4. `ats_engine.parsing.job_description._extract_domain` used a bare substring
   test instead of a word-boundary match.
5. `COMMON_TECH_TERMS` (the JD keyword allowlist) was built from
   BI/data-engineering postings and had no Power-Platform-era vocabulary
   (Power Apps, Power Automate, Power Pages, Dataverse, SharePoint, Azure
   Function Apps, PCF, etc.), so JD parsing under-detected requirements for
   that category of role entirely, and the resulting empty keyword list
   triggered a content-free "core tools and day-to-day delivery" fallback
   summary sentence.
6. Nothing in the pipeline ever stated the target job title truthfully; the
   resume header is deliberately built only from the candidate's own role
   identity (correct, to avoid impersonating a title never held), but no
   *separate*, clearly-framed "targeting" line existed to name the target
   role safely — matching the JobScan-style "job title not found" finding.

**Fix:**

- `ats_engine.parsing.extraction_quality` (new): deterministic, **content-
  agnostic** structural scoring — replacement/private-use/control character
  counts, a glued-word heuristic (`usingPostgreSQL`-style missing-space
  detection), a glued-bullet-marker heuristic, and a glued-contact-prefix
  heuristic (an email/URL match whose preceding character isn't whitespace or
  a normal separator). Never scores by candidate-content relevance.
- `document_extraction._extract_pdf_multi_engine`: runs `pypdf` (mandatory —
  it also owns encryption/page-count/page-limit validation), `PyMuPDF`, and
  `pdfplumber` as extraction candidates, applies a shared line-break-hyphen
  repair to every candidate, scores them, and selects the best. Returns the
  selected engine name and a `manual_review_recommended` flag (surfaced as an
  existing `warnings` entry the upload UI already renders — no new UI
  component was needed). Verified against the real reference PDF: the old
  single-engine path corrupted the candidate's email/website with a glued
  icon-glyph prefix; every multi-engine candidate produces the correct value.
- `_repair_line_break_hyphens`: joins a word only when the hyphen is
  immediately followed by a literal line break — the unambiguous PDF-native
  signal for a word-wrap break — so a legitimate hyphenated compound used
  mid-line (`well-known`, `end-to-end`, `real-time`, `multi-language`) is
  never touched (no literal newline sits between the hyphen and the next
  letter in that case).
- `ats_engine.parsing.contact_integrity` (new): syntax-only validation of the
  resolved email/phone/LinkedIn/website — never rewrites or guesses a
  replacement. Wired into `validate_pipeline_result` under a `"contact:"`
  prefix, which is **not** in `severity.FATAL_MARKERS`, so a malformed
  contact field is a visible trust-summary warning, never a withheld
  artifact.
- `_career_years`: now month-aware (`(end_year*12+end_month) -
  (start_year*12+start_month)) // 12`) when a month is present anywhere in
  the source dates, falling back to plain year subtraction only when no month
  is available at all. Still a total career span (earliest start to latest
  end/now), so concurrent or overlapping roles are never double-counted.
- Removed `"end-to-end"` from both the style-validator ban list and the
  cliché-softener replacement table (`repair.py`) — narrowly scoped, and
  unrelated to any truth-grounding/claim-validation logic.
- `_extract_domain`: word-boundary (`\b...\b`) matching instead of a bare
  substring test.
- `COMMON_TECH_TERMS` gained a Power-Platform/`.NET`-adjacent vocabulary
  block (JD-side keyword *detection* only — this never adds candidate
  evidence), and JD keyword selection now prioritizes terms that literally
  appear in the required-qualifications text before falling back to
  frequency-ranked generic tokens, with the cap raised from 18 to 30 so a
  long, specific requirement list no longer truncates a short critical
  acronym like "C#" in favor of longer generic phrases.
- `_fallback_summary` and the LLM summary prompt both gained a truthful,
  clearly-separated "Targeting {exact JD title} opportunities." clause
  (only emitted when a real target title was parsed, never phrased as a held
  position), and the no-keywords fallback no longer emits "core tools and
  day-to-day delivery" placeholder text.
- `ats_engine.evidence.quality_report` (new, `AtsQualityReport`): an
  **internal-only** diagnostic (`PipelineResult.metadata["ats_quality_report"]`,
  not part of the `ApplicationKit` contract) — required/preferred coverage
  percentages computed only from tier-A/B ("proven") evidence, exact
  target-title presence, section presence, contact integrity, measurable-
  result count, word count, and unsupported/adjacency/working-knowledge
  counts. Not a single confidence score, and never counts an unsupported
  keyword as coverage.

**What did not change:** the evidence gap ladder (proven / adjacency /
working-knowledge / missing) and its placement rules, `validate_claims`,
`validate_completeness`'s thresholds, or the target-role/candidate-identity
separation (the target title is only ever emitted in an explicit "Targeting…"
clause, never as the candidate's own headline or an experience-section
title). A term with zero real evidence remains a genuine gap; the new JD
vocabulary only changes what the JD parser can *detect a requirement for*, not
what the candidate is credited with.

**Verified live** (Docker, deterministic mode, using the real reference
resume against a synthetic Power-Platform-style job description, never
committed): selected extraction engine reported per request; the exported
Classic and Modern PDFs both render 3 pages with no blank pages, no
replacement/private-use characters, a single correctly-placed header and
contact block, the correct employer name in every entry, "8+ years" (not the
previously inflated "9+ years"), a truthful "Targeting Developer, Power
Platform opportunities" clause, and no fabricated C#/.NET/SharePoint
evidence for a candidate whose resume does not support them.

**Known limitation:** the evidence matrix can occasionally surface the same
underlying tool through two differently-worded JD keywords (e.g. a direct
"Power Automate" match alongside an adjacency phrase that also names
"Power Automate" in its own parenthetical) — both mentions are individually
truthful, but the summary/headline can read as slightly repetitive. This is a
pre-existing evidence-matrix characteristic, not introduced here, and fixing
it well requires recognizing that two keywords resolve to the same
`real_evidence` tool — left for a follow-up rather than risked in this fix.

#### Grounded ATS tailoring, typed requirement categories, and direct PDF download (fixed/added)

Extends the multi-engine extraction/ATS-quality audit above with deeper JD
segmentation, a typed requirement-category model, evidence-driven skill-group
ordering, ATS-quality-report warnings, and — the new capability — a direct,
selectable-text PDF download that bypasses the browser's print dialog
entirely.

**JD segmentation (`parsing/job_description.py`).** Enterprise/government
postings routinely bury the title behind a metadata-label preamble
(`Requisition Number:`, `Position Type:`), phrase the mandatory-qualifications
heading as an instruction ("What you need to succeed" / "In addition, you
have:") rather than the word "required," and use a hyphenated "Nice-to-have"
heading that a plain `"nice to have" in text` substring check never matches.
Three concrete bugs here were found and fixed:

- Section-heading detection matched a heading word anywhere in a line
  (`heading in lowered`), so a responsibility bullet that merely mentions
  "...to meet business requirements" mid-sentence was mistaken for a
  "Requirements:" heading and silently pulled every later responsibility
  bullet into the required-qualifications list. Detection is now
  prefix-anchored (`line.startswith(heading)`), matching how a real heading
  is actually written.
- Title extraction only scanned the first 8 lines, so a long D&I/metadata
  preamble pushed the real title heading out of range; the scan window is
  now 40 lines and skips `Label:  Value` metadata lines outright.
- Company extraction's weak "first plausible short line" fallback is now
  preceded by a generic, line-scoped repeated-proper-noun detector (a real
  employer name is mentioned repeatedly through a posting; a one-off section
  heading is not) — this correctly resolves postings that never carry an
  explicit "Company:" field.

A new keyword-frequency safeguard strips organizational/D&I/benefits/
recruitment-process lines before the frequency-based keyword fallback runs,
and drops any bare token that is only a fragment of an already-found longer
keyword (so "Power Platform" is not joined by spurious standalone "power"
and "platform" gap entries). `JDProfile` gained five new, deliberately
inert segmentation fields (`education_experience_requirements`,
`security_language_requirements`, `employment_conditions`,
`compensation_benefits`, `organizational_boilerplate`) for transparency —
Resume tailoring itself continues to read only title, responsibilities, and
required/preferred qualifications, which is what keeps a posting's benefits
paragraph from ever influencing keyword matching.

**Responsibilities as a primary tailoring input.** `build_evidence_matrix`
previously matched required/preferred keywords only against the
required/preferred-qualifications bullets. A keyword named only in the
day-to-day responsibilities (e.g. "perform root-cause analysis on issues,"
never restated in the qualifications list) never reached the requirement map
at all. It now does, added as an extra required-tier entry — but only when
that exact keyword is not already claimed by an explicit required or
preferred designation, so a noisy heading-less responsibilities guess can
never re-rank something the posting itself already called out as preferred.

**Typed requirement categories (`evidence/matrix.py`).** `EvidenceItem`
gained a `category` field (`platform`, `programming language`, `framework`,
`integration`, `cloud`, `database`, `web development`, `source control`,
`business analysis`, `operations and support`, `documentation`,
`communication`, `work conditions`, `other`), assigned by
`classify_requirement_category()` via word-boundary keyword-pattern
matching — this is a separate, coarser classification from
`evidence/adjacency.py`'s `TOOL_CATEGORIES` (which groups tools for honest
substitute-tool phrasing), used here only for skills-section grouping and
requirement-map display.

**Evidence-driven skill-group ordering (`generation/planning.py`).**
`_build_skill_groups` previously emitted one flat "Core Skills" bucket. It
now buckets each evidence-backed skill by its JD-derived category and emits
groups in a fixed category-priority order (role-defining categories first,
general engineering categories next), skipping any category with no
evidence for this candidate — never a hardcoded "Power Platform resume"
layout, the same ordering rule applied to whatever categories this JD and
candidate actually produced. Anything not tied to a JD-matched category still
appears, in "Additional Skills"/"Working Knowledge" — no candidate skill is
ever dropped.

**ATS quality report (`evidence/quality_report.py`).** Two additions:
`duplicate_keyword_warnings` flags when one real piece of evidence answers
two or more differently-worded JD keywords (the "Power Automate" answering
both a direct match and an adjacency phrase case noted as a known limitation
above — now surfaced as a warning instead of silently invisible, though the
underlying cosmetic repetition itself is unchanged). `generic_language_warnings`
re-scans the rendered text for the same banned-cliche/generic-filler
vocabulary generation already actively blocks, as an audit-visibility check
rather than a new restriction. A pre-existing bug in `exact_target_title_present`
was also found and fixed: it checked only the headline and work-mode line,
but the "Targeting {title} opportunities" clause lives in the summary — the
report was reporting "title absent" even when the summary said otherwise.

**Direct PDF download.** See [ADR-0018](../adr/0018-local-pdf-rendering.md)
for the architecture (`ats_engine.generation.html_renderer` + WeasyPrint in
`apps/api` only) and [ADR-0004](../adr/0004-defer-binary-pdf-rendering.md)
for why that split preserves the engine's zero-native-dependency property.
`POST /api/v1/document-exports/pdf` renders the persisted, already-validated
Kit result (or a request-scoped local edit, never persisted) to a real,
selectable-text, single-column PDF and returns it with a standardized
`Content-Disposition` filename
(`ApplicantName_JobTitle_CompanyName_<Resume|Cover_Letter>[_Classic|_Modern].pdf`,
`ats_engine.generation.filenames.build_export_filename`). The frontend's
"Download PDF" button (`template-preview.tsx`) calls this directly — no
print dialog — with duplicate-click prevention and success/failure toasts;
Print / Save as PDF, plain-text, and LaTeX export remain available from a
secondary "More export options" menu.

**Two regressions found only by a live, real end-to-end run (not caught by
any existing test) and fixed:**

- `Access-Control-Expose-Headers` did not include `Content-Disposition`.
  `Content-Disposition` is not on the browser's CORS-safelisted
  response-header list, so `fetch()` silently returned `null` for it on the
  frontend even though curl/httpx and every server-side test could always
  see it — the download worked, but every file was named `document.pdf`
  until this was added to the API's CORS middleware.
- The JobFit/InterviewPrep/LinkedInOutreach truth-grounding validators
  (`job_fit/validation.py`, `interview_prep/validation.py`,
  `linkedin_outreach/validation.py`) each had two bugs in their
  narrative-vs-requirement clause matching, invisible until a real JD
  produced the exact keyword shapes that trigger them: (1) `_contexts()`
  split narrative text on every literal `.`, so a keyword spelled with an
  internal period (`.NET Framework`) self-fragmented, stripping the leading
  `.` the match required and causing an honest "acknowledge this gap"
  sentence to read as if the gap were never mentioned at all; (2) the
  strength-word lexicon includes the bare word "experience," so a gap
  literally named "user experience" self-triggered (and, because several
  gaps share one "Genuine gaps: X, Y, Z." sentence, cross-contaminated its
  neighbors in the same list too) a false "genuine gap presented as a
  strength" rejection — withholding JobFit and InterviewPrep entirely for a
  real, honestly-generated, deterministic narrative that never overclaimed
  anything. Fixed by only splitting on a terminator followed by whitespace
  (a real sentence boundary) and by scrubbing every listed requirement's own
  name out of a shared clause before scanning it for strength language.

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

### ApplicationKit v5: match report + change ledger (completed)

ApplicationKit v5 (`schema application-kit/v5`,
`orchestration grounded-orchestration/v5`) adds two capabilities without
weakening any grounding policy. Older kits (v4 and earlier) remain readable and
are never rewritten in place; regeneration creates a new linked v5 kit instead.

**MatchReport** (`ats_engine.scoring.match_report`) computes three deliberately
separate scores after grounding and final rendering: the original-resume keyword
match (submitted resume), the tailored-resume keyword match (final grounded
resume, absent when the resume was not requested or was withheld), and the
evidence-based role alignment (reusing `job_fit.policy.requirement_coverage_score`
so no competing formula exists). The unified keyword vocabulary is built only
from the job description; a keyword earns credit only when it is present in the
measured resume *and* the candidate's parsed evidence supports it at tier A/B/C,
counted once (frequency never helps). It also carries deterministic confidence
(`high`/`medium`/`low`) with reasons, a `FitCategory` (five honest values,
boundary-safe ordering), a constructive style-clean recommendation and kit
summary, and the persisted `AtsQualityReportPayload`. A failure in match-report
computation never fails an otherwise-safe kit (`match_report=None` plus a bounded
warning). Per-stage timings (`StageTimings`, plain integer ms) are persisted for
observability. See [ADR-0019](adr/0019-application-kit-v5-match-report-and-change-ledger.md).

**Change ledger** (`ats_engine.kit.change_ledger`) records every material
tailoring delta as one stable, location-aware `ChangeRecord`, from instrumented
`PlanDecision`s (summary, targeting clause, bullet rewrite, skill surfacing) and
from grounding claim records (each repaired/rejected claim becomes a visible,
irreversible `grounding_removal`). `ats_engine.kit.change_actions` applies safe,
idempotent, LLM-free accept/reject/restore actions against the persisted
structured document, re-renders, re-grounds, re-validates, recomputes the
tailored score/coverage, and increments a revision. Truth-grounding removals can
never be restored. The API adds `POST /kits/{id}/change-actions` (optimistic
concurrency via `expected_revision`, 409 conflict, 422 irreversible), `DELETE
/kits/{id}`, and `POST /kits/{id}/regenerate`; migration 0006 adds the portable
`revision` and `parent_kit_id` columns. See
[ADR-0020](adr/0020-change-action-revision-and-irreversibility-policy.md).

The frontend surfaces three visually and textually distinct scores, the fit
category and confidence, a production change-ledger component with accept/reject/
restore and conflict handling, kit lineage with regenerate/delete, and a static
"How scoring works" page. `interview_probability` is never rendered as a
percentage.

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
| WeasyPrint/ReportLab binary PDF rendering | **Deferred, then partially adopted** | Heavy native deps conflict with engine portability; the LaTeX artifact served as the downloadable output until direct PDF download became a real requirement. WeasyPrint now renders PDFs in `apps/api` only — `packages/engine` still has zero binary dependencies (ADR-0018). |
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
- [ADR-0017](adr/0017-independent-artifact-selection.md) — Persist independent artifact selection (six independently-requestable artifacts).
- [ADR-0018](adr/0018-local-pdf-rendering.md) — Local server-side PDF rendering (WeasyPrint in `apps/api` only) for direct Resume/Cover Letter download.
- [ADR-0019](adr/0019-application-kit-v5-match-report-and-change-ledger.md) — ApplicationKit v5 match report (three honest scores, confidence, fit categories) and change ledger.
- [ADR-0020](adr/0020-change-action-revision-and-irreversibility-policy.md) — Change-action revision, optimistic concurrency, and grounding-removal irreversibility.

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
