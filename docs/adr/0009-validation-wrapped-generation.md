# ADR-0009 — Validation-wrapped generation orchestration

- Status: Accepted
- Date: 2026-07-11
- Related: [ADR-0011](0011-repair-vs-rejection-policy.md), [ADR-0003](0003-llm-provider-abstraction.md)

## Context

The Phase 1 audit found that generation-time checks rejected *some* unsupported
rewrites (metrics, known skills) in favor of deterministic fallbacks, but:

1. application answers received almost no claim validation;
2. cover-letter and summary prose had no employer/title/novel-skill/certification/
   degree checks; and
3. when the final validators *did* detect a fabrication, the content was flagged
   as a string but **not removed** — and the kit still shipped `completed`.

Detection was not the same as absence. Phase 2A must guarantee that no fabricated
candidate-specific claim reaches the final ApplicationKit.

## Decision

Add a grounded orchestration layer in the engine (`ats_engine.kit.orchestrator`,
`ats_engine.kit.grounding`) that sits **above** the proven pipeline and composes
it — it does not reimplement parsing, evidence, scoring, or generation. Flow:

1. resolve providers (primary / optional fallback / deterministic — ADR-0010);
2. run the existing pipeline (parse → evidence → plan → AI prose → validate);
3. build a deterministic evidence view of the candidate;
4. **ground every artifact's prose**: extract structured claims, classify support
   against evidence, and remove or reject unsupported claims *inside the plans*;
5. **re-render text and LaTeX from the sanitized plans**, so both surfaces are
   clean by construction (not just the human-readable text);
6. re-run the engine's artifact validators on the clean output; and
7. assemble the ApplicationKit with the full claim/evidence trace.

Grounding runs over **all** artifacts — resume summary/bullets, cover letter, and
answers — because cover letters and answers can hallucinate candidate facts too.
Claim extraction is deterministic (regex + evidence membership) and covers
employers, titles, skills/expertise, percentages (symbol *and* spelled-out),
money (symbol *and* spelled-out), team size/management, tenure, certifications,
and degrees.

The worker calls the orchestrator; the ApplicationKit logic never lives in
FastAPI or Celery, and prompts never live in Celery task code.

## Consequences

- Fabrications are absent from the delivered artifacts, not merely flagged — the
  core Phase 2A guarantee, proven by the adversarial suite.
- Re-rendering from sanitized plans keeps `text` and `latex` consistent.
- We reuse (not fork) the proven deterministic engine; the orchestrator is the
  only new composition path, and the deterministic `provider=None` path is a
  no-op for grounding (nothing to remove).
- Claim extraction is precise-but-not-perfect on free prose; see ADR-0011 for the
  removal-over-detection stance and the honest limitations.
