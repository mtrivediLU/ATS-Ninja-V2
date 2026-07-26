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
| `ats_engine.validation` | Claim/fidelity/stuffing/style/format/LaTeX/completeness gates + severity |
| `ats_engine.caching` | Content-hash cache (disk-backed, degrades to no-op) |
| `ats_engine.providers` | `LLMProvider` interface + Ollama adapter |
| `ats_engine.generation` | Source-preserving plans, placement planner, optimizer, document generation + pipeline |
| `ats_engine.job_fit` | Deterministic requirement coverage, fit bands, narrative consistency |
| `ats_engine.interview_prep` | Grounded questions, STAR integrity, gap guidance, provider consistency |
| `ats_engine.linkedin_outreach` | Grounded drafts, evidence boundaries, relationship and length validation |
| `ats_engine.kit` | ApplicationKit v6, typed artifacts, grounding, optimization trace, serialization compatibility |

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

## Tailoring Engine v2

The default tailoring path is a deterministic, provenance-carrying sequence:

```
source extraction → JD requirements → evidence resolver → placement planner
→ monotone optimizer → fidelity/stuffing/grounding validators → ats_v2 scorer
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
- The optimizer accepts an action batch only when it strictly improves the one
  authoritative `ats_v2` score and passes raw-source fidelity, anti-stuffing,
  grounding, and structural gates. It otherwise bisects/rejects the batch and
  falls back to source content rather than weakening a fact.
- The final v2 tailored score is asserted to be no lower than the original
  score. `MatchReport.optimization_trace` records score steps, accepted and
  rejected actions, and truly unreachable terms.

The path works with `provider=None` / `use_llm=False`. To temporarily retain
the compatibility path while investigating an older caller, set
`ENGINE_TAILORING_V2=0`; this does not bypass grounding or validation. See
[ADR-0022](../../docs/adr/0022-tailoring-engine-v2-evidence-grounded-iterative-optimization.md)
for the full decision and invariants.

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
print(result.match_report.score_basis)
print(result.match_report.optimization_trace.score_path)
print(result.job_fit.fit_band)
print(result.job_fit.genuine_gaps)
print(result.interview_prep.questions)
print(result.interview_prep.star_stories)
print(result.linkedin_outreach.drafts)
```

ApplicationKit v6 retains grounded JobFit, interview preparation, and LinkedIn
outreach drafts, and adds the v2 score basis and optimization trace. These
artifacts remain independently selectable. Outreach context is typed and
provenance-bound; the engine does not send messages or access LinkedIn.
