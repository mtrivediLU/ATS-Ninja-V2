# ADR-0008 — Claim and evidence traceability model

- Status: Accepted
- Date: 2026-07-11
- Related: [ADR-0007](0007-application-kit-contract.md), [ADR-0009](0009-validation-wrapped-generation.md)

## Context

The product's differentiator is that a candidate-specific claim only ships if the
candidate's own evidence supports it. Before Phase 2A that guarantee lived only
as pass/fail error strings; it was impossible to answer, per claim, *"why was
ATS-Ninja allowed to say this about the candidate?"* Truth-grounding needed to
become visible, structured data — without turning the trace into a second copy
of the resume (candidate data is sensitive).

## Decision

Introduce a typed claim/evidence trace:

- **`ClaimRecord`** — an `id`, the owning `ArtifactKind`, a `ClaimType`
  (employer, title, skill, metric, monetary, team size, management, tenure,
  certification, education), the (bounded) claim text, a `ClaimStatus`
  (`supported` / `repaired` / `rejected`), a human-readable `disposition` and
  `reason`, and its evidence references.
- **`EvidenceRef`** — a `source`, a stable `locator` (e.g. `supported_metric`,
  `experience`, `education`), and a **bounded excerpt** capped at
  `EVIDENCE_EXCERPT_MAX_CHARS` (160). The trace records *supported* claims too,
  so the kit carries positive proof, not only rejections.

Support is decided **evidence-first**: a claim is supported only if it traces to
the candidate's own resume (structured profile fields plus the raw resume). The
job description is a targeting source, never candidate evidence; the one
deliberate exception is naming the target company/role, which is not a claim
about the candidate's history.

### Privacy trade-off

We include short, bounded evidence excerpts (and the claim text) rather than
either (a) the whole resume, which would duplicate sensitive data across the
result, or (b) nothing, which would make the trace unauditable. Excerpts are
capped and the trace stores stable locators, not offsets into the raw document.

## Consequences

- Every completed kit answers, per claim, why a statement about the candidate was
  permitted or removed — auditable by product, support, and the candidate.
- The trace is bounded and safe to persist and return over the API.
- The `ClaimType` set is the enforcement surface for the repair/rejection policy
  (ADR-0011); adding a fabrication category means adding a type here and a rule
  there.
