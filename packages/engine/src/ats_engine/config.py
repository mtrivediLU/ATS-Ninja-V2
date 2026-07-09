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
    """

    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    llm_cache_enabled: bool = True
    llm_cache_dir: Path = _DEFAULT_CACHE_DIR
    llm_cache_ttl_seconds: int = _ONE_WEEK_SECONDS
    llm_request_timeout: float = 120.0

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
        )
