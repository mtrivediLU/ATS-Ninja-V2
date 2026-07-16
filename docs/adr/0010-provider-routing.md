# ADR-0010 — Vendor-neutral provider routing

- Status: Accepted
- Date: 2026-07-11
- Extends: [ADR-0003](0003-llm-provider-abstraction.md)

## Context

The orchestrator needs to choose a model provider and produce accurate provider
metadata, without turning into a multi-provider marketplace and without leaking a
vendor into domain code. It must also keep the deterministic `provider=None` path
working end to end, and it must never fabricate metrics it cannot measure.

## Decision

Add a lightweight routing layer (`ats_engine.kit.routing`):

- **`resolve_providers`** mirrors the engine's provider-selection rules (explicit
  providers, else `use_llm=False` → deterministic, else the configured Ollama
  pair) and returns the providers to pass into the pipeline plus the metadata
  inputs. Provider choice stays configuration-driven; no vendor SDK enters domain
  logic.
- **Primary / optional fallback / deterministic.** A `FallbackProvider` tries the
  primary and, **only when the primary raises**, uses a configured fallback.
  Candidate-derived prompts are never fanned out speculatively to multiple
  providers; a second provider sees the prompt only to recover from a real
  failure, and only because a fallback was configured. With no fallback, a
  provider failure degrades to the deterministic path (the engine's
  `generate_text` swallows the error and returns `""`).
- **Accurate metadata only.** A `CountingProvider` counts real provider calls and
  records fallback usage. `GenerationMetadata` reports provider identity, model,
  generation mode, call count, and fallback usage — and deliberately omits token
  counts, cost, and latency, which the current providers cannot report
  accurately. No provider key is ever stored.

## Consequences

- Adding a hosted provider is a sibling adapter plus configuration; domain models
  do not change.
- The deterministic path is preserved and is the safe default when no provider is
  reachable.
- Fallback is a deliberate, privacy-bounded policy, not automatic fan-out.
- Production multi-provider routing/optimization is future work; this phase ships
  the minimum routing shape needed and nothing more.
