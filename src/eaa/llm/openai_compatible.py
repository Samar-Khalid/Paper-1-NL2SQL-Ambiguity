"""OpenAI-compatible chat backend (transport only).

Speaks the ``/chat/completions`` REST shape (OpenAI, vLLM, Ollama, LM Studio,
TGI, ...) over stdlib ``urllib`` so no HTTP dependency is required. Backends
never contain task logic.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from ..core.configuration.schemas import LLMConfig
from ..core.contracts.llm import (
    Completion,
    CompletionParams,
    Message,
    Usage,
)
from .echo import EchoBackend
from .errors import LLMError

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAICompatibleBackend:
    """A minimal OpenAI-compatible chat-completion client."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str | None = None,
        api_key_env: str | None = None,
        temperature: float = 0.0,
        max_retries: int = 3,
        timeout_seconds: int = 60,
    ) -> None:
        if not model:
            raise ValueError("OpenAICompatibleBackend requires a model id")
        if base_url is not None and not base_url.startswith(("http://", "https://")):
            raise ValueError(f"base_url must be http(s): {base_url!r}")
        self.model = model
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key_env = api_key_env or "OPENAI_API_KEY"
        self.temperature = temperature
        self.max_retries = max(0, max_retries)
        self.timeout_seconds = timeout_seconds

    @property
    def model_id(self) -> str:
        """Return the configured model id."""
        return self.model

    def complete(
        self,
        messages: list[Message],
        params: CompletionParams | None = None,
    ) -> Completion:
        """Request a chat completion and return a ``Completion``."""
        body = self._build_body(messages, params)
        last_error: LLMError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                payload = self._post(body)
                return self._to_completion(payload)
            except LLMError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(min(2.0**attempt, 8.0))
        if last_error is None:  # defensive; the loop always sets it on failure
            raise LLMError("LLM request failed", code="LLM_TRANSPORT_ERROR")
        raise last_error

    def complete_async(
        self,
        messages: list[Message],
        params: CompletionParams | None = None,
    ) -> Completion:
        """Identical to :meth:`complete` (no true async transport yet)."""
        return self.complete(messages, params)

    def _build_body(
        self,
        messages: list[Message],
        params: CompletionParams | None,
    ) -> dict[str, Any]:
        temperature = self.temperature
        if params is not None and params.temperature is not None:
            temperature = params.temperature
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                message.model_dump(exclude_none=True)
                for message in messages
            ],
            "temperature": temperature,
        }
        if params is not None:
            if params.top_p is not None:
                body["top_p"] = params.top_p
            if params.max_tokens is not None:
                body["max_tokens"] = params.max_tokens
            if params.stop is not None:
                body["stop"] = params.stop
            body.update(params.extra)
        return body

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST ``body`` to the chat completions endpoint (raises ``LLMError``).

        The base URL is validated as http(s) at construction, so the request can
        only target a permitted web endpoint.
        """
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        api_key = os.environ.get(self.api_key_env)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            # noqa: S310 - base_url is scheme-checked in __init__ (http/https only)
            request = urllib.request.Request(  # noqa: S310
                url,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            # noqa: S310 - base_url is scheme-checked in __init__ (http/https only)
            with urllib.request.urlopen(  # noqa: S310
                request, timeout=self.timeout_seconds
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMError(f"LLM request failed: {exc}", code="LLM_TRANSPORT_ERROR") from exc
        if not isinstance(payload, dict):
            raise LLMError("LLM response is not a JSON object", code="LLM_RESPONSE_ERROR")
        return payload

    @staticmethod
    def _to_completion(payload: dict[str, Any]) -> Completion:
        """Parse a chat-completions payload into a ``Completion``."""
        try:
            choice = payload["choices"][0]
            message = choice["message"]
            usage_raw = payload.get("usage") or {}
            return Completion(
                message=Message(
                    role="assistant",
                    content=message.get("content") or "",
                    name=message.get("name"),
                ),
                usage=Usage(
                    prompt_tokens=usage_raw.get("prompt_tokens"),
                    completion_tokens=usage_raw.get("completion_tokens"),
                    total_tokens=usage_raw.get("total_tokens"),
                ),
                model_id=payload.get("model"),
                finish_reason=choice.get("finish_reason"),
                raw=payload,
            )
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LLMError(f"malformed LLM response: {exc}", code="LLM_RESPONSE_ERROR") from exc


def backend_from_config(config: LLMConfig) -> Any:
    """Build an LLM backend from an ``LLMConfig`` (transport only).

    Raises
    ------
        LLMError: if no provider is configured (fail loudly rather than silently
            routing research runs to a dummy backend).
    """
    provider = (config.provider or "").lower()
    if provider == "":
        raise LLMError("no LLM provider configured", code="LLM_UNKNOWN_PROVIDER")
    if provider in ("echo", "echo-local"):
        return EchoBackend()
    if provider in ("openai", "openai-compatible", "vllm", "ollama"):
        return OpenAICompatibleBackend(
            model=config.model or "",
            base_url=config.base_url,
            api_key_env=config.api_key_env,
            temperature=config.temperature,
            max_retries=config.max_retries,
            timeout_seconds=config.timeout_seconds,
        )
    raise LLMError(f"unknown LLM provider: {config.provider!r}", code="LLM_UNKNOWN_PROVIDER")


__all__ = [
    "DEFAULT_BASE_URL",
    "EchoBackend",
    "LLMError",
    "OpenAICompatibleBackend",
    "backend_from_config",
]
