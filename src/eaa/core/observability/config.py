"""Configure structured logging for the framework."""
from __future__ import annotations

import logging
from typing import Any


def configure_logging(*, level: str | int = logging.INFO, json: bool = False) -> None:
    """Configure structured logging.

    Prefers structlog when available; falls back to stdlib ``logging`` so the
    core remains runnable without optional dependencies.
    """
    try:
        import structlog

        _level = logging.getLevelName(level) if isinstance(level, int) else level
        processors: list[Any] = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
        ]
        renderer: Any = (
            structlog.processors.JSONRenderer()
            if json
            else structlog.dev.ConsoleRenderer()
        )
        structlog.configure(
            processors=[*processors, renderer],
            wrapper_class=structlog.make_filtering_bound_logger(_level),
        )
    except ImportError:  # pragma: no cover - structlog is optional at runtime
        logging.basicConfig(level=level)


def get_logger(name: str | None = None) -> Any:
    """Return a structured logger (structlog) or a stdlib fallback."""
    try:
        import structlog

        return structlog.get_logger(name)
    except ImportError:  # pragma: no cover
        return logging.getLogger(name)
