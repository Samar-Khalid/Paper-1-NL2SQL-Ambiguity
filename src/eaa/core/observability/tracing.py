"""Minimal tracing support (in-process spans).

Full OpenTelemetry integration is out of scope for the foundation; this module
provides the span data model and a context-manager helper that the observability
layer can later forward to a real exporter.
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime
import threading
import uuid
from collections.abc import Iterator
from typing import Any


@dataclasses.dataclass(frozen=True)
class Span:
    """A traced unit of work."""

    span_id: str
    trace_id: str
    parent_span_id: str | None
    name: str
    started_at: datetime.datetime
    finished_at: datetime.datetime | None = None
    attributes: dict[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def duration_ms(self) -> float | None:
        """Return the span duration in milliseconds, or None if unfinished."""
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds() * 1000.0


class _SpanContext:
    """Thread-local holder of the current span."""

    def __init__(self) -> None:
        self._local = threading.local()

    @property
    def current(self) -> Span | None:
        """Return the current span for this thread, if any."""
        return getattr(self._local, "current", None)

    @current.setter
    def current(self, span: Span | None) -> None:
        self._local.current = span


_SPAN_CONTEXT = _SpanContext()


def current_trace_id() -> str | None:
    """Return the trace id of the current span, if any."""
    span = _SPAN_CONTEXT.current
    return span.trace_id if span else None


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[Span]:
    """Run a block inside a traced span."""
    parent = _SPAN_CONTEXT.current
    span_obj = Span(
        span_id=uuid.uuid4().hex,
        trace_id=parent.trace_id if parent else uuid.uuid4().hex,
        parent_span_id=parent.span_id if parent else None,
        name=name,
        started_at=datetime.datetime.now(datetime.UTC),
        attributes=dict(attributes),
    )
    _SPAN_CONTEXT.current = span_obj
    try:
        yield span_obj
        span_obj = dataclasses.replace(
            span_obj, finished_at=datetime.datetime.now(datetime.UTC)
        )
    finally:
        if _SPAN_CONTEXT.current is span_obj:
            _SPAN_CONTEXT.current = parent
