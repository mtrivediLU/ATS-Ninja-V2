from __future__ import annotations

from dataclasses import dataclass

from ats_engine.config import EngineSettings
from ats_engine.kit.contract import ORCHESTRATION_VERSION, SCHEMA_VERSION
from ats_engine.providers.base import LLMProvider
from ats_engine.providers.ollama import ollama_provider_pair

"""Vendor-neutral model/provider routing for the orchestrator (Phase 2A).

This is a *lightweight* routing layer, not a multi-provider marketplace. It:

- keeps provider choice configuration-driven (no vendor SDK, no hardcoded
  Anthropic/OpenAI/Gemini/Ollama, in domain logic — see AGENTS.md and ADR-0010);
- preserves the deterministic ``provider=None`` path end to end;
- supports a *primary* provider, an optional *fallback* provider, and the
  deterministic fallback, with the deliberate policy that candidate-derived
  prompts reach the fallback **only** when the primary actually fails; and
- accurately counts provider calls and fallback usage for
  :class:`~ats_engine.kit.contract.GenerationMetadata` (no fabricated token/cost/
  latency numbers).

Cache identity: the wrapper's ``identity`` is salted with the schema and
orchestration contract versions, so a change in grounding behavior never reuses
prose cached under an older contract (ADR-0013).
"""

_CACHE_SALT = f"{SCHEMA_VERSION}:{ORCHESTRATION_VERSION}"


@dataclass(slots=True)
class ProviderStats:
    """Mutable accumulator for accurate generation metadata."""

    calls: int = 0
    fallback_used: bool = False


class CountingProvider:
    """Wrap a provider to count calls and tie cache identity to the contract."""

    def __init__(self, inner: LLMProvider, stats: ProviderStats) -> None:
        self._inner = inner
        self._stats = stats

    @property
    def identity(self) -> str:
        return f"{self._inner.identity}|orch={_CACHE_SALT}"

    def complete(self, prompt: str) -> str:
        self._stats.calls += 1
        return self._inner.complete(prompt)


class FallbackProvider:
    """Try the primary provider; on failure, use the fallback under policy.

    The fallback is invoked ONLY when the primary raises. This keeps the privacy
    guarantee explicit: candidate-derived prompts are not fanned out to multiple
    providers speculatively; a second provider sees the prompt only to recover
    from a real primary failure, and only because a fallback was configured.
    """

    def __init__(self, primary: LLMProvider, fallback: LLMProvider, stats: ProviderStats) -> None:
        self._primary = primary
        self._fallback = fallback
        self._stats = stats

    @property
    def identity(self) -> str:
        # Cache on the primary's identity; a fallback recovery is not cached under
        # a distinct key because it is an exceptional path, not a routing choice.
        return self._primary.identity

    def complete(self, prompt: str) -> str:
        try:
            return self._primary.complete(prompt)
        except Exception:
            self._stats.fallback_used = True
            return self._fallback.complete(prompt)


@dataclass(slots=True)
class ResolvedProviders:
    """The providers to pass into the pipeline, plus metadata inputs."""

    extraction: LLMProvider | None
    prose: LLMProvider | None
    stats: ProviderStats
    llm_available: bool
    provider_identity: str
    model: str

    @property
    def generation_mode(self) -> str:
        return "provider" if self.llm_available else "deterministic"


def resolve_providers(
    *,
    settings: EngineSettings,
    use_llm: bool,
    model_name: str = "",
    extraction_provider: LLMProvider | None = None,
    prose_provider: LLMProvider | None = None,
    fallback_provider: LLMProvider | None = None,
) -> ResolvedProviders:
    """Resolve primary/fallback/deterministic providers for a generation run.

    Mirrors the engine pipeline's provider-selection rules so behavior is
    identical, then wraps the resolved providers for call counting and contract-
    salted caching. When no provider is available, both are ``None`` and the
    deterministic path runs end to end.
    """
    stats = ProviderStats()

    if extraction_provider is not None or prose_provider is not None:
        extraction, prose = extraction_provider, prose_provider
    elif not use_llm:
        extraction, prose = None, None
    else:
        extraction, prose = ollama_provider_pair(settings, model=model_name or None)

    if extraction is None and prose is None:
        return ResolvedProviders(
            extraction=None,
            prose=None,
            stats=stats,
            llm_available=False,
            provider_identity="",
            model="",
        )

    identity_source = extraction or prose
    provider_identity = identity_source.identity if identity_source is not None else ""
    model = model_name or getattr(settings, "ollama_model", "")

    wrapped_extraction = _wrap(extraction, fallback_provider, stats)
    wrapped_prose = _wrap(prose, fallback_provider, stats)

    return ResolvedProviders(
        extraction=wrapped_extraction,
        prose=wrapped_prose,
        stats=stats,
        llm_available=True,
        provider_identity=provider_identity,
        model=model,
    )


def _wrap(
    provider: LLMProvider | None,
    fallback: LLMProvider | None,
    stats: ProviderStats,
) -> LLMProvider | None:
    if provider is None:
        return None
    routed: LLMProvider = provider if fallback is None else FallbackProvider(provider, fallback, stats)
    return CountingProvider(routed, stats)
