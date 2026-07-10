from __future__ import annotations

from pathlib import Path

from ats_engine.caching.content_hash import ContentHashCache, make_key
from ats_engine.config import EngineSettings
from ats_engine.providers.base import generate_json, generate_text
from ats_engine.providers.ollama import OllamaProvider
from conftest import ScriptedProvider


def _no_cache(tmp_path: Path) -> ContentHashCache:
    return ContentHashCache(tmp_path / "cache", enabled=False)


def test_generate_text_returns_empty_without_provider(tmp_path: Path) -> None:
    assert generate_text(None, "prompt", cache=_no_cache(tmp_path)) == ""


def test_generate_text_uses_provider(tmp_path: Path) -> None:
    provider = ScriptedProvider("hello world")
    assert generate_text(provider, "prompt", cache=_no_cache(tmp_path)) == "hello world"
    assert provider.calls == ["prompt"]


def test_generate_text_is_cached(tmp_path: Path) -> None:
    cache = ContentHashCache(tmp_path / "cache", enabled=True)
    provider = ScriptedProvider("cached result")
    first = generate_text(provider, "same prompt", cache=cache)
    second = generate_text(provider, "same prompt", cache=cache)
    assert first == second == "cached result"
    # The provider is only hit once; the second call is served from cache.
    assert len(provider.calls) == 1


def test_generate_json_parses_and_repairs(tmp_path: Path) -> None:
    provider = ScriptedProvider('```json\n{"a": 1}\n```')
    result = generate_json(provider, "prompt", cache=_no_cache(tmp_path))
    assert result == {"a": 1}


def test_generate_json_returns_none_on_unparseable(tmp_path: Path) -> None:
    provider = ScriptedProvider("not json at all")
    assert generate_json(provider, "prompt", retries=0, cache=_no_cache(tmp_path)) is None


def test_content_hash_cache_disabled_is_always_miss(tmp_path: Path) -> None:
    cache = ContentHashCache(tmp_path / "cache", enabled=False)
    cache.set("k", "v")
    assert cache.get("k") is None
    assert cache.enabled is False


def test_make_key_is_stable_and_input_sensitive() -> None:
    assert make_key("id", "payload") == make_key("id", "payload")
    assert make_key("id", "payload") != make_key("id", "other")


def test_ollama_provider_identity_encodes_decoding_params() -> None:
    provider = OllamaProvider(model="llama3.2", base_url="http://localhost:11434", temperature=0.2, num_predict=2048)
    assert provider.identity == "llama3.2|0.2|2048"


def test_engine_settings_from_env_defaults() -> None:
    settings = EngineSettings.from_env({})
    assert settings.ollama_base_url == "http://localhost:11434"
    assert settings.ollama_model == "llama3.2"
    assert settings.llm_cache_enabled is True


def test_engine_settings_from_env_overrides() -> None:
    settings = EngineSettings.from_env(
        {
            "OLLAMA_BASE_URL": "http://ollama:11434/",
            "OLLAMA_MODEL": "qwen2.5",
            "ATS_ENGINE_LLM_CACHE": "0",
        }
    )
    assert settings.ollama_base_url == "http://ollama:11434"  # trailing slash trimmed
    assert settings.ollama_model == "qwen2.5"
    assert settings.llm_cache_enabled is False
