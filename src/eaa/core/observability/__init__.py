"""Observability: structured logging, events, tracing, and redaction.

Everything observable is generated from core contracts so research runs are
auditable and reproducible (metrics derive from contract payloads, never from
free-form state).
"""
from __future__ import annotations

from .config import configure_logging
from .events import EventBus, EventSink, NullEventSink
from .redaction import Redactor, default_redactor
from .tracing import span

__all__ = [
    "EventBus",
    "EventSink",
    "NullEventSink",
    "Redactor",
    "configure_logging",
    "default_redactor",
    "span",
]
