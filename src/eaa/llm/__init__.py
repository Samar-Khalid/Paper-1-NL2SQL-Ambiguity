"""LLM abstraction layer: provider-agnostic backends, prompts, caching, guardrails.

Transport only — no task logic. See AGENTS.md on dataset independence.
"""
from __future__ import annotations

from .echo import EchoBackend
from .errors import LLMError
from .openai_compatible import DEFAULT_BASE_URL, OpenAICompatibleBackend, backend_from_config

__all__ = [
    "DEFAULT_BASE_URL",
    "EchoBackend",
    "LLMError",
    "OpenAICompatibleBackend",
    "backend_from_config",
]
