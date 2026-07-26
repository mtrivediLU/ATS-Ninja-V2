# ADR-0022: Tailoring Engine v2 — evidence-grounded iterative optimization

Status: Accepted
Date: 2026-07-26

## Context

The v5 match report made before/after keyword match visible, but the original
tailoring path could neither improve it reliably nor guarantee that the generated
resume preserved the candidate's facts. A production failing case exposed eleven
connected causes:

| Root cause | Failure mode | v2 response |
| --- | --- | --- |
| RC1 | Generic JD unigrams became required keywords. | Phrase-first, section-aware requirement extraction rejects generic unigram heads. |
| RC2 | JD parsing was seeded from the candidate profile, so a resume's `C` became a job requirement. | Requirements are derived from the JD alone; terms of two characters or fewer are structurally inadmissible. |
| RC3 | Important multi-word requirements were absent from unigram extraction. | A canonical vocabulary and longest-match phrase scan cover BI, data, geospatial, security, platform, and related terms. |
| RC4 | The score used original-only evidence, generation could not surface supported terms, and two scorers disagreed. | One v2 scorer drives optimization and the match report; provenance-scoped placements can surface supported JD terminology. |
| RC5 | Variant spelling, aliases, and certification implications did not resolve. | Canonical normalization and a conservative certification implication map feed the resolver. |
| RC6 | Wrapped lines could become employers or titles. | Extraction joins layout wraps, resume parsing applies structure/plausibility checks, and suspicious extraction is surfaced. |
| RC7 | Style repair weakened candidate-authored bullet wording. | Candidate bullets are source content; style repair applies only to generated prose. |
| RC8 | Bullet validation blocked inventions but allowed fact deletion. | Fidelity checks are bidirectional for metrics, team facts, entities, and terminal clauses. |
| RC9 | JD title/company heuristics selected product names or a placeholder role. | Standalone role/dept lines and organization patterns take precedence; vocabulary terms cannot win the last-resort company heuristic. |
| RC10 | Skill groups flattened and parser fragments became skills or priorities. | Source taxonomy is retained, categories are expanded, and priorities require a category or meaningful phrase. |
| RC11 | Locations, credential IDs, and terminal bullet text disappeared during rendering. | The contract/renderers model those fields and raw-source fidelity is a delivery gate. |

These were not isolated quality issues. A noise-dominated requirement model,
an original-only scoring gate, and unsafe source rewriting made an unchanged or
worse score the expected deterministic outcome. Fixing them requires a single
evidence and scoring path, rather than independent keyword, generation, and
validation patches.

## Decision

Introduce Tailoring Engine v2 as the default deterministic path. It creates a
typed evidence trail from the job description to a bounded placement action,
then accepts only score-improving actions that preserve source facts and pass
anti-stuffing and grounding gates.

### Pipeline and ownership

```
candidate document
  → extraction / source-preserving Profile
job description
  → phrase-first RequirementTerm[]
  → EvidenceLink[] resolver
  → PlacementAction[] planner
  → optimize (score → validate → bisect)
  → render + grounding + final validation
  → ats_v2 MatchReport + OptimizationTrace
```

- `parsing.vocab` owns canonical terms, aliases, categories, and conservative
  certification implications.
- `parsing.jd_requirements` owns JD-only, section-aware requirement extraction.
  It records the original JD surface and evidence line in `RequirementTerm`.
- `evidence.resolver` owns the normalized, structured-source match ladder and
  returns one `EvidenceLink` per requirement.
- `generation.integration_planner` owns only bounded placement proposals;
  `generation.optimizer` owns deterministic accept/reject decisions.
- `validation.fidelity` and `validation.stuffing` own preservation and
  anti-stuffing rules. They supplement, not replace, claim grounding and the
  existing structural validators.
- `scoring.ats_v2` owns the authoritative score. Legacy public functions in
  `scoring.ats` remain wrappers for callers that have not migrated.

No API, web, or LLM provider owns any part of requirement extraction, evidence
resolution, scoring, or fact validation.

### Typed provenance contracts

`RequirementTerm` records a canonical term, JD surface, aliases, kind, section,
weight, n-gram size, category, and JD evidence line. `EvidenceLink` records the
exact candidate source span/location, match tier/type, permitted surface form,
and maximum placement. `PlacementAction` records the target, operation, exact
proposed text, and source provenance. These objects are carried on the resume
plan rather than reconstructed from rendered prose.

The resolver's ordered ladder is:

1. experience bullet (tier A);
2. source summary (tier B);
3. source skill taxonomy (tier C);
4. curated certification implication (`cert`);
5. adjacency/transfer; or
6. `missing`.

Only A/B/C/cert/variant evidence can authorize the JD surface in a resume.
Adjacency is useful for an honest gap explanation but never authorizes the bare
requirement; a missing requirement is never placed.

### Deterministic iterative optimization

The optimizer begins from a source-content plan, so a failed optimization cannot
fall back to a lossy rewrite. It scores the original source, sorts
evidence-backed actions by weight, and tests bounded batches. Each candidate
render must pass fidelity, anti-stuffing, and grounding/structural validation.
On a failed batch the optimizer bisects down to an individually safe subset. A
batch is accepted only when its score strictly improves. It stops after a small,
bounded number of iterations or a score plateau, and returns the source-content
plan if the final result would regress.

`OptimizationTrace` is additive MatchReport data: iterations, score path,
accepted action labels, rejected action/reason pairs, and missing-tier
requirements that were truthfully unreachable. It is observability, not a
second source of candidate facts.

### One authoritative score

`score_resume_v2` uses weighted boolean requirement credit. Credit requires both
phrase presence and a source-backed A/B/C/cert/variant link. In a tailored
resume, a phrase absent from the source also requires an accepted placement
action with matching provenance. Thus copying a JD into unstructured resume
text cannot create evidence or increase score.

Frequency never creates more base credit. The scorer applies a capped density
penalty for excessive repetition and a small capped bonus when a supported term
appears in both skills and a bullet. The optimizer, match report, and job-fit
generation use this scorer; the older `scoring.ats` interface is explicitly a
compatibility/deprecation boundary, not a competing algorithm.

### Fact preservation and safety gates

Raw candidate source is the authority for fidelity. Before delivery, the resume
must retain source-supported employers, titles, date ranges, locations,
education, certification lines and credential IDs, metrics, team-size facts,
material named entities, and bullet terminal clauses. A parser plausibility
failure raises a content-safe `EXTRACTION_SUSPECT` before planning. The API
records a failed job without persisting the candidate-derived parser diagnostic,
rather than silently accepting or generating from corrupt structure.

The anti-stuffing gate caps requirement frequency, targeted density, summary and
bullet placements, skills additions, and repeated bigrams. Existing claim
grounding remains mandatory: a model may improve prose but cannot create a
candidate fact. Any fatal fidelity, stuffing, extraction, grounding, or
structural failure withholds the unsafe artifact; extraction failure aborts
generation before an artifact exists.

### Contract, rollout, and compatibility

The additive MatchReport fields are `score_basis="ats_v2"` and
`optimization_trace`. The ApplicationKit schema advances from v5 to v6; the
serialization boundary keeps v1–v5 kits readable with safe defaults. API and
web response types expose the new fields additively.

`ENGINE_TAILORING_V2` defaults to enabled. Setting it to `0`, `false`, `no`, or
`off` retains the legacy parsing/scoring path for a controlled rollback or old
caller investigation. It is not a way to bypass grounding or other delivery
gates.

## Invariants

1. **Never fabricate.** Only source-backed A/B/C/cert/variant links may surface
   a JD term. Missing and adjacency-only evidence cannot become candidate claims.
2. **Never lose source facts.** Candidate-authored bullets and structured source
   data are preserved; raw-source fidelity blocks rendered fact loss.
3. **Tailored score is monotone.** For the v2 path, the final tailored score must
   be greater than or equal to the original score. The orchestrator asserts this
   after final rendering and grounding.
4. **One score definition.** The displayed match score, optimizer objective, and
   job-fit keyword score use `ats_v2`; wrappers may adapt it but may not redefine
   it.
5. **No score through stuffing or JD append.** Credit is boolean, provenance is
   required, and frequency/density controls are enforced.
6. **Deterministic without an LLM.** `use_llm=False` runs the full extraction,
   resolution, optimization, validation, rendering, and scoring path with stable
   results.

## Consequences

- The system can make a truthful score improvement when the candidate's existing
  evidence supports a JD spelling, alias, or conservative certification
  implication; it leaves genuinely unsupported requirements visible as gaps.
- Match-report diagnostics become explainable: a user can distinguish a missing
  requirement from one intentionally not placed because it lacked evidence or
  failed a safety gate.
- Fidelity is stricter than parsed-profile completeness. A corrupted parser
  output can no longer validate itself by becoming the only comparison baseline.
- The engine carries more typed provenance and performs bounded extra scoring/
  validation work, but it remains pure Python and independently runnable with
  no provider.
- Existing persisted kits, legacy public scoring callers, and the temporary
  feature-flagged v1 path remain compatible; new kits use the v6 contract.

## Alternatives considered

- **Tune the old unigram list.** Rejected: a larger blacklist cannot make
  candidate-seeded, unigram-only extraction reliable for multi-word tools.
- **Let the LLM choose or verify keywords.** Rejected: it would make evidence,
  score, and safety behavior non-deterministic and cannot be the source of a
  candidate fact.
- **Score raw keyword frequency only.** Rejected: it rewards copying or
  repeating the JD instead of truthful relevance.
- **Rewrite all bullets for stronger prose.** Rejected: arbitrary paraphrase is
  the mechanism that lost metrics and terminal clauses. Source bullets are
  retained unless a separately evidenced, validated change is explicitly made.
- **Keep multiple specialized scorers.** Rejected: a generator cannot optimize
  honestly when the UI, job-fit artifact, and internal loop measure different
  things.
