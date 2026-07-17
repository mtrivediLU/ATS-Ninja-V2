# ADR-0017: Persist independent artifact selection

Status: Accepted
Date: 2026-07-16

## Context

The original `requested_mode` string resolves the primary outputs through a
legacy `Mode` enum. It can request resume with cover letter or resume with
application answers, but cannot represent all primary artifacts—or every
independent combination—without ambiguous strings. D1 requires six independent
controls whose explicit false values survive asynchronous worker processing.

## Decision

Add optional `include_resume`, `include_cover_letter`, and
`include_application_answers` booleans to `KitCreate`, then persist their
resolved values on the Kit row. The existing `include_job_fit`,
`include_interview_prep`, and `include_linkedin_outreach` flags are unchanged.

When a new primary flag is omitted, the corresponding value is inherited from
the existing `requested_mode` resolution. Existing clients therefore keep their
current behavior. New clients send all three flags explicitly. The engine uses
a typed `ArtifactSelection` and can build an internal resume plan for optional
intelligence artifacts without returning an unrequested resume.

Migration `0005_primary_artifact_selection` backfills existing records using
the legacy detector's precedence. Celery payloads remain Kit-ID-only;
PostgreSQL remains authoritative and Redis remains broker-only.

## Consequences

- All six artifacts can be selected independently and reproduced by the worker.
- Explicit false values are respected.
- `requested_mode` remains accepted for backward compatibility.
- No combinations are encoded into new request strings.
- The API and engine gain small typed-selection surfaces and corresponding
  regression tests.
