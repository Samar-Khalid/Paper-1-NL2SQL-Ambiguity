"""Redaction boundary: strip secrets and PII before anything leaves the process.

The redactor is the *only* sanctioned place to decide what is safe to log or
persist. Pipeline stages must never bypass it.
"""
from __future__ import annotations

import re
from typing import Any

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "api_key",
        re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*\S+"),
    ),
    ("bearer", re.compile(r"(?i)bearer\s+[a-zA-Z0-9._~+/=-]{6,}")),
    ("authorization", re.compile(r"(?i)authorization\s*[:=]\s*\S+")),
]

_DEFAULT_REDACTED_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "passwd",
    "authorization",
    "db_password",
    "connection_string",
    "private_key",
    "openai_api_key",
}


class Redactor:
    """Redacts sensitive values in strings and dicts."""

    def __init__(
        self,
        redacted_keys: set[str] | None = None,
        secret_patterns: list[tuple[str, re.Pattern[str]]] | None = None,
    ) -> None:
        self.redacted_keys = redacted_keys or _DEFAULT_REDACTED_KEYS
        self.secret_patterns = secret_patterns or _SECRET_PATTERNS

    def redact_text(self, text: str) -> str:
        """Redact secret-looking values inside a text string."""
        for _, pattern in self.secret_patterns:
            text = pattern.sub("[REDACTED]", text)
        return text

    def redact(self, data: Any) -> Any:
        """Recursively redact a value (str/dict/list/tuple)."""
        if isinstance(data, str):
            return self.redact_text(data)
        if isinstance(data, dict):
            return {
                k: self.redact(v) if k not in self.redacted_keys else "[REDACTED]"
                for k, v in data.items()
            }
        if isinstance(data, (list, tuple)):
            return [self.redact(v) for v in data]
        return data


default_redactor = Redactor()
