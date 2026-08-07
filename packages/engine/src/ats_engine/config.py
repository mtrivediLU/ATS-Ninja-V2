from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

"""Framework-independent engine configuration.

The engine reads its settings from explicit values or, as a convenience, from
environment variables via :meth:`EngineSettings.from_env`. There is no
dependency on any UI-framework secrets store, FastAPI settings, or web
framework: a caller (API service, worker, test, or notebook) constructs an
:class:`EngineSettings` and passes it in, or relies on the process
environment. This keeps the engine usable in any runtime.
"""

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2"
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "ats-engine" / "llm"
_ONE_WEEK_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class EngineSettings:
    """Immutable engine configuration.

    Attributes:
        ollama_base_url: Base URL of the Ollama-compatible HTTP endpoint.
        ollama_model: Default local model name.
        llm_cache_enabled: When False, all content-hash LLM caching is skipped.
        llm_cache_dir: Directory backing the content-hash cache.
        llm_cache_ttl_seconds: Time-to-live for cached generations.
        llm_request_timeout: Per-request timeout (seconds) for provider calls.
        tailoring_v2: Enables the evidence-grounded Tailoring Engine v2 path.
        delivery_first: Enables calibrated validation and the delivery-first
            optimizer. This is a one-release rollout switch; disabling it uses
            the retained PR-21 score-only optimizer while keeping detector
            correctness, grounding, and additive wire-contract fixes in place.
        optimizer_policy: Selects the placement-action acceptance rule inside
            the delivery-first optimizer (has no effect when delivery_first is
            False). ``"pareto"`` accepts a proposal that improves PRAMANA
            coverage, JD-surface adoption, or density without regressing any
            of the three beyond tolerance -- see ``generation.optimizer``.
            ``"legacy"`` is a rollback switch that retains the original
            strict-PRAMANA-score-improvement rule exactly.
        resume_word_budget: Target delivered length, in words. A *target*, not
            a truncation: nothing is ever cut to reach it, and a document over
            budget is delivered unchanged if no removal is provably safe. It
            only changes how hard a prune has to work -- see
            ``generation.optimizer._prune_verdict``. The default is chosen from
            the fixtures rather than from folklore: their source projections
            run 995-1002 words, and mainstream two-page resume guidance lands
            around 800-1000, so 950 sits just below every fixture's current
            length. That keeps the budget *active* (concision is the binding
            need on real input) without demanding cuts that would have to reach
            protected content to satisfy it.
    """

    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    llm_cache_enabled: bool = True
    llm_cache_dir: Path = _DEFAULT_CACHE_DIR
    llm_cache_ttl_seconds: int = _ONE_WEEK_SECONDS
    llm_request_timeout: float = 120.0
    tailoring_v2: bool = True
    delivery_first: bool = True
    optimizer_policy: str = "pareto"
    resume_word_budget: int = 950

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> EngineSettings:
        """Build settings from environment variables with safe fallbacks."""
        env = os.environ if environ is None else environ
        cache_dir = env.get("ATS_ENGINE_LLM_CACHE_DIR")
        return cls(
            ollama_base_url=(env.get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL).rstrip("/"),
            ollama_model=(env.get("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL).strip(),
            llm_cache_enabled=env.get("ATS_ENGINE_LLM_CACHE", "1") != "0",
            llm_cache_dir=Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR,
            llm_cache_ttl_seconds=int(env.get("ATS_ENGINE_LLM_CACHE_TTL", _ONE_WEEK_SECONDS)),
            llm_request_timeout=float(env.get("ATS_ENGINE_LLM_TIMEOUT", 120.0)),
            tailoring_v2=(env.get("ENGINE_TAILORING_V2", "1").strip().lower() not in {"0", "false", "no", "off"}),
            delivery_first=(env.get("ENGINE_DELIVERY_FIRST", "1").strip().lower() not in {"0", "false", "no", "off"}),
            optimizer_policy=(env.get("ENGINE_OPTIMIZER_POLICY", "pareto").strip().lower() or "pareto"),
            resume_word_budget=int(env.get("ENGINE_RESUME_WORD_BUDGET", 950)),
        )
