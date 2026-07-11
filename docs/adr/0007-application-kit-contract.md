# ADR-0007 — Versioned ApplicationKit contract

- Status: Accepted
- Date: 2026-07-11

## Context

Through Phase 1, a completed kit's result was a flat, unversioned bag of strings
(`resume_text`, `cover_letter_text`, `answers_text`, `validation_errors`, ...).
That shape cannot express *why* a claim was allowed, cannot distinguish a
repaired artifact from a clean one, and — having no schema version — cannot
evolve without ambiguity. Phase 2A needs an explicit, persistable, evolvable
domain contract for what the engine produces.

## Decision

Introduce **`ApplicationKit`**, a versioned public engine contract
(`ats_engine.kit.contract`) with:

- an explicit, human-readable **`schema_version` = `application-kit/v1`** (not an
  opaque integer), plus `engine_version` and `orchestration_version`;
- **typed artifacts** (`ResumeArtifact`, `CoverLetterArtifact`, `AnswerArtifact`)
  rather than loose strings — each carries its text, LaTeX where generated, a
  per-artifact `ArtifactValidation`, and its claim trace;
- application answers modelled as structured `(question, answer)` items (the
  engine's real behavior), not an invented questionnaire;
- a kit-wide `ValidationSummary` and a persistence-safe `GenerationMetadata`;
- only the artifact categories the engine really produces today (resume, cover
  letter, answers). Job-fit analysis, interview prep, and LinkedIn outreach are
  **Phase 2B** and are deliberately absent.

The contract is plain dataclasses of primitives/enums, JSON-serializable through
a single boundary (see ADR-0012), and never exposes private engine
implementation objects to callers.

## Consequences

- New completed kits are self-describing and forward-evolvable; a stored kit
  always declares the contract it was written under.
- The API mirrors this contract as its response shape (typed Pydantic models),
  so OpenAPI is accurate and no ORM/engine internals leak.
- A migration path is required for kits persisted under the old shape — handled
  in ADR-0012, with no database migration required (the result stays a JSON
  column).
- Adding a Phase 2B artifact type is an additive schema change (a new optional
  field), not a breaking one.
