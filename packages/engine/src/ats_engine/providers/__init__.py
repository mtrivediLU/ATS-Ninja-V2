"""LLM provider abstraction.

Domain code depends only on :class:`LLMProvider` and the ``generate_text`` /
``generate_json`` helpers. Concrete vendors (Ollama today; hosted APIs later)
are adapters that implement the Protocol. No provider SDK is imported by domain
modules, and no vendor name is hardcoded into the engine's core.
"""

from __future__ import annotations

from ats_engine.providers.base import (
    LLMProvider,
    generate_json,
    generate_text,
    run_concurrently,
)
from ats_engine.providers.ollama import OllamaProvider, ollama_provider_pair

__all__ = [
    "LLMProvider",
    "OllamaProvider",
    "generate_json",
    "generate_text",
    "ollama_provider_pair",
    "run_concurrently",
]
