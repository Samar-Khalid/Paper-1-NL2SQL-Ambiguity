"""Tracking protocol and a no-op implementation.

The ``Tracker`` protocol is owned by ``core.interfaces.tracking``; this module
provides the ``NullTracker`` convenience implementation.
"""
from __future__ import annotations

from typing import Any

from ..contracts.metrics import MetricResult
from ..interfaces.tracking import Tracker
from .run_id import RunId


class NullTracker:
    """Discards everything; used when persistence is disabled."""

    def start_run(
        self,
        run_id: str | RunId,
        *,
        meta: dict[str, Any] | None = None,
    ) -> None:
        """Discard run start."""
        pass

    def log_metric(self, run_id: str | RunId, metric: MetricResult) -> None:
        """Discard a metric result."""
        pass

    def log_instance(
        self,
        run_id: str | RunId,
        instance_id: str,
        prediction: dict[str, Any],
        gold: dict[str, Any] | None = None,
    ) -> None:
        """Discard an instance record."""
        pass

    def finish_run(self, run_id: str | RunId) -> None:
        """Discard run finish."""
        pass


__all__ = ["NullTracker", "Tracker"]
