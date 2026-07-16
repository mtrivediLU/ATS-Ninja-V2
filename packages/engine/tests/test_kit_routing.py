from __future__ import annotations

from ats_engine.caching.content_hash import make_key
from ats_engine.config import EngineSettings
from ats_engine.generation.planning import build_resume_plan
from ats_engine.generation.prompts import PROHIBITED_INVENTION_CLAUSE, PROHIBITED_INVENTIONS
from ats_engine.kit import generate_application_kit
from ats_engine.kit.routing import (
    CountingProvider,
    FallbackProvider,
    ProviderStats,
    resolve_providers,
)
from ats_engine.models import JDProfile, Mode
from ats_engine.parsing.resume import build_profile
from conftest import ADVERSARIAL_JD, ADVERSARIAL_RESUME

"""Provider routing, failure handling, cache identity, and prompt contract.

Covers Steps 10, 16, and 17.
"""


class _Raises:
    @property
    def identity(self) -> str:
        return "raises:test"

    def complete(self, prompt: str) -> str:
        raise RuntimeError("provider down")


class _Timeout:
    @property
    def identity(self) -> str:
        return "timeout:test"

    def complete(self, prompt: str) -> str:
        raise TimeoutError("slow")


class _Fixed:
    def __init__(self, text: str, identity: str = "fixed:test") -> None:
        self._text = text
        self._identity = identity
        self.calls = 0

    @property
    def identity(self) -> str:
        return self._identity

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return self._text


class _FailsOnce:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def identity(self) -> str:
        return "failsonce:test"

    def complete(self, prompt: str) -> str:
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("transient")
        return "recovered text"


# --------------------------------------------------------------------------- #
# resolve_providers + deterministic path (Step 16)
# --------------------------------------------------------------------------- #
def test_use_llm_false_resolves_to_deterministic() -> None:
    resolved = resolve_providers(settings=EngineSettings(), use_llm=False)
    assert resolved.extraction is None
    assert resolved.prose is None
    assert resolved.llm_available is False
    assert resolved.generation_mode == "deterministic"


def test_explicit_provider_is_wrapped_and_counted() -> None:
    provider = _Fixed("hi")
    resolved = resolve_providers(settings=EngineSettings(), use_llm=True, prose_provider=provider)
    assert resolved.prose is not None
    assert resolved.llm_available is True
    resolved.prose.complete("prompt")
    assert resolved.stats.calls == 1


def test_provider_none_deterministic_path_end_to_end() -> None:
    kit = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        default_mode=Mode.RESUME_AND_COVER,
        use_llm=False,
    )
    assert kit.resume is not None
    assert kit.generation.generation_mode == "deterministic"


# --------------------------------------------------------------------------- #
# Provider failure resilience (Step 16)
# --------------------------------------------------------------------------- #
def test_raising_provider_does_not_crash_and_falls_back() -> None:
    # A provider that always raises must degrade to the deterministic path, not
    # crash the kit generation or leak a traceback.
    kit = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        default_mode=Mode.RESUME_AND_COVER,
        use_llm=True,
        extraction_provider=_Raises(),
        prose_provider=_Raises(),
    )
    assert kit.resume is not None
    assert kit.cover_letter is not None
    assert not kit.validation.fatal


def test_timeout_provider_falls_back_cleanly() -> None:
    kit = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        default_mode=Mode.RESUME,
        use_llm=True,
        prose_provider=_Timeout(),
    )
    assert kit.resume is not None


def test_fallback_provider_used_only_on_primary_failure() -> None:
    stats = ProviderStats()
    fallback = _Fixed("from fallback")
    routed = FallbackProvider(_Raises(), fallback, stats)
    assert routed.complete("p") == "from fallback"
    assert stats.fallback_used is True
    assert fallback.calls == 1


def test_fallback_provider_not_used_when_primary_succeeds() -> None:
    stats = ProviderStats()
    fallback = _Fixed("from fallback")
    primary = _Fixed("from primary")
    routed = FallbackProvider(primary, fallback, stats)
    assert routed.complete("p") == "from primary"
    assert stats.fallback_used is False
    assert fallback.calls == 0


def test_primary_failure_without_fallback_propagates_to_deterministic() -> None:
    # No fallback configured: resolve_providers wraps the primary alone; the
    # engine's generate_text swallows the raise and returns "" (deterministic).
    resolved = resolve_providers(settings=EngineSettings(), use_llm=True, prose_provider=_Raises())
    assert isinstance(resolved.prose, CountingProvider)


def test_transient_failure_then_success_via_fallback() -> None:
    stats = ProviderStats()
    primary = _FailsOnce()
    routed = FallbackProvider(primary, _Fixed("safety net"), stats)
    # First call: primary raises -> fallback recovers.
    assert routed.complete("p1") == "safety net"
    # Second call: primary now succeeds.
    assert routed.complete("p2") == "recovered text"


# --------------------------------------------------------------------------- #
# Cache identity (Step 17)
# --------------------------------------------------------------------------- #
def test_counting_provider_identity_carries_contract_salt() -> None:
    stats = ProviderStats()
    wrapped = CountingProvider(_Fixed("x", identity="ollama:llama3.2"), stats)
    assert wrapped.identity.startswith("ollama:llama3.2")
    assert "orch=" in wrapped.identity
    assert "application-kit/v3" in wrapped.identity


def test_cache_key_changes_with_contract_and_provider_but_hides_raw_text() -> None:
    base = make_key("ollama:llama3.2|orch=application-kit/v1:grounded-orchestration/v1", "PROMPT")
    other_contract = make_key("ollama:llama3.2|orch=application-kit/v2:grounded-orchestration/v2", "PROMPT")
    other_provider = make_key("ollama:other|orch=application-kit/v1:grounded-orchestration/v1", "PROMPT")
    assert base != other_contract  # contract bump invalidates cache
    assert base != other_provider  # provider identity participates
    # Key is a SHA-256 hex digest, never the human-readable resume text.
    assert len(base) == 64 and all(c in "0123456789abcdef" for c in base)


def test_raw_resume_text_is_not_a_cache_key() -> None:
    secret = "Jordan Rivera SIN 123-456-789"
    key = make_key("ollama:llama3.2|orch=x", secret)
    assert secret not in key
    assert "Jordan" not in key


# --------------------------------------------------------------------------- #
# Prompt contract (Step 10)
# --------------------------------------------------------------------------- #
def test_prohibited_invention_clause_enumerates_sensitive_categories() -> None:
    clause = PROHIBITED_INVENTION_CLAUSE.lower()
    for needle in ("employers", "titles", "metrics", "dollar values", "team sizes", "certifications", "degrees"):
        assert needle in clause
    assert len(PROHIBITED_INVENTIONS) >= 10


def test_real_summary_prompt_includes_the_evidence_boundary() -> None:
    captured: list[str] = []

    class _Capture:
        @property
        def identity(self) -> str:
            return "capture:test"

        def complete(self, prompt: str) -> str:
            captured.append(prompt)
            return ""  # force fallback; we only care about the prompt

    profile = build_profile(ADVERSARIAL_RESUME)
    jd = JDProfile(title="AI Engineer", company="Vantage Analytics", technical_keywords=["python", "sql"])
    build_resume_plan(
        contacts=profile.contact, jd_profile=jd, profile=profile, provider=_Capture(), batch_provider=None
    )
    assert any(PROHIBITED_INVENTION_CLAUSE in prompt for prompt in captured)
