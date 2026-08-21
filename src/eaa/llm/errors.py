"""Errors for the LLM transport layer."""
from __future__ import annotations

from ..core.contracts.errors import EAAError


class LLMError(EAAError):
    """An LLM request failed or returned a malformed response."""


__all__ = ["LLMError"]
