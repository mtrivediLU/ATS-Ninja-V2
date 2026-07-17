# @ats-ninja/web

The ATS-Ninja private local frontend: Next.js 15 App Router, React 19, strict
TypeScript, and Tailwind CSS 4.

## Current scope: Design Phase D1

D1 connects the approved D0 **Signal** shell to the real FastAPI and
ApplicationKit v4 lifecycle:

- three-step New Kit workflow with form validation and six independent outputs
- optional application questions and typed LinkedIn outreach context
- real `POST /api/v1/kits`, cancellable lifecycle polling, and terminal states
- real Kit overview and six artifact workspaces
- server-provided Job Fit, Interview Prep, outreach, validation, and evidence
- local-only editing, clipboard actions, and text/LaTeX downloads
- paginated server-backed history with loaded-page search/filter/sort
- responsive desktop, tablet, and mobile behavior inherited from D0

The browser never calculates scores, fit bands, gaps, evidence support, claim
repairs, STAR completeness, or relationship validity. It renders API values.

## Routes

| Route | Purpose |
| --- | --- |
| `/` | Private local landing and first-use state |
| `/kits/new` | New Kit inputs, independent output selection, review, submission |
| `/kits/[kitId]` | Real Kit lifecycle and overview |
| `/kits/[kitId]/resume` | Resume read/local-edit/copy/text/LaTeX/evidence |
| `/kits/[kitId]/cover-letter` | Cover letter workspace |
| `/kits/[kitId]/answers` | Structured application answers |
| `/kits/[kitId]/job-fit` | Deterministic-authoritative Job Fit |
| `/kits/[kitId]/interview-prep` | Questions, guides, STAR candidates, study topics |
| `/kits/[kitId]/linkedin-outreach` | Draft-only outreach with provenance and limits |
| `/history` | Paginated real Kit history and reopen flow |
| `/components` | D0 component reference surface |
| `/kits/demo/[artifact]` | Clearly synthetic D0 development fixtures |

## API configuration

Browser calls use `NEXT_PUBLIC_API_BASE_URL`. For safe local development it
defaults to `http://localhost:8000`; the legacy `NEXT_PUBLIC_API_URL` alias is
also accepted. Public environment values are compiled into the web bundle, so
set the build argument when building for a different local API origin.

```bash
cp apps/web/.env.example apps/web/.env.local
```

No candidate input is stored in `localStorage` or placed in a query string.

## Artifact selection and polling

The frontend sends all six persisted include flags explicitly. The API retains
`requested_mode` compatibility for older clients. After a `202`, the browser
navigates to the real Kit route and polls `GET /api/v1/kits/{id}` every 1.5
seconds without overlapping requests. Polling stops on `completed` or `failed`
and is aborted when the route unmounts.

## Local edits, copy, and downloads

Resume, cover-letter, and answer edits exist only in React state. They are
labelled “Edited since generation”, are not sent to the backend, and are not
revalidated. Reloading restores generated content. Copy and download use the
current local text; LaTeX is downloadable when returned. No rendered PDF is
promised or produced.

Download filenames are bounded and sanitized from available target context.
Generated content never leaves the browser for copy/download actions.

## History behavior

`GET /api/v1/kits` supplies real newest-first pagination. D1 retrieves details
for the currently loaded page so it can show available target/artifact values.
Search, filter, and sort operate only over that page and are labelled honestly.
Rename, duplicate, and delete are omitted because the API exposes no endpoints.

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

D1 does not implement PDF/DOCX upload, saved/revalidated edits, per-artifact
regeneration, rendered PDF download, history mutations, authentication, billing,
credits, analytics, LinkedIn access/sending, public hosting, or external
research. Later design work should extend the typed API/client/component
boundaries without moving backend business rules into the web app.
