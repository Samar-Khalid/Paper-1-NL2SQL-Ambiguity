"""In-process event bus for lifecycle and instrumentation events.

Events are plain objects (dataclasses) carrying typed payloads (e.g. contract
envelopes or their IDs). Consumers subscribe by event type name.
"""
from __future__ import annotations

import dataclasses
import datetime
import typing
from collections.abc import Callable
from typing import Any

EventType = str

Handler = Callable[["EventRecord"], None]


@dataclasses.dataclass(frozen=True)
class EventRecord:
    """One event on the bus."""

    event_type: EventType
    session_id: str | None = None
    run_id: str | None = None
    payload: Any = None
    emitted_at: datetime.datetime = dataclasses.field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )


class EventSink(typing.Protocol):
    """Anything that accepts events (bus, file sink, test collector)."""

    def emit(self, event: EventRecord) -> None:
        """Emit an event to the sink."""
        ...

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        """Subscribe a handler to an event type."""
        ...


class NullEventSink:
    """No-op sink used when observability is disabled."""

    def emit(self, event: EventRecord) -> None:
        """Discard an event."""
        pass

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        """Ignore a subscription."""
        pass


class EventBus:
    """Synchronous in-process pub/sub event bus."""

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[Handler]] = {}
        self._wildcards: list[Handler] = []

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        """Register a handler for a specific event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: Handler) -> None:
        """Register a handler that receives every event."""
        self._wildcards.append(handler)

    def emit(self, event: EventRecord) -> None:
        """Deliver an event to wildcard and type-specific handlers."""
        for handler in self._wildcards:
            handler(event)
        for handler in self._handlers.get(event.event_type, []):
            handler(event)

    def emit_type(
        self,
        event_type: EventType,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        payload: Any = None,
    ) -> None:
        """Build and emit an event of the given type."""
        self.emit(
            EventRecord(
                event_type=event_type,
                session_id=session_id,
                run_id=run_id,
                payload=payload,
            )
        )


default_event_bus = EventBus()
