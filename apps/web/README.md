# @ats-ninja/web

The ATS-Ninja-V2 frontend: Next.js (App Router) + TypeScript + Tailwind CSS v4.

**Phase 0 scope:** a static product shell that proves the frontend builds and
runs. It contains **no business logic** — resume scoring, gap analysis, claim
validation, and evidence logic live in the Python engine and are reached only
through the API. No fake dashboards or generated kits are included.

## Run locally

```bash
pnpm install            # from the repo root
pnpm --filter @ats-ninja/web dev     # http://localhost:3000
```

## Quality gates

```bash
pnpm --filter @ats-ninja/web lint
pnpm --filter @ats-ninja/web typecheck
pnpm --filter @ats-ninja/web build
```
