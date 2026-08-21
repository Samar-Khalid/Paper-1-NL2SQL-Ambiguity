"""LLM backend protocol."""
from __future__ import annotations

from typing import Protocol

from ..contracts.llm import Completion, CompletionParams, Message


class LLMBackend(Protocol):
    """A chat-completion backend.

    Implementations are registered via config/registry (e.g. OpenAI-compatible,
    a local server). Backends never hold business logic.
    """

    model_id: str

    def complete(
        self,
        messages: list[Message],
        params: CompletionParams | None = None,
    ) -> Completion:
        """Return a completion for the given messages."""
        ...

    def complete_async(
        self,
        messages: list[Message],
        params: CompletionParams | None = None,
    ) -> Completion:
        """Return a completion for the given messages (async backend)."""
        ...


__all__ = ["LLMBackend"]
