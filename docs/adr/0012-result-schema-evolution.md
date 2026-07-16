# ADR-0012 — Result schema evolution and Phase 1 compatibility

- Status: Accepted
- Date: 2026-07-11
- Related: [ADR-0007](0007-application-kit-contract.md), [ADR-0005](0005-async-kit-lifecycle.md)

## Context

Phase 1 already persisted completed kit results as JSON under a flat, unversioned
shape. Phase 2A introduces the versioned ApplicationKit contract. Reading an
existing completed kit must not crash merely because it predates the new
contract, and we must not silently reinterpret an unknown payload as if it were a
known schema. Dropping the database is not an acceptable "migration."

## Decision

**No database migration is required.** The kit `result` column is already a
generic JSON column (portable across PostgreSQL and the SQLite used in tests);
only the *shape* of the JSON changes, not the table. This is documented here so
the absence of an Alembic migration is a deliberate, recorded decision rather
than an oversight.

Compatibility is handled at the serialization boundary
(`ats_engine.kit.serialization.normalize_persisted_result`), which dispatches on
the stored schema:

- a **v1 ApplicationKit** (`schema_version == "application-kit/v1"`) is returned
  as-is;
- a **Phase 1 record** (no `schema_version`, but the known flat fields) is
  **adapted** into the canonical response shape under the explicit marker
  `phase-1/legacy` — mapping the old text/LaTeX and validation errors onto typed
  artifacts, with an empty claim trace (it never had one) and a warning naming
  its provenance;
- anything else is surfaced under `unknown` with a warning and **no fabricated
  artifacts** — it is never reinterpreted as a known schema.

The API's `KitRead.result` runs every persisted result through this normalizer
before Pydantic validation, so a legacy completed kit is served, not crashed.

## Consequences

- Old completed kits keep working through the API with an honest legacy marker;
  new kits carry the full v1 contract.
- The database and its data are untouched; no destructive migration.
- If a genuinely new persisted invariant is ever needed (e.g. a dedicated
  `schema_version` column for indexed queries), that would be a future additive
  Alembic migration — not required now.
