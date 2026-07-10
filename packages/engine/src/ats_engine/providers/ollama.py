from __future__ import annotations

import json
import logging
from urllib.error import URLError
from urllib.request import Request, urlopen

from ats_engine.config import EngineSettings

logger = logging.getLogger(__name__)

# Output-length caps per task shape. The server keeps generating until a stop
# token or this cap; bounding it is the single biggest latency lever for small,
# well-scoped generations, while extraction gets more room because a full
# resume/JD can legitimately produce a large JSON payload.
NUM_PREDICT_SHORT = 700
NUM_PREDICT_EXTRACTION = 2048


class OllamaProvider:
    """LLMProvider adapter for a local Ollama-compatible HTTP endpoint.

    Implemented directly over the standard library HTTP client so the engine
    carries no LLM-vendor SDK dependency. A hosted-API provider (OpenAI,
    Anthropic, Azure, ...) is added later as a sibling adapter implementing the
    same :class:`~ats_engine.providers.base.LLMProvider` Protocol; nothing in the
    domain layer changes.
    """

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        temperature: float = 0.3,
        num_predict: int | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._temperature = temperature
        self._num_predict = num_predict
        self._timeout = timeout

    @property
    def identity(self) -> str:
        return f"{self._model}|{self._temperature}|{self._num_predict}"

    def complete(self, prompt: str) -> str:
        options: dict[str, float | int] = {"temperature": self._temperature}
        if self._num_predict is not None:
            options["num_predict"] = self._num_predict
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": options,
        }
        request = Request(
            f"{self._base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self._timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        message = body.get("message") or {}
        return str(message.get("content") or "").strip()


def is_ollama_available(settings: EngineSettings, timeout: float = 3.0) -> bool:
    """Return True when the Ollama tags endpoint responds, else False."""
    request = Request(f"{settings.ollama_base_url}/api/tags", method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return bool(200 <= response.status < 300)
    except (OSError, URLError, TimeoutError):
        return False


def ollama_provider_pair(
    settings: EngineSettings | None = None,
    *,
    model: str | None = None,
) -> tuple[OllamaProvider | None, OllamaProvider | None]:
    """Return ``(extraction_provider, prose_provider)`` if Ollama is reachable, else ``(None, None)``.

    A single connectivity check backs both: either the server is reachable and
    the caller gets two differently-capped adapters for the same model, or it is
    not and both are ``None`` so every caller falls back deterministically.
    """
    resolved = settings or EngineSettings.from_env()
    if not is_ollama_available(resolved):
        return None, None
    model_name = (model or resolved.ollama_model).strip()
    try:
        extraction = OllamaProvider(
            model=model_name,
            base_url=resolved.ollama_base_url,
            temperature=0.2,
            num_predict=NUM_PREDICT_EXTRACTION,
            timeout=resolved.llm_request_timeout,
        )
        prose = OllamaProvider(
            model=model_name,
            base_url=resolved.ollama_base_url,
            temperature=0.4,
            num_predict=NUM_PREDICT_SHORT,
            timeout=resolved.llm_request_timeout,
        )
        return extraction, prose
    except Exception:  # pragma: no cover - defensive construction guard
        logger.exception("Failed to construct Ollama providers.")
        return None, None
