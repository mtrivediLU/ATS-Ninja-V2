# ADR-0016 — ApplicationKit v4 grounded LinkedInOutreachArtifact

- Status: Accepted
- Date: 2026-07-16
- Phase: 2B3

## Context

Useful outreach needs candidate relevance, target context, and sometimes
recipient or relationship personalization. Those sources have different trust
privileges. Treating a JD company, recipient title, free-form note, or proposed
referral as candidate evidence would create fabricated history. Free-form model
generation can also invent meetings, applications, links, company facts, or
complete alignment and can remove honesty qualifiers to satisfy a length limit.

## Decision

New kits use `application-kit/v4` and may contain a typed
`LinkedInOutreachArtifact`. `include_linkedin_outreach: bool = true` and an
optional bounded typed `outreach_context` are persisted by migration 0004. The
artifact remains in the existing JSON result column and is independently
selectable from JobFit and InterviewPrep.

The engine explicitly separates candidate evidence, JD target context,
recipient context, and relationship/action context. Candidate claims pass the
existing grounding gate. Target facts may express interest but never employment
history. Recipient, application, referral, meeting, conversation, mutual
connection, affiliation, and link claims require the corresponding explicit
request field. Free-form personalization notes are not candidate or relationship
evidence.

Deterministic generation produces recruiter and hiring-manager connection notes,
direct messages, employee informational outreach, and context-authorized
follow-up, referral, or shared-affiliation drafts. Central product policies set
format-specific character limits; they are not representations of current
LinkedIn limits. Validation checks normalized character counts, complete
sentences, honesty qualifiers, one call to action, fit consistency, tone,
candidate grounding, target consistency, and relationship/action support.

A provider receives only a bounded structured brief and may rewrite the strategy
summary, not draft facts or structure. One deterministic fallback pass replaces
contradictory or over-limit prose. New reads accept v4 directly, adapt v3 with
absent outreach, preserve the existing v2/v1/Phase 1 adapters, and leave unknown
schemas uninterpreted.

The artifact contains drafts only. It does not access LinkedIn, discover
contacts, scrape profiles, automate a browser, send messages, or record that an
outreach action occurred.

## Consequences

- Provider absence still yields complete, useful, concise outreach.
- Personalization is reproducible and auditable without evidence-class
  privilege escalation.
- Genuine fit gaps need not be listed in a short message, but no draft may
  contradict them with a complete-alignment claim.
- API, worker, queue, and PostgreSQL lifecycle behavior remains unchanged beyond
  additive request state and the v4 JSON result.
