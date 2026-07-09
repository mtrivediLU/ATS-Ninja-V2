from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from ats_engine.config import EngineSettings

"""Deterministic content-hash cache.

Expensive, deterministic-for-fixed-input work (LLM generations, parsed
profiles) is cached under a SHA-256 key derived from an identity string plus
the exact input payload. Identical inputs therefore never pay twice, including
across process restarts. This is the framework-independent replacement for the
legacy UI-framework cache coupling: the cache directory is configuration, not a
hardcoded repository path, and the backend degrades to a no-op if
:mod:`diskcache` is unavailable or the filesystem rejects it.
"""

try:  # diskcache is a declared dependency, but never let its absence break generation.
    import diskcache
except ImportError:  # pragma: no cover - defensive
    diskcache = None


def make_key(identity: str, payload: str) -> str:
    """Return a stable SHA-256 key for an (identity, payload) pair."""
    return hashlib.sha256(f"{identity}\n{payload}".encode()).hexdigest()


class ContentHashCache:
    """A small, safe wrapper over a disk-backed key/value store.

    All operations swallow backend errors: a cache is an optimization, never a
    correctness dependency, so a broken cache must degrade to "always miss"
    rather than raise into the generation path.
    """

    def __init__(
        self,
        directory: Path,
        *,
        enabled: bool = True,
        ttl_seconds: int = 7 * 24 * 60 * 60,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._enabled = enabled and diskcache is not None
        self._cache: Any | None = None
        if self._enabled:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                self._cache = diskcache.Cache(str(directory))
            except Exception:  # pragma: no cover - filesystem issues fall back to no cache
                self._cache = None
                self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled and self._cache is not None

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        try:
            return self._cache.get(key)  # type: ignore[union-attr]
        except Exception:  # pragma: no cover - never let cache errors break generation
            return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        if not self.enabled:
            return
        try:
            self._cache.set(key, value, expire=ttl_seconds or self._ttl_seconds)  # type: ignore[union-attr]
        except Exception:  # pragma: no cover - never let cache errors break generation
            pass


@lru_cache(maxsize=8)
def _cache_for(directory: Path, enabled: bool, ttl_seconds: int) -> ContentHashCache:
    return ContentHashCache(directory, enabled=enabled, ttl_seconds=ttl_seconds)


def default_cache(settings: EngineSettings | None = None) -> ContentHashCache:
    """Return the process-wide cache for the given settings (memoized per config)."""
    resolved = settings or EngineSettings.from_env()
    return _cache_for(resolved.llm_cache_dir, resolved.llm_cache_enabled, resolved.llm_cache_ttl_seconds)
