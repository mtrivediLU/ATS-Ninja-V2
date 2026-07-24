# ADR-0019: ApplicationKit v5 match report and change ledger

Status: Accepted
Date: 2026-07-24

## Context

Through v4 the kit exposed a single literal keyword figure
(`JobFitArtifact.ats_keyword_score`, computed against the *original* resume), a
requirement-coverage index, and a four-value `interview_probability` heuristic
that the frontend rendered as a percentage. This was misleading in three ways:

1. There was no *tailored*-resume score, so a user could not see what tailoring
   actually changed. The one number was easy to read as "the tailored resume's
   ATS score".
2. `interview_probability` looked like a probability of being interviewed. It is
   not — it is a coarse deterministic bucket.
3. `compare_scores` / `analyze_keyword_coverage` existed but were never wired
   into the kit, and the internal `AtsQualityReport` was computed and discarded.

The product also needs to explain *why* a tailored document differs from the
submitted one, without weakening truth grounding.

## Decision

Introduce **ApplicationKit v5** (`schema_version = application-kit/v5`,
`orchestration_version = grounded-orchestration/v5`) with a typed
`MatchReport` and a per-artifact transparent change ledger. v4 and earlier
remain readable and are never rewritten in place (ADR-0012 compatibility
strategy extended; see also ADR-0020 for the change-action side).

### Three separate scores, never merged

`ats_engine.scoring.match_report.build_match_report` computes, from already-
grounded pipeline data:

- **Original resume keyword match** — the submitted resume against a unified JD
  keyword vocabulary.
- **Tailored resume keyword match** — the final, grounded resume against the
  same vocabulary. Absent when the resume was not requested or was withheld. It
  may be *lower* than the original when grounding removed unsupported content;
  the kit summary explains this honestly rather than assuming tailoring always
  raises the number.
- **Evidence-based role alignment** — reuses
  `job_fit.policy.requirement_coverage_score`. No competing alignment formula is
  introduced; when a `JobFitArtifact` is present the match report reads its
  authoritative score/band/strengths/gaps so the two never disagree.

### Evidence-gated keyword credit (anti-inflation)

The unified vocabulary (`WeightedKeyword`) is built **only** from the job
description: evidence-matrix required terms (weight 2.0), then preferred terms
(1.0), then remaining `JDProfile.technical_keywords` (1.0), case-insensitively
deduplicated in a stable order. No candidate-derived term is ever added.

A keyword earns credit only when it is present in the measured resume (word-
boundary, so `Java` never matches `JavaScript`) **and** the candidate's parsed
evidence independently supports it at tier A/B/C — the same evidence gate that
resists fabrication. Credit is boolean per keyword, so frequency never helps.
This is why pasting the job description into a resume, repeating a keyword, or
padding prose cannot raise any score: raw appended text is not parsed into
affirmative tier-A/B/C candidate evidence.

### Confidence, fit categories, recommendation, quality payload

- **Score confidence** (`high`/`medium`/`low`) is a deterministic annotation
  (never a delivery gate) from a centralized rubric: real target title present,
  number of required requirements, JD segmentability, resume extraction quality
  and manual-review warnings, contact integrity, and keyword-set size. Complete
  human-readable reasons are persisted.
- **`FitCategory`** (`strong_fit`/`good_fit`/`partial_fit`/`stretch_role`/
  `low_alignment`) sits beside the retained `FitBand`. Thresholds are centralized
  constants. The ordering gates every category on the must-have-gap count
  *before* the alignment-only "partial" rung, so a result with two or more
  must-have gaps is never classified more positively than `stretch_role` even
  when alignment is ≥ 50. Edge cases are locked by tests.
- **Recommendation and kit summary** are deterministic, plain-language, and pass
  the style and naturalness validators. They identify supported strengths and
  real gaps (must-have first), never promise an interview or ATS behavior, never
  say "do not apply", vary filler deterministically by a stable content hash,
  and always carry the disclaimer: *"These are estimates from deterministic
  keyword and evidence analysis, not a prediction of any employer's decision."*
- The internal `AtsQualityReport` is promoted into a bounded, persistable
  `AtsQualityReportPayload` (coverage, target-title presence, section presence,
  contact findings, measurable-result and word counts, duplicate-keyword and
  generic-language warnings). No unbounded resume content is stored.

### Observability and failure handling

Per-stage timings (`StageTimings`, plain integer milliseconds for pipeline,
grounding, rendering, artifacts, scoring) are persisted in the result. If match-
report computation fails, the kit is still delivered with `match_report=None`
and a bounded `"Match scores were unavailable for this run."` warning; only safe
metadata is logged.

## Consequences

- The frontend shows three visually and textually distinct scores plus an honest
  fit category and confidence, and a static "How scoring works" page. The
  `interview_probability` field is preserved for backward compatibility but is
  never rendered as a percentage.
- Everything is deterministic and works with `provider=None` /
  `engine_use_llm=False`; no hosted API or recurring scoring cost is introduced.
- v4 kits keep their schema and are shown through the compatibility boundary
  with a regenerate prompt.

## Corrections and hardening (PR #19 review)

A review found the scoring and placement were not yet delivering an honest,
recruiter-useful result. The following are now implemented and tested.

### Weighted match-score formula

`score_resume` computes a genuinely weighted score, not a count ratio:

    score = 100 * (sum of weights of credited keywords) / (sum of all keyword weights)

Required keywords (weight 2.0) contribute more than preferred/other keywords
(1.0), so matching only the required keyword of a 2+1 pair yields 66.67%, not
50%. Credit is boolean per unique normalized keyword, so repetition never raises
the score, and `Java` never matches `JavaScript` (word-boundary matching).

### Evidence tiers and semantic-transfer boundaries

Keyword credit follows an explicit evidence-to-keyword policy:

1. **Directly supported** (tier A/B/C): the exact term appears with real
   candidate evidence; it earns strict keyword-match credit.
2. **Strongly transferable** (`ats_engine.evidence.transfer`): the candidate's
   evidence demonstrates the capability with different wording (e.g. a developer
   who writes unit/integration tests, reviews code, runs CI/CD, and resolves
   defects, applying to a "unit testing"/"test automation" requirement). A small,
   explicit, reviewable map produces a **truthful umbrella phrase** ("software
   testing and quality practices"), surfaced in the skills section and credited
   toward evidence-based role alignment — but **not** toward strict keyword-match
   for the exact JD term, so no score is inflated by a capability not directly
   shown. Named tools/practices (Selenium, Cypress, JUnit, performance/security
   testing, ...) are `forbidden_specifics` and are **never** produced by transfer;
   they remain honest gaps unless stated directly.
3. **Weak/ambiguous**: not placed automatically; treated as a gap.
4. **Unsupported**: never added and never credited.

Transfer is deterministic and bounded (no free-form inference): it fires only for
listed JD terms when the candidate's own bullets/skills carry an explicit,
word-boundary-matched capability signal.

### Smart placement

JD keyword detection gained testing/quality and general web-development
vocabulary so those requirements reach the evidence matrix at all. Placement
remains deterministic: skills for concise supported skills, summary for a small
number of role-alignment themes, experience for contextual evidence, with the
umbrella phrase used only where transfer permits. Repetition and JD-echo cannot
raise a score; anti-stuffing (`ats_engine.validation.naturalness`) is wired into
generation (bullet safety, duplicate-bullet removal, varied fallback closings).

## Deviations from the Fable proposal

- The match report reuses the existing requirement-coverage policy for alignment
  and reads the JobFit artifact's authoritative numbers rather than recomputing,
  guaranteeing internal consistency.
- Fit-category boundary ordering resolves the proposal's "partial at ≥ 50" vs
  "stretch for 2+ must-have gaps" tension in favor of the safer (less positive)
  classification, documented above and covered by explicit edge tests.
