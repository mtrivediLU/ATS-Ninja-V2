# ADR-0021: Results-first Application Kit page and DOCX export

Status: Accepted
Date: 2026-07-25

## Context

The completed-Kit workspace (ADR-0019/0020, "K1 unified workspace") composed
the whole ApplicationKit onto one page but still read like an internal audit
tool: a large match-insights panel, six always-visible artifact rows, and a
full change ledger all competed for attention above the fold. New-Kit
submission also redirected to `/kits/{id}/resume`, which defaults to the
`TrustSummary` view — a candidate's first look at a finished Kit was an
evidence trace, not their résumé.

The D4/K1 design package specifies a **results-first** hierarchy: a
personalized header, an honest score comparison, one-click downloads, a
compact evidence-backed "keywords added" list, a handful of natural-language
"what matters most" bullets, exactly two fit panels (strengths/gaps), and a
single quiet entry to everything else. Two pieces of that hierarchy needed new
engine output that did not exist: which keywords were genuinely *added* by
tailoring, and a natural-language summary of the job's own priorities. A third
piece — a Word (.docx) download alongside the existing PDF — was designed
around as a "planned backend capability"; this ADR also closes that gap.

## Decision

### The results-first hierarchy replaces the unified workspace's body

`UnifiedKitWorkspace` now renders, in order: `ResultsHeader`,
`ScoreComparison`, `KeywordsAdded`, `JobPriorities`, `FitPanels`, the primary
document downloads (with a PDF/Word format selector), and one
`AdvancedDetails` disclosure. Nothing else renders above the fold. A Kit opened
from History renders this identical page (History already linked to the base
`/kits/{id}` route); the only routing defect was `new-kit-wizard.tsx`
redirecting to `/kits/{id}/resume` after submission, which is now
`/kits/{id}` so a fresh Kit never lands on a Trust Summary.

`AdvancedDetails` consolidates everything the old page always rendered — the
full `MatchInsights` breakdown, `KitTrustStrip`, `KitLineageActions`
(regenerate/revision history), the tailoring change ledgers, and the four
secondary-artifact sections (answers, job-fit, interview prep, LinkedIn
outreach, still single-open via the existing `ArtifactSummarySection`) —
behind one "View detailed analysis and evidence" toggle. No route, component,
or capability is removed; `kit-quick-actions.tsx` was deleted because its
sticky-bar responsibilities are now fully covered by the primary downloads
section and the advanced entry, leaving it with zero remaining callers.

### Added keywords reuse the existing evidence-gated field

The compact "keywords added" chip row needed an engine-authoritative signal
for which JD keywords are genuinely new in the tailored resume. This already
exists: `MatchReport.keywords_surfaced_by_tailoring` (ADR-0019) is exactly
"matched in the tailored resume, not matched in the original," gated by the
same evidence-tier credit used for scoring. No new engine field was added —
duplicating an existing, already-evidence-gated field under a second name
would be a redundant field to keep in sync for no behavioral gain. Kits that
predate this field (v4 and earlier) have no `match_report` at all, so the
section's honest empty state covers them without any special-casing.

### Job priorities: a new, deterministic, JD-only field

`MatchReport.job_priorities: list[JobPriorityItem]` is new
(`ats_engine.scoring.job_priorities.build_job_priorities`). It groups the
already-built evidence matrix by its coarse requirement category (the same
categories `evidence.matrix.classify_requirement_category` already produces),
ranks required-backed categories ahead of preferred-only ones, and yields up to
six short `{theme, detail}` bullets — a keyword outside every coarse category
becomes its own single-keyword theme rather than being folded into a vague
catch-all. It reads only `EvidenceItem.category` / `.keyword` /
`.required_or_preferred` — **never** `real_evidence` — so it is deterministic
and provably candidate-identity-invariant: two different resumes against the
same JD produce byte-identical priorities. It never fabricates a theme to
reach a minimum count; a thin JD simply returns fewer.

Serialization follows the existing `MatchReport` pattern exactly
(`_job_priority_to_dict`/`_job_priority_from_dict` in `kit/serialization.py`,
`.get(..., [])` on read) and the API's `JobPriorityItemResponse` carries a
`default_factory=list`, so a kit persisted before this field existed
deserializes to an empty list, never an error.

### DOCX export is a new engine renderer, not a client pipeline

`ats_engine.generation.docx_renderer` (`render_resume_docx`,
`render_cover_letter_docx`, `render_plain_text_docx`) renders the same
`ResumeDocument`/`CoverLetterDocument` contract the HTML/PDF renderer already
consumes into single-column, ATS-safe `.docx` bytes via `python-docx` — no
tables, no images, no text boxes, so an ATS text extractor and a human reader
see the same content in the same order. `python-docx` is a pure-Python OOXML
writer (already an engine dependency for input-side `.docx` parsing), unlike
WeasyPrint (confined to `apps/api` per ADR-0004/ADR-0018), so this renderer
lives in the engine alongside the HTML renderer rather than in the API layer.

The freeform/local-edit fallback path (heading recognition for a local edit
with no structured document) was extracted out of `html_renderer.py` into two
shared functions — `parse_freeform_document`, `freeform_line_blocks` — so the
PDF and DOCX exports of the same local edit agree on structure instead of each
carrying their own copy of the heuristic.

`apps/api/app/document_export.py` gained a sibling `build_docx_export`
alongside the existing `build_export` (PDF), sharing one `_resolve` step that
resolves the artifact once (structured document, local-edit text, or plain
fallback) for both formats. `POST /api/v1/document-exports/docx` is a new,
fully additive route beside the existing `/pdf` route — same
`DocumentExportRequest` schema, same `Content-Disposition`-filename contract,
same local-edit-is-never-persisted guarantee. `build_export_filename` gained
an optional `extension` parameter (default `"pdf"`) so both formats share the
one naming convention.

On the frontend, `QuickPdfDownload` gained an optional `format?: "pdf" |
"word"` prop (default `"pdf"`, so every existing caller is unchanged) and
calls `exportDocumentDocx` when `"word"` is selected; a new `FormatSelector`
segmented control (a real ARIA `radiogroup`) sits above the two document cards
and relabels both download buttons at once. No second export pipeline, no
client-side rendering of the binary — both formats call the existing
one-click download path and read the filename from the server's
`Content-Disposition` header.

### Top-level `ApplicationKit.validation` refresh after a change action

Independent of the D4 work: a review found that a successful change-action
batch refreshed each artifact's own `ArtifactValidation` but never the kit-wide
`ValidationSummary` roll-up, so `kit.validation.warning_count`/`fatal` could go
stale relative to the artifacts it summarizes. `kit/change_actions.py` now
recomputes it after every successful batch
(`_recompute_kit_validation`): the roll-up's prefixed `"resume: ..."`/`"cover
letter: ..."` entries (the same prefixing `validate_pipeline_result` uses) are
replaced with fresh ones from the just-rebuilt artifacts, every other
artifact's contribution is carried over untouched, and `fatal` is recomputed
across all six artifacts — matching the exact rule initial generation uses.

## Consequences

- The results-first hierarchy is the only Kit-results experience; there is no
  separate, more-technical page a user reaches by a different path.
- `keywords_surfaced_by_tailoring` now has two consumers (the advanced
  `MatchInsights` panel and the compact `KeywordsAdded` chips) instead of one;
  both read the same evidence-gated field, so they can never disagree.
- DOCX export is a genuine, tested capability, not a documented gap: both
  formats are exercised end-to-end (API tests, and a real generated-kit smoke
  test) with the same fidelity guarantees as the existing PDF path.
- No Alembic migration was needed — `job_priorities` lives inside the existing
  `kits.result` JSON column, and every new API response field has a default,
  so older persisted kits keep serving without error.

## Deviations from the D4 package

- The package's `IMPLEMENTATION-HANDOFF.md`/`component-deltas.md` describe the
  *prior* K1 unified-workspace delivery (already shipped) and were superseded
  by this results-first simplification; they were not re-implemented as
  written. The authoritative hierarchy here follows the task's explicit
  7-item list (never the older 7-item K1 spec's "How we strengthened" card,
  main-page requirement table, four job-fit categories, or long "More about
  this Kit" accordion).
- Sticky/fixed mobile action bars described in `QUICK-ACTIONS-AND-DOWNLOADS.md`
  were not built: the downloads section stays in normal document flow, which
  already satisfies "does not cover content or navigation" without a new
  fixed-position component.
- Hash-based deep-linking into the advanced sub-sections was simplified to
  local component state (no `#job-fit`-style URL sync) to keep the new
  disclosure surface small and easy to reason about; this can be added later
  without a contract change if deep-linking into advanced detail is needed.
