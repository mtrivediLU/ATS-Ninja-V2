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
| `ats_engine.parsing` | PDF text, contacts, resume `Profile`, JD `JDProfile` |
| `ats_engine.evidence` | Truth-grounded gap ladder + adjacency clustering |
| `ats_engine.scoring` | Deterministic ATS keyword scoring + coverage analysis |
| `ats_engine.validation` | Claim/style/format/latex/completeness gates + severity |
| `ats_engine.caching` | Content-hash cache (disk-backed, degrades to no-op) |
| `ats_engine.providers` | `LLMProvider` interface + Ollama adapter |
| `ats_engine.generation` | Plans + resume/cover-letter/answer generation + pipeline |
| `ats_engine.job_fit` | Deterministic requirement coverage, fit bands, narrative consistency |
| `ats_engine.kit` | ApplicationKit v2, JobFitArtifact, grounding, serialization compatibility |

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
print(result.job_fit.fit_band)
print(result.job_fit.genuine_gaps)
```

ApplicationKit v2 adds the grounded JobFitArtifact. Interview preparation and
LinkedIn outreach remain future capabilities; no placeholder models them.
