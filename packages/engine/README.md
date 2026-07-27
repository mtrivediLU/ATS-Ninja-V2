# ats-engine

The ATS-Ninja-V2 career intelligence engine: a pure-Python, framework-independent
package that performs **deterministic-first, truth-grounded** resume and
application-kit generation.

It owns the product's domain logic and has **no dependency on FastAPI, Next.js,
any UI framework, or any LLM vendor SDK**. LLM providers are reached through the
`LLMProvider` interface (`ats_engine.providers`); the only bundled adapter talks
to a local Ollama server over stdlib HTTP.

## Domain modules

| Package | Responsibility |
| --- | --- |
| `ats_engine.models` | Typed domain models (dataclasses) shared across the engine |
| `ats_engine.config` | Framework-independent `EngineSettings` (env-driven) |
| `ats_engine.parsing` | PDF text, contacts, source-preserving resume `Profile`, JD `JDProfile`, phrase-first requirements |
| `ats_engine.evidence` | Source-grounded requirement resolver, gap ladder + adjacency clustering |
| `ats_engine.scoring` | Authoritative v2 ATS scoring, legacy wrappers + coverage analysis |
| `ats_engine.validation` | Structured claim/fidelity/stuffing/style/format/LaTeX/completeness gates, exact calibration + severity |
| `ats_engine.caching` | Content-hash cache (disk-backed, degrades to no-op) |
| `ats_engine.providers` | `LLMProvider` interface + Ollama adapter |
| `ats_engine.generation` | Source-preserving plans, placement planner, optimizer, document generation + pipeline |
| `ats_engine.job_fit` | Deterministic requirement coverage, fit bands, narrative consistency |
| `ats_engine.interview_prep` | Grounded questions, STAR integrity, gap guidance, provider consistency |
| `ats_engine.linkedin_outreach` | Grounded drafts, evidence boundaries, relationship and length validation |
| `ats_engine.kit` | ApplicationKit v7, typed artifacts, delivery reports/state roll-up, grounding, optimization trace, v1-v6 compatibility |

## Core principles

1. **Deterministic-first.** Parsing, evidence extraction, matching, scoring, gap
   classification, validation, and caching are all deterministic. Every pipeline
   step works with no LLM.
2. **LLM output is untrusted.** Provider output is re-validated against the
   candidate's evidence; unsupported metrics or newly-introduced tools are
   rejected in favor of the grounded original.
3. **No fabricated claims.** Extracted employers/bullets are verified against the
   source resume; the claim validator blocks invented employers, metrics, emails,
   and altered titles.

## Tailoring Engine v2 and delivery-first validation

The default tailoring path is a deterministic, provenance-carrying sequence:

```
source extraction → JD requirements → evidence resolver → placement planner
→ identity calibration → delivery-first optimizer → shared final validators
→ ats_v2 scorer → document/kit delivery states
```

- `RequirementTerm` is extracted from the JD alone, phrase-first and
  section-aware. Generic unigrams and candidate-seeded terms are not valid
  requirements.
- `EvidenceLink` resolves each requirement only against structured candidate
  source evidence: experience (A), summary (B), skills (C), conservative
  certification implication (`cert`), adjacency, or missing. Missing and
  adjacency-only links never authorize the bare JD term in a resume.
- `PlacementAction` can surface a supported JD spelling in the summary, skills,
  headline, or a source-appropriate bullet without turning an unsupported gap
  into a claim. Source skill headings and candidate-authored bullet facts are
  preserved.
- The source-preserving plan is first validated as a delivery floor. A single
  run-local gate context is reused through action/batch bisection, rollback, and
  final validation. A quality-only headline/summary/bullet proposal may be
  accepted at score parity; a score-targeting action cannot regress the one
  authoritative `ats_v2` score.
- Validation findings are structured and tiered (`fatal`, `degrade`, `warn`).
  Identity calibration can downgrade only the exact
  `(detector_version, code, normalized_fact, source_span)` that fired against
  an unchanged source projection. It cannot hide a genuine deletion with a
  different fact or span.
- Resume quality-stage headline/summary/bullet proposals are structured and
  validated per item. A headline proposal may only select/reorder exact
  resolver-credited terms around the immutable candidate role, and every
  delivered summary crosses truth grounding. Malformed output, a timeout, an
  unavailable provider, or one unsupported proposal falls back only for that
  item; deterministic generation remains complete. Generated resume and cover
  letter prose contains no em dash.
- The final delivered score is asserted to be no lower than the original and
  remains present for a source-preserving fallback. `MatchReport.optimization_trace`
  records score steps, accepted/rejected actions, delivery state, honest
  fallback reason, calibrated detector codes, and truly unreachable terms.

The path works with `provider=None` / `use_llm=False`. To temporarily retain
the compatibility path while investigating an older caller, set
`ENGINE_TAILORING_V2=0`; this does not bypass grounding or validation. See
[ADR-0022](../../docs/adr/0022-tailoring-engine-v2-evidence-grounded-iterative-optimization.md)
for the full decision and invariants.

ApplicationKit v7 separates per-document delivery from the complete-kit
roll-up. Documents use `generated`, `generated_with_fallback`,
`needs_input_review`, `failed`, or `not_requested`; only kits use
`partially_completed`. A requested resume and cover letter are primary
documents, and `completed` means all requested primary and secondary artifacts
were delivered. Every artifact kind has a `DeliveryReport`, including explicit
`not_requested` entries.

`ENGINE_DELIVERY_FIRST=1` is the default. Setting it to `0`, `false`, `no`, or
`off` and restarting callers selects the retained PR-21 score-only optimizer:
it skips run-local identity calibration and delivery-first quality proposals.
It does **not** revert detector fixes, grounding, or additive ApplicationKit
v7/state semantics. See
[ADR-0023](../../docs/adr/0023-delivery-first-validation-and-application-kit-v7.md).

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e "packages/engine[dev]"
```

## Quality gates

```bash
pytest packages/engine            # tests
ruff check packages/engine        # lint
ruff format --check packages/engine  # format
mypy --config-file packages/engine/pyproject.toml packages/engine/src  # types
```

## Usage

```python
from ats_engine import Mode, generate_application_kit

result = generate_application_kit(
    resume_text=my_resume_text,
    job_description=my_jd_text,
    requested_mode="resume and cover letter",
    use_llm=False,  # fully deterministic path
)
print(result.resume.text)
print(result.state)
print(result.delivery_reports)
print(result.match_report.score_basis)
print(result.match_report.optimization_trace.score_path)
print(result.job_fit.fit_band)
print(result.job_fit.genuine_gaps)
print(result.interview_prep.questions)
print(result.interview_prep.star_stories)
print(result.linkedin_outreach.drafts)
```

ApplicationKit v7 retains grounded JobFit, interview preparation, LinkedIn
outreach drafts, the authoritative v2 score basis, and the optimization trace,
then adds honest delivery reports, target metadata, and kit state. Persisted
v1-v6 and known Phase 1 results remain readable through the serialization
boundary without rewriting their stored schema; unknown schemas are surfaced
as unknown instead of being guessed. Artifacts remain independently
selectable. Outreach context is typed and provenance-bound; the engine does not
send messages or access LinkedIn.
