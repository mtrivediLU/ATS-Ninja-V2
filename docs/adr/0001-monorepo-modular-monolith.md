# ADR-0001 — Monorepo, modular monolith with a future async worker

- Status: Accepted
- Date: 2026-07-09
- Phase: 0

## Context

ATS-Ninja-V2 must optimize for modularity, testability, low operational cost,
horizontal scalability, infrastructure portability, minimal vendor lock-in, and
maintainability by a future team. The legacy app was a single Streamlit process
mixing UI, orchestration, and domain logic.

## Decision

Use a single repository with three units — `packages/engine` (domain),
`apps/api` (FastAPI), `apps/web` (Next.js) — plus `infra` and `docs`. Build a
**modular monolith**: one deployable API process that imports the engine
in-process, with a **separately-executable async worker** added in a later phase
(sharing the API image and the engine). Avoid premature microservices.

## Consequences

- Clear boundaries with cheap in-process calls between API and engine; no network
  hop or serialization tax for domain work.
- The engine is independently importable/testable and carries no framework.
- Horizontal scale comes from running more API/worker replicas behind a load
  balancer; the worker scales independently of request-serving.
- One repo means atomic cross-cutting changes and a single quality-gate story.
- If a piece ever needs to be a separate service, the existing package boundary is
  the natural seam — but we do not pay that cost until it is justified.
