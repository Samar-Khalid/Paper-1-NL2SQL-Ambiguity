"""Tracking protocol for run metrics and instance-level artifacts."""
from __future__ import annotations

from typing import Any, Protocol

from ..contracts.metrics import MetricResult


class Tracker(Protocol):
    """What the evaluation harness and pipeline stages use to record metrics.

    Implementations include ``ArtifactStoreTracker`` (persistence) and
    ``NullTracker`` (discard). Run ids are opaque strings (see
    ``core.experiments.run_id.RunId``).
    """

    def start_run(self, run_id: str, *, meta: dict[str, Any] | None = None) -> None:
        """Begin a run and record its metadata."""
        ...

    def log_metric(self, run_id: str, metric: MetricResult) -> None:
        """Record one metric result for a run."""
        ...

    def log_instance(
        self,
        run_id: str,
        instance_id: str,
        prediction: dict[str, Any],
        gold: dict[str, Any] | None = None,
    ) -> None:
        """Record one (prediction, gold) instance for a run."""
        ...

    def finish_run(self, run_id: str) -> None:
        """Finalize a run."""
        ...


__all__ = ["Tracker"]
