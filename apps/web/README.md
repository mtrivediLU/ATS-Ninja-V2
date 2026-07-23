# @ats-ninja/web

The ATS-Ninja private local frontend: Next.js 15 App Router, React 19, strict
TypeScript, and Tailwind CSS 4.

## Structured documents and printing

Resume and Cover Letter templates prefer optional engine-provided structured
document fields, then use the conservative text parser/verbatim fallback for
older Kits. Classic and Modern render the same source content. Print / Save as
PDF uses one flowing print-only document root, excluding all application
warnings and controls. Local edits stay local and are not revalidated.

## Current scope: Design Phase K1

K1 makes `/kits/[kitId]` the completed-Kit workspace: one continuous, scrollable
page with a compact Kit header, sticky quick actions, a persisted-trust strip,
primary Resume and Cover Letter cards, and inline summaries for all remaining
artifacts. Resume PDF, Cover Letter PDF, Copy all answers, Copy recommended
outreach, View Job Fit gaps, Start interview review, and Review warnings are
one-click actions from this page. Common review expands inline without a route
change; the six existing artifact routes remain advanced, distraction-free
workspaces for deeper editing, comparison, printing, and export.

The page reads the existing `KitProvider` result and starts no per-card request
or polling loop. Only one large artifact detail mounts at a time; the selected
Classic/Modern template is shared in React session state with the advanced
template workspace and never stored in browser storage. The quick PDF control
reuses the existing direct export endpoint and server `Content-Disposition`
filename. K1 does not change API, engine, evidence, ATS, or fit logic.

The workspace is responsive at desktop, tablet, and mobile: document cards
stack below desktop, quick document actions become a mobile bar above bottom
navigation, and the existing evidence surface remains a panel/drawer/sheet.
Expandable regions use semantic controls, focus movement/restoration, Escape,
and reduced-motion-safe transitions. Known limitation: local edits are still
owned by the advanced workspace and intentionally disappear on reload.

### D2 foundations retained

D2 retains the D0 **Signal** foundation and D1 real workflows, then adds the
trust, evidence, editing, recovery, accessibility, and responsive polish needed
for private local dogfooding:

- three-step New Kit workflow with form validation, six independent outputs,
  and Paste text / Upload file resume modes
- optional application questions and typed LinkedIn outreach context
- real `POST /api/v1/kits`, cancellable lifecycle polling, and terminal states
- trust-first and content views for all six artifact workspaces, with counts and
  evidence-trace distribution derived only from persisted claim/validation fields
- trace filters by returned artifact and status, bounded excerpts, reasons,
  disposition, keyboard previous/next, and desktop panel/tablet drawer/mobile sheet
- unified generated, notes, removed, withheld, not-requested, unavailable,
  empty, failed, partial, older-format, and locally edited presentation states
- local-only document and outreach editing with dirty warnings, apply-local-edits,
  discard/reset confirmations, compare, browser-close/route protection, and
  persistent not-revalidated wording
- source-labelled copy/download dialogs, safe bounded filenames, text/LaTeX and
  Markdown exports, failure feedback, and mobile editing actions
- accumulated API-page history with honest loaded-item search/filter/sort,
  active filters, included-artifact filter, load-more, schema compatibility, and
  status-aware reopen behavior
- calm processing/retrieval recovery with no fabricated ETA or progress percentage
- Job Fit gap emphasis, Interview study focus mode with interaction-only progress,
  and per-draft Outreach local editing/context provenance/mobile copy

The browser never calculates scores, fit bands, gaps, evidence support, claim
repairs, STAR completeness, or relationship validity. It renders API values and
only aggregates existing trace records for presentation.

## Routes

| Route | Purpose |
| --- | --- |
| `/` | Private local landing and first-use state |
| `/kits/new` | New Kit inputs, independent output selection, review, submission |
| `/kits/[kitId]` | Unified Application Kit results workspace and lifecycle states |
| `/kits/[kitId]/resume` | Resume read/local-edit/copy/text/LaTeX/evidence |
| `/kits/[kitId]/cover-letter` | Cover letter workspace |
| `/kits/[kitId]/answers` | Structured application answers |
| `/kits/[kitId]/job-fit` | Deterministic-authoritative Job Fit |
| `/kits/[kitId]/interview-prep` | Questions, guides, STAR candidates, study topics |
| `/kits/[kitId]/linkedin-outreach` | Draft-only outreach with provenance and limits |
| `/history` | Paginated real Kit history and reopen flow |
| `/components` | D0 component reference surface |
| `/kits/demo/[artifact]` | Clearly synthetic D0 development fixtures |
| `/states/d2` | Clearly labelled D2 development-only unavailable/partial/old-schema fixtures |

## API configuration

Browser calls use `NEXT_PUBLIC_API_BASE_URL`. For safe local development it
defaults to `http://localhost:8000`; the legacy `NEXT_PUBLIC_API_URL` alias is
also accepted. Public environment values are compiled into the web bundle, so
set the build argument when building for a different local API origin.

```bash
cp apps/web/.env.example apps/web/.env.local
```

No candidate input is stored in `localStorage` or placed in a query string.

## Resume upload and review

The New Kit input step supports a plain-text paste path and a local file path.
The file picker/drop zone accepts text-based PDF, DOCX, and TXT files up to
10 MB. The browser sends a file only to `POST /api/v1/resume-extractions`, then
shows its returned text in an editable preview. The candidate must review that
text; only the reviewed text is submitted using the existing Kit JSON request.

Replacing, removing, or switching sources confirms before discarding reviewed
text. Extraction requests are cancellable and stale responses are ignored. The
browser stores neither the file nor extracted text. There is no OCR or legacy
`.doc` support; scanned/image-only and encrypted PDFs surface a safe error.

`ResumeExtraction`'s optional `manual_review_recommended` flag from the API
(the extraction engine's own quality-scoring signal, never a candidate-content
judgment) already surfaces through the existing `warnings` banner in the
upload step with no new component needed — the wizard renders every string in
`extraction.warnings` and switches the banner to its warning tone whenever the
array is non-empty.

`lib/product.ts`'s `kitTarget()` reads target company/role from whichever
requested artifact carries it (LinkedIn Outreach, then Cover Letter) instead
of only the former, so the header does not show "Target company unavailable"
just because Outreach wasn't requested. `safeWithheldReason()` maps a withheld
artifact's persisted validation errors to one of a small set of safe,
actionable messages instead of a generic fallback.

## Artifact selection and polling

The frontend sends all six persisted include flags explicitly. The API retains
`requested_mode` compatibility for older clients. After a `202`, the browser
navigates to the real Kit route and polls `GET /api/v1/kits/{id}` every 1.5
seconds without overlapping requests. Polling stops on `completed` or `failed`
and is aborted when the route unmounts.

## Trust, evidence, and artifact state

Every real workspace defaults to a route-backed **Trust** view (`?view=content`
opens Content). Trust summaries show supported, adjusted, removed, withheld, and
warning counts from the returned records; their trace-distribution percentage is
explicitly labelled as presentation, not a quality/readiness/AI-confidence score.

The evidence panel renders bounded API excerpts only. It filters returned traces
by artifact and D2 status, supports keyboard ←/→ traversal, and restores focus on
close. The API provides no character offsets, so the UI deliberately renders
trace markers below text rather than inferring claim positions by browser string
matching. The development-only D2 fixture exercises unavailable evidence without
mixing synthetic records into real Kits or history.

### D2 semantic token deltas and state model

D2 adds only `--status-edited-{fg,bg,border}`,
`--status-unavailable-{fg,bg,border}`, and `--readiness-track` to the existing
light-theme Signal token layer. Tailwind exposes matching semantic colors; no
component contains new raw state hex values. Edited uses a cool slate treatment;
unavailable uses a muted dashed treatment. The unified presentation model is:
generated, ready-with-notes, removed, withheld, not-requested, unavailable,
empty, failed, partially-generated, older-format, and edited-not-revalidated.
Every state is an icon plus text and maps only to persisted lifecycle,
validation, selection, or explicitly local editing state.

## Local edits, copy, and downloads

Resume, cover-letter, application-answer, and individual outreach-draft edits
exist only in React state. “Apply local edits” never sends content to the API;
the edit is labelled “Edited — not revalidated,” can be compared with the
read-only generated version, reset, or discarded, and disappears on reload.
Browser-close and ordinary route navigation warn only for true unsaved editor
changes. No candidate content is stored in localStorage/sessionStorage.

Copy/download actions identify whether they use generated, applied local, or
currently unsaved local text. Text is available for every export; the engine
provided LaTeX remains optional for resume/cover-letter; Interview Preparation
exports Markdown.

Download filenames are bounded and sanitized from available target context.
Generated content never leaves the browser for copy/download actions.

### Resume/Cover Letter template PDF download

The template workspace's primary **Download PDF** button
(`components/product/templates/template-preview.tsx`) calls
`POST /api/v1/document-exports/pdf` directly and saves the response as a real
binary file — no browser print dialog, no external service. It sends
`content_source: "local_edit"` and the current draft text only when the
active source actually is a local edit (never persisted server-side by that
request); otherwise it exports the generated, already-validated Kit content.
The button disables itself and shows a spinner for the duration of the
export (no duplicate in-flight exports) and announces success or a specific
failure reason through the existing toast system. The downloaded filename is
never computed in the frontend: it is read from the API's
`Content-Disposition` header, which is the single source of truth for the
`ApplicantName_JobTitle_CompanyName_<Resume|Cover_Letter>[_Classic|_Modern].pdf`
convention (`ats_engine.generation.filenames.build_export_filename`). Print /
Save as PDF, plain-text, and LaTeX export remain available from a secondary
"More export options" menu next to the primary button.

## History behavior

`GET /api/v1/kits` supplies real newest-first pagination. D2 accumulates the
pages explicitly loaded with **Load more** so filtering/search/sort can operate
over those loaded items; this limitation remains labelled in the UI and is not
represented as server-wide search. History exposes lifecycle, included-artifact,
and validation-notes filters, clearable active filters, old-schema/partial/failed
indicators, and normal reopen links. Rename, duplicate, and delete are omitted
because the API exposes no endpoints.

## Recovery, responsive behavior, and accessibility

Lifecycle presentation names only persisted Kit states. Pending/processing/slow,
temporary retrieval interruption, malformed response, failed Kit, retry, and
connection-restored states use client-safe copy without asserting an unknown
worker or broker failure. There is no fake progress bar or ETA.

The shell is verified at desktop, tablet, and mobile breakpoints. Evidence is an
inline desktop panel, a tablet drawer, and a mobile sheet. Artifact tabs scroll,
mobile editing actions sit above bottom navigation/safe-area clearance, and wide
Job Fit tables scroll inside their region. Statuses include icon + text, drawers
and dialogs trap/restore focus and support Escape, trace navigation is keyboard
accessible, feedback is announced through live regions, and reduced-motion rules
remain in the base token layer.

## Run locally

```bash
pnpm install
pnpm --filter @ats-ninja/web dev
```

Or run the full local product:

```bash
ATS_API_ENGINE_USE_LLM=false docker compose up -d --build
```

- Web: `http://localhost:3000`
- API health: `http://localhost:8000/health`

## Quality gates

```bash
pnpm --filter @ats-ninja/web lint
pnpm --filter @ats-ninja/web typecheck
CI=1 pnpm --filter @ats-ninja/web build
docker compose config
```

## Intentionally unsupported

D2 does not implement server-persisted/revalidated edits, per-artifact
regeneration, history mutations, authentication, billing, pricing, credits,
analytics/tracking, LinkedIn access/sending, public hosting, or external
research. It is private-local
dogfooding polish, not public-SaaS work. Later work must extend typed API/client
boundaries without moving domain logic into the browser.
