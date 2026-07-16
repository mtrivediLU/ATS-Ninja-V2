# ADR-0014 — ApplicationKit v2 grounded JobFitArtifact

- Status: Accepted
- Date: 2026-07-15
- Phase: 2B1
- Related: ADR-0007, ADR-0008, ADR-0009, ADR-0011, ADR-0012

## Context

ApplicationKit v1 expresses grounded resume, cover-letter, and answer artifacts
but not the product's existing deterministic fit intelligence. The engine
already owns an evidence matrix, gap ladder, ATS keyword score, and calibrated
interview probability. Job-fit must expose these usefully without allowing a
provider to recalculate scores, upgrade evidence, or hide must-have gaps.

## Decision

Newly generated kits use `application-kit/v2` and may contain a typed
`JobFitArtifact`. Generation is default-on through `include_job_fit: bool = true`;
the option is stored as an additive non-null `kits.include_job_fit` column so a
worker retry reproduces the submitted behavior. The artifact continues to use
the existing JSON result column.

The authoritative requirement list is the existing evidence matrix. Its tiers
map to public classifications: A/B → proven, adjacency → adjacent, C → working
knowledge, and missing → genuine gap. Required requirements are must-haves.
Every assessment carries bounded candidate evidence, a deterministic
explanation, risk, and permitted positioning.

The user-facing view drops only redundant phrase fragments (for example
`power` when `power bi` is present) and generic standalone parser qualifiers
such as `experience` or `proficiency`. The underlying evidence matrix is not
mutated; this prevents a scoring token from masquerading as a meaningful job
requirement.

The fit band is based on a transparent requirement-coverage index, not a new
probability. Required items have weight 2 and preferred items weight 1. Fixed
coverage credits are A=100, B=80, adjacency=55, C=35, missing=0. The weighted
mean maps through one typed policy: low below 50, partial from 50, competitive
from 70, and strong from 85. The existing literal ATS keyword score and
calibrated interview probability remain separately labelled.

A provider may rewrite only the bounded summary. Its prompt contains the score,
band, classifications, bounded evidence excerpts, and allowed positioning—not
the full resume or JD. Output passes candidate-claim grounding and explicit
JobFit consistency invariants. A contradiction triggers one deterministic
repair to the authoritative narrative and remains visible in validation; an
unrepairable final contradiction withholds the narrative.

Serialization reads v2 directly, reads v1 with `job_fit=null`, adapts Phase 1
legacy results with `job_fit=null`, and preserves the existing explicit unknown
schema response. No stored result is silently reinterpreted.

## Consequences

- Provider absence still produces a complete useful assessment.
- Genuine, working-knowledge, adjacent, and must-have gaps remain explicit.
- Providers cannot alter classifications or user-facing deterministic values.
- Schema evolution is additive at the JSON boundary; only reproducible request
  state requires a relational migration.
- Interview preparation and outreach remain out of scope.
