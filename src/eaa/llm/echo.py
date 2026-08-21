"""Deterministic test backend: returns the last user/assistant message verbatim."""
from __future__ import annotations

from ..core.contracts.llm import Completion, CompletionParams, Message


class EchoBackend:
    """A deterministic chat backend that echoes the last message.

    ``model_id`` is fixed so runs record a stable id. Useful for unit tests and
    the hello-world pipeline; never for research numbers.
    """

    model_id = "echo-local-v1"

    def complete(
        self,
        messages: list[Message],
        params: CompletionParams | None = None,
    ) -> Completion:
        """Return the last user/assistant message content as the completion."""
        last = next(
            (message for message in reversed(messages) if message.role in ("user", "assistant")),
            None,
        )
        content = last.content if last is not None else ""
        return Completion(
            message=Message(role="assistant", content=content),
            model_id=self.model_id,
            finish_reason="stop",
        )

    def complete_async(
        self,
        messages: list[Message],
        params: CompletionParams | None = None,
    ) -> Completion:
        """Identical to :meth:`complete` (the echo backend is synchronous)."""
        return self.complete(messages, params)


__all__ = ["EchoBackend"]
