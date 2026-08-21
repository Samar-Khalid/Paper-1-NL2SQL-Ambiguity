"""Metric protocol."""
from __future__ import annotations

from typing import Any, Protocol

from ..contracts.gold import GoldReferenceEnvelope
from ..contracts.metrics import MetricResult
from ..contracts.prediction import PredictionEnvelope


class Metric(Protocol):
    """Computes one named metric for a (prediction, gold) pair.

    Metric implementations are registered in the metrics registry under
    ``<owner>:<name>``; the evaluation harness invokes them by name.
    """

    name: str
    type_key: str | None = None

    def compute(
        self,
        prediction: PredictionEnvelope,
        gold: GoldReferenceEnvelope,
        context: dict[str, Any] | None = None,
    ) -> MetricResult:
        """Compute the metric value for the prediction/gold pair."""
        ...


__all__ = ["Metric"]
