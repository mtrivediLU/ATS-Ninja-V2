# ADR-0011 — Repair vs rejection policy for unsupported claims

- Status: Accepted
- Date: 2026-07-11
- Related: [ADR-0009](0009-validation-wrapped-generation.md)

## Context

When generated prose asserts a candidate-specific claim the evidence does not
support, the system must do something explicit and bounded — never "let the AI
retry until it looks right," and never soften a fabricated identity/history fact
into acceptance just because the wording changed.

## Decision

A single, explicit policy (`ats_engine.kit.policy`), applied deterministically:

- **Every** candidate-specific claim category is fabrication-sensitive (employer,
  title, skill, metric, monetary, team size, management, tenure, certification,
  education). An unsupported instance is **removed** from the artifact.
- **Repair = removal.** Removal can never make a fabrication survive, so it is
  always the safe default:
  - prose (summary, cover letter, answers): the offending **sentence** is
    excised;
  - candidate-authored resume bullets: the offending **span** is redacted in
    place, so completeness accounting (bullet counts) is preserved.
- **Rejection.** If a single deterministic pass cannot eliminate the fabricated
  value (it remains detectable on re-verification), or if repairing a required
  prose artifact leaves it below a usable length, the artifact is **withheld**
  (its text is emptied) and the kit is marked `fatal`.
- **Bounded.** Exactly one repair pass, then re-verify. There is no unbounded
  regeneration loop.

The safest product behavior wins over ATS keyword gain. Style-only defects
(cliché wording) are handled earlier and separately by the deterministic style
softener; they are not fabrications and never gate delivery.

## Consequences

- Detected fabrications become *absent* fabrications; a rejected artifact is
  withheld rather than shipped dirty, and the trace records the disposition.
- Precision matters less than removal: a false positive costs a (truthful) piece
  of wording; a false negative would ship a fabrication. Extractors are tuned to
  be confident, and removal is the backstop.
- Known limitation: sentence-level removal can drop a supported claim that shares
  a sentence with an unsupported one. This is an accepted safety trade-off; the
  adversarial suite documents the boundary.
