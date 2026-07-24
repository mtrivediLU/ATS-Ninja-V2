# ADR-0020: Change-action revision and irreversibility policy

Status: Accepted
Date: 2026-07-24

## Context

ApplicationKit v5 (ADR-0019) records every material tailoring delta as a typed
`ChangeRecord` in a per-artifact change ledger. Users need to accept or reject
those changes and see the result persisted, without any of it becoming a way to
re-introduce a fabrication that truth grounding removed. The frontend's existing
freeform edits are deliberately local, unpersisted, and marked "not revalidated";
change actions are the first *persisted, revalidated* edit path.

## Decision

### Ledger construction (stable, deterministic, one-record-per-delta)

The ledger is built from two stable sources, never fragile rendered-text diffing:

1. **Instrumented plan decisions** (`ats_engine.models.PlanDecision`), captured
   where the decision happens in planning (summary, targeting clause, bullet
   rewrite, skill surfacing), each with its exact original and tailored text and
   a stable, location-aware id (e.g. `resume::exp0::bullet1`).
2. **Grounding claim records** — every repaired/rejected claim becomes a visible
   `grounding_removal` `ChangeRecord`, linked to the real claim id.

Every material delta maps to exactly one record. Bullet rewrites, the summary,
the targeting clause, and cover-letter paragraphs are reversible; skill surfacing
is recorded for transparency but managed through regeneration, not individual
reversal. `ats_impact_delta` is computed by exact deterministic re-scoring (never
a model estimate) and is described as an *estimated keyword-match* impact, never
an interview impact; frequency does not affect it.

### Irreversibility of grounding removals

A `grounding_removal` record is always `reversible=False`. The change-action
service refuses any reject or restore against it with a 422. The fabricated text
is gone from the delivered artifact and can never be restored by a user or the
API. This is the non-negotiable rule that keeps the change ledger from becoming a
back door around the grounding gate.

### Safe, idempotent change actions

`ats_engine.kit.change_actions.apply_change_actions` is deterministic and
LLM-free. It always rebuilds the delivered artifacts from a stable baseline (the
ledger records' own original/tailored text applied to the persisted structured
document) rather than cumulatively mutating already-mutated text, so a reject
followed by the same reject — or an accept applied twice — never drifts.
Rejecting a rewrite restores the candidate's original text; rejecting an added
unit removes it; restoring re-applies the tailored change. After a batch the
artifacts are re-rendered from the structured document, re-grounded as a safety
net, re-validated for style/naturalness, the tailored keyword-match score and
keyword coverage are recomputed, and the revision is incremented once.

### Optimistic concurrency and lineage

The authoritative revision is the `kits.revision` column (migration 0006). A
change-action batch carries `expected_revision`; a mismatch returns 409 so two
browser tabs cannot silently overwrite each other. `kits.parent_kit_id` (also
migration 0006) links a regenerated kit to its source. Regeneration creates a new
pending kit from the source's stored inputs and selection, starts at revision 0,
and never modifies the source. Deletion is a hard delete of the local row and
never logs candidate content. PDF export always renders the current persisted
revision.

## Consequences

- The change ledger is fully transparent and reversible for ordinary tailoring,
  yet truth-grounding removals stay permanent.
- No LLM is called for a change action; the operation is cheap and reproducible.
- The persisted structured document (`ResumeDocument`/`CoverLetterDocument`) is
  the reversible state; no opaque Python object is ever serialized.

## Corrections and hardening (PR #19 review)

### Whole-document change impact

Per-change ATS impact is computed **counterfactually against the complete
document** — `score(document with the change) - score(document without it)` —
not by scoring an isolated snippet. A keyword that already appears elsewhere
contributes zero impact, and a grounding removal is honestly non-positive
(removing a fabrication never raises the real keyword match).

### Stable-baseline reconstruction

Reject/restore is drift-free because the delivered artifact is rebuilt from the
immutable ledger records, never by mutating already-mutated document state. The
cover-letter body is reconstructed from the index-ordered paragraph records
(dropping only rejected ones), so a reject followed by a restore reproduces
exactly the document that existed before — the earlier destructive filter that
made restore impossible is removed. Bullet records carry the **raw** candidate
wording (captured before style softening) so a rejected bullet restores the
candidate's own words. Reversibility and reason are explicit per record type: a
`grounding_removal` is permanent with a removal-specific reason, while skill
surfacing is transparency-only (managed via regeneration), never mislabelled as a
grounding removal.

### Full revalidation on every batch

After applying a batch the artifact is rebuilt from the current revision: it is
re-grounded per unit (refreshing the ClaimRecord/evidence trace from scratch, so
no revision-zero claims survive), re-rendered to both plain text and LaTeX, and
revalidated (grounding + style + naturalness + LaTeX + JD-append). If the rebuilt
artifact would be fatally invalid or ungrounded the batch is refused atomically —
statuses roll back, nothing is persisted, and the revision does not advance.

### Atomic revision concurrency

The revision is advanced by a single conditional UPDATE guarded on
`revision = expected_revision`, with the affected-row count verified to be
exactly one. Two simultaneous requests for the same revision can no longer both
succeed: the loser's UPDATE affects zero rows and returns 409, never overwriting
the winner. A PostgreSQL-gated concurrency test proves exactly one of two
concurrent requests wins.

## Second review: full validation, true atomicity, and adjacent hardening

### Authoritative post-action validation

Every batch is revalidated to the *same* standards as initial generation, so a
change action can never persist an unusable artifact. The resume rebuild runs
LaTeX + whole-JD-append + **completeness** as fatal gates and style + the
authoritative anti-stuffing / JD-echo gate as warnings. The cover-letter rebuild
runs LaTeX plus a **minimum-usable** gate (no body paragraphs, or a body below a
usable word floor) as fatal, with the ideal word-count band, anti-stuffing, and
style as warnings. This is why rejecting most or all cover-letter paragraphs —
which previously produced a "valid" 22-word letter — is now refused. Initial
generation still treats the ideal 280-320 band as a soft warning; only a
change action that would leave the letter *degenerate* is refused, so a
legitimately short letter is never blocked.

### True atomicity (build-then-swap, never mutate-then-rollback)

The proposed revision is built on a **deep copy** of the kit. Only a fully valid
revision is returned; on any failure the caller's kit is returned byte-for-byte
unchanged — documents, claims, ledger statuses, rendered text, LaTeX, match
report, revision, and validation. The earlier design mutated the artifact in
place and rolled back only ledger statuses on failure, so a refused batch could
leave the artifact text emptied. Build-then-swap removes that whole class of
partial-mutation bug.

### Claim-link reconciliation

After the rebuild re-grounds each unit from scratch (fresh ClaimRecord ids), every
ledger record's `linked_claim_ids` is reconciled against the new claim set: any id
that no longer exists is dropped. No `linked_claim_id` can dangle, and no stale
revision-zero link survives an action. A grounding-removal record keeps its
permanent-removal reason and text even when its historical link is cleared — the
removed content stays gone regardless.

### Adjacent hardening

- **Empty batch is a no-op.** It never advances the revision or rebuilds; the kit
  is returned unchanged.
- **Duplicate change id in one batch is refused (422).** Two actions targeting the
  same change are ambiguous, so the batch is rejected rather than letting the last
  action silently win.
- **CI aligns on Node 24.** The web test runner uses
  `node --experimental-strip-types`, unsupported on the Node 20 the workflow
  previously pinned; the workflow, root `engines`, and the web package now require
  Node 24.

## Deviations from the Fable proposal

- Reversible bullet mapping comes from planning-time instrumentation
  (`PlanDecision`) rather than post-hoc diffing, which the proposal preferred; a
  full collector threaded through every planning function was avoided because it
  would change nothing behaviorally while adding regression risk, and the
  instrumented decisions already give exact original↔tailored pairs.
- After a change action the resume plain text is deterministically re-rendered
  from the structured document; content is identical, though minor formatting
  normalization can differ from the initial plan-based render.
