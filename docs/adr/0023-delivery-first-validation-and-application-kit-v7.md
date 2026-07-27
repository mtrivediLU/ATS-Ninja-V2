# ADR-0023: Delivery-first validation and ApplicationKit v7

Status: Accepted
Date: 2026-07-26
Related: [ADR-0009](0009-validation-wrapped-generation.md),
[ADR-0011](0011-repair-vs-rejection-policy.md),
[ADR-0012](0012-result-schema-evolution.md),
[ADR-0019](0019-application-kit-v5-match-report-and-change-ledger.md), and
[ADR-0022](0022-tailoring-engine-v2-evidence-grounded-iterative-optimization.md)

## Context

Tailoring Engine v2 introduced the right high-level shape: JD-only
requirements, source-backed evidence links, bounded placement actions, one
authoritative scorer, and iterative validation with rollback. A production
resume nevertheless became permanently undeliverable because one raw-fidelity
detector discarded punctuation while extracting a named entity but preserved
that punctuation during containment. A source line shaped like
`TitleCase - TitleCase` could therefore fail validation against its own
unchanged identity projection.

Every optimizer fallback and the final delivery check used that same
uncalibrated gate. There was no demonstrably safe floor, every fidelity string
was treated as fatal, the tailored score became absent, and the API still
persisted `completed` because the engine had returned normally. Independent JD
parsing defects also allowed application instructions, HR contacts, and a
job-title-plus-verb phrase to contaminate requirements and target-company
metadata.

The corrective design must retain all existing anti-fabrication,
anti-stuffing, fidelity, deterministic, and ATS v2 scoring invariants. It must
not make a false-positive detector harmless by broadly suppressing other real
fact-loss findings.

## Decision

### Structured findings and exact identity calibration

Validation gates return `ValidationFinding` values with a stable detector
`code`, `severity` (`fatal`, `degrade`, or `warn`), `fact`, `source_span`,
human-readable `detail`, and `detector_version`. Extraction and containment
share one fact canonicalizer, and named-entity extraction treats punctuation as
a boundary instead of joining title-cased tokens across it. Raw-bullet fidelity
is scoped to experience bullets; separately modelled identity, education,
certification, metric, technology, and remaining-section facts retain their
own checks.

Before optimization, the engine renders the source-preserving identity plan and
runs the same fidelity gate used for candidates. A false positive observed
without a content change may be calibrated only by the exact tuple:

```
(detector_version, code, normalized_fact, source_span)
```

There are no code-only, fact-only, substring, or fuzzy calibration paths. An
exact match is reclassified as `CAL_FALSE_POSITIVE`/`warn`; its original code
is retained for audit. The detector must still be corrected when its logic is
self-inconsistent. Calibration is a secondary run-local safety net, not a
substitute for detector correctness.

The full calibration profile stays in memory because its source spans and fact
identities may contain candidate data. Only calibrated detector codes are
copied to `calibration_suppressed` and the optimization trace. A delivery report
may persist its structured findings inside the same protected result JSON as
the generated application kit; application logs expose only codes and counts,
never fact text or source spans. Removing a genuine employer, title, date,
metric, certification, technology, or responsibility creates a different
finding identity and remains fatal.

### One gate context and a guaranteed delivery floor

The source-preserving resume plan is the delivery floor. The engine builds one
`ResumeGateContext` from its identity projection and reuses that exact context
through action evaluation, batch bisection, rollback, and final validation.
There is no second uncalibrated final gate.

Candidate actions are independently or recursively evaluated so one unsafe
proposal does not discard safe siblings. Evidence-backed score actions must
preserve the authoritative ATS v2 score; headline, summary, and individually
mapped provider bullet proposals may be accepted at score parity when they
pass the same fidelity, grounding, anti-stuffing, structure, and quality gates.
Malformed, timed-out, unavailable, or unsupported provider output falls back
for that item only.

Both the submitted resume and the delivered resume are scored with
`score_resume_v2`. A source-preserving fallback is a delivered resume, so its
delivered score is present and may equal the original score. The final
delivered score cannot be lower than the original. `OptimizationTrace` records
accepted/rejected actions, score steps, delivery state, calibrated detector
codes, and an honest fallback reason.

### Document states and kit states are separate

An individual artifact has exactly one of these states:

| Document state | Meaning |
| --- | --- |
| `generated` | The requested artifact was generated and passed its gates. |
| `generated_with_fallback` | A validated source-preserving or repaired artifact was delivered. |
| `needs_input_review` | Generation cannot safely continue until the input is reviewed. |
| `failed` | The requested artifact could not be safely delivered. |
| `not_requested` | The artifact was not selected. |

`partially_completed` is deliberately not a document state. It is one of the
four kit roll-up states: `completed`, `partially_completed`,
`needs_input_review`, and `failed`.

A requested resume and requested cover letter are delivery-critical primary
documents. A kit is `completed` only when every requested primary document is
delivered (`generated` or `generated_with_fallback`) and every requested
secondary artifact is also delivered. A failed secondary artifact produces
`partially_completed` without removing successful primary documents. If one
primary is delivered and another fails, the kit is `partially_completed`; if
no requested primary can be delivered, it is `failed`, except that a primary
requiring source review rolls up to `needs_input_review`.

The web renders the engine-authored state rather than inferring success from
artifact presence. A fallback is labelled as a delivered resume match and shows
its reason; partial kits keep successful siblings usable; input-review and
failed documents show recovery guidance. Low-confidence JD target metadata is
presented for confirmation rather than asserted as certain.

### ApplicationKit v7 and API lifecycle

New kits use `application-kit/v7` and
`grounded-orchestration/v7`. The additive contract fields are:

- top-level `state`, `target_role`, `target_company`, and
  `target_confidence`;
- one `delivery_reports` entry for every artifact kind, including explicit
  `not_requested` entries;
- structured validation findings and an optional, user-readable
  `fallback_reason`; and
- delivery state, fallback reason, and calibrated detector codes on the
  optimization trace.

Target metadata comes only from the JD and never becomes candidate history.
The original artifact validation and claim/evidence contracts remain present;
the delivery report describes whether an artifact reached the user rather than
replacing truth grounding.

The API maps the engine kit roll-up directly into persisted lifecycle status.
`KitStatus` therefore adds the terminal values `partially_completed` and
`needs_input_review` alongside `pending`, `processing`, `completed`, and
`failed`. Migration `0007_delivery_statuses` widens the portable string column
from 20 to 32 characters on PostgreSQL and SQLite; it does not rewrite
historical rows or introduce a PostgreSQL-only enum.

This is an additive response change on the existing `/api/v1` surface, not a
negotiated compatibility header. Clients must tolerate newly added enum values
and treat both new values as terminal. Change actions and exports may operate
on `completed` or `partially_completed` kits, but export resolution also checks
that the selected document's delivery report says it was delivered.
`needs_input_review` is a terminal review state but may retain an independently
delivered sibling. Selected-artifact delivery reports authorize exports and
change actions; `failed` has no delivered artifact authorization.

### JD hygiene, target identity, and conservative bridges

Requirement extraction stops before application instructions, compensation,
eligibility, EEO/accommodation, contact, and similar posting tails. Contact
lines, person/HR names, and organization self-description remain available as
target context where useful but do not enter the score denominator. LLM-enriched
JD fields must pass the same deterministic hygiene rules as heuristic fields.

Target title/company resolution prefers explicit labels and organization
headings, then constrained repeated-name or email-domain evidence. A company
candidate that begins with the parsed role, contains a role noun followed by a
lowercase verb, or ends in a conjunction/preposition is rejected. Target
confidence is returned so the UI can request confirmation instead of asserting
a weak guess. Target facts may personalize an application but can never become
candidate employment history.

Resolver aliases and morphological bridges are curated and conservative.
Version control requires explicit Git-family evidence; data ingestion requires
an experience span with an ingest variant; a multi-source pipeline requires
ETL/ELT plus distinct source systems in evidenced context; certification child
terms inherit only from an approved implication. Every bridge is labelled
`bridged` and carries evidence spans. Adjacency and missing terms remain
unauthorized for candidate-facing claims.

### Recruiter-readable structured prose and exports

For the delivery-first resume quality stage, the optional provider receives only
the target role/company, prioritized JD requirements, exact source evidence for
the item, allowed terminology, protected facts, and bounded style/length
instructions. It returns structured headline, summary, and eligible-bullet
proposals mapped to source spans and placement actions. For a headline, the
model may only select and reorder up to three exact, resolver-credited
tool/methodology terms; it cannot change the candidate's role identity, coin a
synonym, or add seniority/scope. Any invalid proposal returns the deterministic
role-aligned headline. Headline, summary, and each eligible bullet are
independently validated, and every delivered summary crosses the final
truth-grounding gate. Provider prose is never an evidence source.

Deterministic quality checks reject duplicated/truncated content, disguised
keyword lists, orphaned identity lines, generic filler, and unsafe punctuation
without turning subjective style preferences into broad fatal gates. Generated
resume and cover-letter prose contains no em dash. PDF and DOCX exports consume
the already-validated structured document, use single-column ATS-readable
layouts, and must preserve the same protected facts as the delivered text.

### Persisted-result compatibility

The JSON serialization boundary recognizes ApplicationKit v1 through v7 plus
the known unversioned Phase 1 shape:

- v1-v6 records keep their original `schema_version` and content. On read, the
  normalizer adds target defaults and infers delivery reports and kit state
  from the artifacts and their historical validation flags. It does not
  rewrite the stored row in place.
- Phase 1 records are adapted under the explicit `phase-1/legacy` marker with
  an empty claim trace and a provenance warning, then receive the same inferred
  delivery projection.
- Unknown schemas are returned under the explicit `unknown` marker with no
  invented artifacts.

This inference intentionally corrects the view of an old record whose transport
status said `completed` while its requested primary artifact was rejected. It
does so through `result.state` and inferred reports; it does not rewrite the
historical row's separate lifecycle `status`. Old clients that inspect only
that transport field retain the historical limitation. The projection does not
pretend that an old kit ran v7 calibration or had v7 diagnostics.

### Rollout and rollback

`ENGINE_DELIVERY_FIRST` defaults to enabled. Values `0`, `false`, `no`, and
`off` select the retained PR-21 score-only optimizer after the API and worker
processes are restarted. That compatibility path skips both construction of
the per-run identity-calibration profile and the delivery-first headline,
summary, and per-bullet quality stage. Compose passes the same setting to both
services.

This switch is a one-release behavioral rollback to PR-21 optimization. It
does not undo punctuation/canonicalization fixes, bypass grounding, or revert
the additive ApplicationKit v7/API state contracts and migration; those safety
and storage changes cannot be toggled per request. `ENGINE_TAILORING_V2`
remains the separate switch for disabling the tailoring/scoring path entirely.
A rollback must be recorded with the affected kit IDs and finding codes; it is
not a permanent alternative validation policy.

## Invariants

1. Candidate evidence remains the only authority for candidate-specific facts.
2. An exact identity calibration cannot suppress a finding with a different
   detector version, code, normalized fact, or source span.
3. Genuine source-fact deletion and fabricated claims remain delivery-blocking.
4. A readable source whose identity projection passes has a validated resume
   delivery floor.
5. The delivered ATS v2 score is present for a delivered resume and is greater
   than or equal to the original score.
6. One unsafe provider item cannot invalidate independently safe items.
7. `completed` means every requested primary document was delivered.
8. Logs and client-safe errors contain finding codes/counts or exception types,
   never resume/JD/generated content.

## Consequences

- A validator defect cannot silently turn an otherwise readable resume into an
  empty "completed" kit.
- Fallback is visible and accurately labelled rather than hidden as successful
  tailoring; unchanged fallback scores are still meaningful.
- The contract and UI can preserve delivered siblings while explaining partial
  or input-review outcomes.
- Calibration and repeated gate execution add bounded deterministic work and
  diagnostic data, but no provider dependency.
- Strict API clients that exhaustively enumerate lifecycle strings must update
  for the two additive terminal values.

## Honest limitations

- `ENGINE_DELIVERY_FIRST=0` restores the PR-21 score-only generation policy,
  but intentionally cannot roll back the additive v7 wire contract or database
  migration at runtime.
- Calibration protects only detector failures reproduced by the unchanged
  identity projection. It does not certify that every future validator is
  correct, so suppression-code rates still need operational monitoring.
- ATS v2 scores are deterministic evidence/keyword estimates, not predictions
  of an employer decision.
- OCR and image-only resume extraction remain unsupported.
- Private production inputs are never committed. When an exact job posting is
  unavailable, a sanitized structurally equivalent regression fixture verifies
  the failure mechanism but cannot establish byte-for-byte behavior for that
  unavailable posting.
- Compatibility reads infer honest delivery inside `result`, but they do not
  backfill the separate lifecycle status of historical database rows.

## Alternatives considered

- **Treat all fidelity findings as warnings.** Rejected because genuine fact
  deletion would reach delivered documents.
- **Suppress a detector code or fact globally after one false positive.**
  Rejected because it can hide unrelated loss with the same broad signature.
- **Skip final validation after the optimizer.** Rejected because grounding and
  rendering can still introduce or expose a defect; the final pass must instead
  reuse the same calibrated context.
- **Return `completed` whenever the engine does not raise.** Rejected because
  process success and artifact delivery are different facts.
- **Inflate or omit a fallback score.** Rejected because the source-preserving
  document can and must be measured by the same authoritative scorer.
