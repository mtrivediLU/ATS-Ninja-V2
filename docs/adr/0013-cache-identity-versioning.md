# ADR-0013 — Cache identity and versioning

- Status: Accepted
- Date: 2026-07-11
- Related: [ADR-0007](0007-application-kit-contract.md), [ADR-0010](0010-provider-routing.md)

## Context

The engine caches LLM generations under a SHA-256 key of `(provider.identity,
prompt)`. With the new ApplicationKit contract and grounded orchestration, we
must ensure stale Phase 1 prose cannot masquerade as ApplicationKit v1 output,
that cache identity captures the inputs that materially change generated output,
and that no secret or raw resume text ends up in a cache key.

## Decision

- **Contract-salted identity.** The orchestrator wraps every provider so its
  cache `identity` is salted with the schema *and* orchestration contract
  versions (`|orch=application-kit/v1:grounded-orchestration/v1`). A bump to
  either version changes the identity, so a change in grounding/orchestration
  behavior never reuses prose cached under an older contract.
- **Inputs already covered.** The cached unit is a single prose *generation*
  keyed on the exact prompt, and the prompt already embeds the material inputs
  (candidate evidence excerpts, JD, requested keywords, provider identity/model).
  The ApplicationKit itself is **never cached as a unit** — it is reassembled and
  re-grounded on every run — so a stale kit cannot be served whole.
- **Keys hide sensitive data.** `make_key` returns a SHA-256 hex digest; the raw
  resume text is never a human-readable key, and secrets/provider keys are never
  part of any key.

## Consequences

- Bumping `SCHEMA_VERSION` or `ORCHESTRATION_VERSION` cleanly invalidates cached
  prose, preventing cross-contract reuse.
- Provider identity (model + decoding params) participates in the key, so two
  models never share cached output.
- No kit-level cache is introduced; grounding always runs, so caching can never
  let a fabrication slip past the gate.
