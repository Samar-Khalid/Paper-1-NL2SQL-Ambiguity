"""LLM message/completion contracts shared across modules.

These are *contracts* (pure data), not the backend abstraction — the backend
protocols live in ``core/interfaces/llm.py``.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel


class Message(ContractModel):
    """One chat message."""

    role: str  # system | user | assistant | tool
    content: str
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Usage(ContractModel):
    """Token/cost accounting for a completion."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None


class CompletionParams(ContractModel):
    """Sampling parameters for a completion."""

    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: list[str] | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class Completion(ContractModel):
    """A completed LLM response."""

    message: Message
    usage: Usage = Field(default_factory=Usage)
    model_id: str | None = None
    finish_reason: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
