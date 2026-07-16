from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol, TypeVar, runtime_checkable

from ats_engine.caching.content_hash import ContentHashCache, default_cache, make_key

logger = logging.getLogger(__name__)


def _safe_response_fingerprint(text: str) -> str:
    """A privacy-safe descriptor of a provider response for logs.

    Model output is candidate-derived and must never be logged verbatim. This
    returns only its length and a short content hash — enough to correlate
    repeated failures without exposing any prompt, resume, or generated content.
    """
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]
    return f"len={len(text)} sha256={digest}"


T = TypeVar("T")


@runtime_checkable
class LLMProvider(Protocol):
    """The engine's only view of an LLM.

    Implementations are thin adapters over a specific vendor. The engine treats
    every response as untrusted text; grounding and validation happen in the
    deterministic layers regardless of which provider produced the text.
    """

    @property
    def identity(self) -> str:
        """Stable string identifying model + decoding params, used as a cache key."""
        ...

    def complete(self, prompt: str) -> str:
        """Return the model's completion for ``prompt``. May raise on transport failure."""
        ...


def generate_text(
    provider: LLMProvider | None,
    prompt: str,
    *,
    cache: ContentHashCache | None = None,
) -> str:
    """Invoke the provider for plain text, returning ``''`` on any failure.

    Identical (identity, prompt) pairs are served from the content-hash cache,
    so repeated generations against unchanged inputs skip the network round
    trip entirely. Returning ``''`` (rather than raising) lets every caller
    fall back to deterministic logic, which is the engine's default posture.
    """
    if provider is None or not prompt.strip():
        return ""

    store = cache or default_cache()
    key = make_key(provider.identity, prompt)
    cached = store.get(key)
    if isinstance(cached, str):
        return cached

    try:
        text = _clean(provider.complete(prompt))
    except Exception:
        logger.exception("LLM text generation failed.")
        return ""

    if text:
        store.set(key, text)
    return text


def generate_json(
    provider: LLMProvider | None,
    prompt: str,
    *,
    retries: int = 2,
    cache: ContentHashCache | None = None,
) -> dict[str, Any] | list[Any] | None:
    """Invoke the provider expecting JSON, with self-repair retries.

    Returns ``None`` when the provider is unavailable or never produces
    parseable JSON, so callers fall back to deterministic logic. Cached the same
    way as :func:`generate_text`, keyed on the exact prompt sent per attempt.
    """
    if provider is None or not prompt.strip():
        return None

    store = cache or default_cache()
    current_prompt = prompt
    last_raw = ""
    for attempt in range(retries + 1):
        key = make_key(provider.identity, current_prompt)
        cached = store.get(key)
        if isinstance(cached, (dict, list)):
            return cached

        try:
            raw = _clean(provider.complete(current_prompt))
        except Exception:
            logger.exception("LLM JSON generation failed on attempt %s.", attempt)
            return None

        last_raw = raw
        parsed = _parse_json_loose(raw)
        if parsed is not None:
            store.set(key, parsed)
            return parsed

        current_prompt = (
            f"{prompt}\n\nYour previous reply was not valid JSON:\n{raw}\n\n"
            "Reply again with ONLY a single valid JSON object or array. "
            "No markdown code fences, no commentary, no trailing commas."
        )

    logger.warning(
        "LLM never returned parseable JSON after %s attempts (provider=%s, response=%s).",
        retries + 1,
        provider.identity,
        _safe_response_fingerprint(last_raw),
    )
    return None


def run_concurrently(tasks: dict[str, Callable[[], T]], max_workers: int | None = None) -> dict[str, T]:
    """Run independent zero-arg callables concurrently and return results by key.

    Provider calls are I/O-bound HTTP round trips, so threads are the right
    primitive: whichever calls the model server can interleave will overlap,
    and worst case this degrades to sequential with negligible overhead.
    """
    if len(tasks) <= 1:
        return {key: task() for key, task in tasks.items()}

    results: dict[str, T] = {}
    with ThreadPoolExecutor(max_workers=max_workers or len(tasks)) as executor:
        futures = {key: executor.submit(task) for key, task in tasks.items()}
        for key, future in futures.items():
            results[key] = future.result()
    return results


def _clean(text: str) -> str:
    return str(text or "").strip()


def _parse_json_loose(raw: str) -> dict[str, Any] | list[Any] | None:
    if not raw:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    parsed = _loads_or_none(cleaned)
    if parsed is not None:
        return parsed

    match = re.search(r"(\{.*\}|\[.*\])", cleaned, flags=re.DOTALL)
    if match:
        return _loads_or_none(match.group(1))
    return None


def _loads_or_none(text: str) -> dict[str, Any] | list[Any] | None:
    try:
        result = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return result if isinstance(result, (dict, list)) else None
