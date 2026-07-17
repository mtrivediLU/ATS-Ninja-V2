# @ats-ninja/web

The ATS-Ninja frontend: Next.js 15 App Router, React 19, strict TypeScript, and
Tailwind CSS 4.

## Current scope: Design Phase D0

D0 implements the approved **Signal** UI foundation:

- approved machine-readable tokens in `design-tokens.json`, mirrored to semantic
  CSS properties and Tailwind 4 theme mappings in `app/globals.css`
- Hanken Grotesk and IBM Plex Mono through `next/font`
- responsive sidebar, tablet rail, mobile drawer, and mobile bottom navigation
- workspace header and route-based artifact tabs
- inline desktop evidence panel and tablet/mobile evidence drawer
- typed presentation mapping for kit, claim, absent, and withheld statuses
- foundational controls, feedback, empty/loading/error states, and accessibility behavior

The content is intentionally synthetic. New Kit does not submit or poll the API,
artifact routes are structural placeholders, and no evidence, scoring, grounding,
or validation logic runs in the browser.

## Foundation routes

| Route | D0 purpose |
| --- | --- |
| `/` | First-use and disconnected New Kit foundation |
| `/history` | Synthetic history and empty-history states |
| `/kits/demo/resume` | Completed results shell and validation warning |
| `/kits/demo/cover-letter` | Cover-letter placeholder shell |
| `/kits/demo/answers` | Application-answer placeholder and empty artifact |
| `/kits/demo/job-fit` | Job-fit placeholder with synthetic rendered values |
| `/kits/demo/interview-prep` | Not-requested artifact state |
| `/kits/demo/linkedin-outreach` | Withheld/draft-only artifact state |
| `/components` | Component-foundation showcase |
| `/settings` | Non-persisted local-settings foundation |
| `/states/processing` | Processing and slow-processing demonstration |
| `/states/error` | Failed, API-unavailable, and worker-unavailable states |

## Structure

- `design-tokens.json` is the approved machine-readable token source.
- `app/globals.css` exposes those values to CSS and Tailwind 4.
- `components/shell` owns layout and navigation presentation.
- `components/ui` owns reusable, product-logic-free primitives.
- `components/foundation` composes synthetic D0 screens.
- `lib/navigation.ts` is the single typed navigation configuration.
- `lib/status.ts` maps existing API status values to accessible presentation.
- `lib/demo-data.ts` contains clearly synthetic records used only by D0.

Desktop uses a 248px sidebar and optional 360px evidence panel. Tablet uses a
64px rail and overlay drawers. Mobile uses the header drawer plus a 60px bottom
bar, scrollable artifact tabs, and full-width evidence sheet. Later phases
should extend the content inside the existing artifact routes and continue to
render backend contracts without recomputing them.

## Run locally

```bash
pnpm install
pnpm --filter @ats-ninja/web dev     # http://localhost:3000
```

## Quality gates

```bash
pnpm --filter @ats-ninja/web lint
pnpm --filter @ats-ninja/web typecheck
CI=1 pnpm --filter @ats-ninja/web build
```

## Intentionally not connected

D0 does not implement real Kit submission/polling, detailed artifact workflows,
PDF upload, evidence drill-down, authentication, credits, billing, analytics,
LinkedIn access, or message sending.
