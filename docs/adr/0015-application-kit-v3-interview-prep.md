# ADR-0015 — ApplicationKit v3 grounded InterviewPrepArtifact

- Status: Accepted
- Date: 2026-07-15
- Phase: 2B2

## Context

Interview preparation needs candidate-specific examples, but free-form answer
or STAR generation can turn a JD keyword into invented history, blend unrelated
roles, or conceal gaps. The existing Profile, evidence matrix, gap ladder,
JobFitArtifact, claim grounder, and JSON result boundary already provide the
authoritative inputs and enforcement model.

## Decision

New kits use `application-kit/v3` and may include a typed
`InterviewPrepArtifact`. `include_interview_prep: bool = true` is persisted in a
portable additive column through migration 0003. It is independent of
`include_job_fit`; interview preparation can consume one internal deterministic
fit calculation without forcing JobFit into the persisted result.

The artifact contains structured focus areas, categorized questions, answer
guides, STAR candidates, study topics, honest gap handling, positioning,
interviewer questions, validation, consistency, generation metadata, claims,
and bounded evidence. Provider-free generation is complete. Providers receive a
bounded structured brief and may improve only strategy wording; deterministic
classifications and content remain authoritative. Candidate grounding and
InterviewPrep consistency run before one bounded fallback pass.

A STAR candidate uses exactly one experience or education bullet. It is
`complete` only when that source explicitly contains Situation, Task, Action,
and Result. Otherwise missing components are named. A result or metric stays on
the same bullet; education never becomes employment; supported/contributed never
becomes led/owned. Gap guidance preserves adjacent, working-knowledge, genuine,
and must-have classifications and never invents current learning.

The artifact remains in the existing PostgreSQL JSON result column. Reads adapt
v2 by adding absent interview preparation, v1 by adding absent JobFit and
interview preparation, and Phase 1 through the existing explicit legacy shape.
Unknown schema versions remain uninterpreted.

## Consequences

- API, worker, and PostgreSQL lifecycle behavior is unchanged except for the
  additive request option and v3 JSON shape.
- Interview preparation is useful offline and reproducible without an LLM.
- Claim/evidence traces and visible repair outcomes make provider attacks
  auditable without permitting fabricated content into deliverable fields.
- LinkedIn outreach, external company research, auth, billing, and UI flows
  remain outside this decision.
