# ADR-0018: Local server-side PDF rendering for direct Resume/Cover Letter download

Status: Accepted
Date: 2026-07-20

## Context

ADR-0004 deferred binary PDF rasterization out of the engine, with an explicit
exit condition: "Revisit when server-side PDF output is a concrete product
requirement, at which point it belongs behind an explicit rendering interface
... not as a core engine dependency." Until now the only downloadable formats
were plain text, engine-provided LaTeX, and the browser's own Print / Save as
PDF (`apps/web/components/product/templates/print-preview.tsx`), which opens
the OS print dialog rather than producing a file directly.

The product now needs a real "Download PDF" action: one click, a real binary
PDF response, a standardized filename, no print dialog, no external service.

## Decision

Split the work exactly along the boundary ADR-0004 anticipated:

- **`packages/engine/src/ats_engine/generation/html_renderer.py`** — pure
  Python, stdlib-only (`html.escape`), no new dependency. Turns the existing
  `ResumeDocument`/`CoverLetterDocument` contract (already used for the
  on-screen structured templates) into standalone, single-column HTML with an
  inlined stylesheet mirroring the app's own Classic/Modern typography. A
  third function, `render_plain_text_html`, ports the frontend's
  heading-recognition heuristic (`document-model.ts`) for the one case with no
  structured document: a request-scoped local edit.
- **`apps/api/app/document_export.py`** — the only place WeasyPrint is
  imported. It resolves a completed Kit's persisted result (or a local edit,
  accepted for the duration of one request and never persisted), renders HTML
  via the engine, and calls `HTML(string=html).write_pdf()`.
- **`POST /api/v1/document-exports/pdf`** — synchronous, not queued through
  Celery (Phase 13 guidance: normal Resume/Cover Letter sizes render in well
  under a second; WeasyPrint rendering runs in `asyncio.to_thread` so it does
  not block the event loop, matching how the worker already offloads engine
  generation).

WeasyPrint was chosen over a headless-Chromium approach (Playwright/Puppeteer)
because it is a proper CSS Paged Media implementation — `@page` size/margins,
`break-inside: avoid`, `orphans`/`widows` are first-class, not print-CSS
approximations — and it ships as a single native-library dependency
(`libpango`, `libcairo`, `libgdk-pixbuf`) instead of a bundled browser. This
keeps the "smallest reliable local renderer" property ADR-0004 asked for. The
native dependency is confined to `infra/docker/api.Dockerfile` and
`apps/api/pyproject.toml`; `packages/engine` remains exactly as portable as
before this change — it still runs with zero binary dependencies.

The filename convention (`ApplicantName_JobTitle_CompanyName_<Artifact>[_<Template>].pdf`)
lives in `packages/engine/src/ats_engine/generation/filenames.py`: one
deterministic, heavily-tested function is the single source of truth, and the
API sets it via `Content-Disposition`. The frontend never recomputes it — it
reads the header and downloads whatever name the server chose. This requires
`Access-Control-Expose-Headers: Content-Disposition` on the API's CORS
middleware; `Content-Disposition` is not on the browser's CORS-safelisted
response-header list, so without it `fetch()` silently returns `null` for the
header even though curl/httpx/server-side tests can always see it.

## Consequences

- `packages/engine` still has zero binary/native dependencies; only
  `apps/api` gained one (WeasyPrint + its native libs).
- The PDF and the on-screen structured template now share one source of
  truth (`ResumeDocument`/`CoverLetterDocument`); a future template change
  updates both from the same data.
- A local edit's PDF export is genuinely request-scoped: the edited text is
  never written to the Kit row, never logged, and the structured document
  path is bypassed entirely in favor of the heading-recognition fallback.
- ADR-0004's engine-purity outcome stands unchanged; only its "revisit when
  needed" clause is now exercised, and only at the `apps/api` layer it
  predicted.
