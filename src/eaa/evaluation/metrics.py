"""Metric registry and built-in (dataset-independent) metrics.

Concrete metric logic lives here and in dataset adapters (ADR-002). The core
only transports ``MetricResult`` objects; adapters register their metrics by
name so the harness never switches on concrete metric classes.
"""
from __future__ import annotations

import re
from typing import Any

from ..core.contracts.errors import RegistryError
from ..core.contracts.gold import GoldReferenceEnvelope
from ..core.contracts.metrics import MetricResult
from ..core.contracts.prediction import PredictionEnvelope
from ..core.interfaces.metrics import Metric

_WS = re.compile(r"\s+")


def _normalize_sql(sql: str) -> str:
    """Normalize a SQL string for exact-match comparison (whitespace + casing)."""
    return _WS.sub(" ", sql).strip().lower()


def _sql_of(envelope: PredictionEnvelope | GoldReferenceEnvelope) -> str | None:
    """Return ``.sql`` from a SQL-bearing payload, else ``None``."""
    payload = getattr(envelope, "payload", None)
    sql = getattr(payload, "sql", None)
    return sql if isinstance(sql, str) else None


class ExactMatch:
    """String-level exact match of normalized SQL (dataset-independent)."""

    name = "exact_match"
    type_key: str | None = "prediction.nl2sql"

    def compute(
        self,
        prediction: PredictionEnvelope,
        gold: GoldReferenceEnvelope,
        context: dict[str, Any] | None = None,
    ) -> MetricResult:
        """Return 1.0 when normalized predicted and gold SQL are equal."""
        predicted = _sql_of(prediction)
        expected = _sql_of(gold)
        matches = (
            predicted is not None
            and expected is not None
            and _normalize_sql(predicted) == _normalize_sql(expected)
        )
        value = 1.0 if matches else 0.0
        return MetricResult(
            metric_name=self.name,
            type_key=prediction.type_key,
            value=value,
            supports={"predicted_sql": predicted, "gold_sql": expected},
        )


class CleanPredictionRate:
    """Fraction of predictions that are not error envelopes (reliability)."""

    name = "clean_prediction_rate"
    type_key: str | None = None

    def compute(
        self,
        prediction: PredictionEnvelope,
        gold: GoldReferenceEnvelope,
        context: dict[str, Any] | None = None,
    ) -> MetricResult:
        """Return 1.0 when the prediction carries no structured error."""
        return MetricResult(
            metric_name=self.name,
            type_key=prediction.type_key,
            value=1.0 if prediction.error is None else 0.0,
            supports={"error_type": prediction.error.error_type if prediction.error else None},
        )


CORE_METRICS: list[Metric] = [ExactMatch(), CleanPredictionRate()]


class MetricsRegistry:
    """Maps ``name`` -> ``Metric`` implementation.

    Keys are metric names (``exact_match``, ...); dataset-specific metrics are
    registered by adapters under their own names (e.g. ``beaver:ves_score``).
    """

    def __init__(self) -> None:
        self._metrics: dict[str, Metric] = {}

    def register(self, metric: Metric, *, replace: bool = False) -> None:
        """Register ``metric`` under its ``name``.

        Raises
        ------
            RegistryError: if the name is already bound and ``replace`` is False.
        """
        if metric.name in self._metrics and not replace:
            raise RegistryError(f"metric '{metric.name}' is already registered")
        self._metrics[metric.name] = metric

    def get(self, name: str) -> Metric:
        """Return the metric registered under ``name``.

        Raises
        ------
            RegistryError: if the name is not registered.
        """
        try:
            return self._metrics[name]
        except KeyError:
            raise RegistryError(f"metric '{name}' is not registered") from None

    def names(self) -> list[str]:
        """Return the sorted registered metric names."""
        return sorted(self._metrics)

    def __contains__(self, name: str) -> bool:
        """Return whether ``name`` is registered."""
        return name in self._metrics


def register_core_metrics(registry: MetricsRegistry) -> None:
    """Register the built-in dataset-independent metrics (idempotent)."""
    for metric in CORE_METRICS:
        if metric.name not in registry:
            registry.register(metric)


def register_metric(metric: Metric) -> None:
    """Register ``metric`` on the default registry (convenience for plugins)."""
    default_metrics_registry().register(metric)


_default_registry: MetricsRegistry | None = None


def default_metrics_registry() -> MetricsRegistry:
    """Return the process-wide default metrics registry (seeded with core)."""
    global _default_registry
    if _default_registry is None:
        _default_registry = MetricsRegistry()
        register_core_metrics(_default_registry)
    return _default_registry


__all__ = [
    "CORE_METRICS",
    "CleanPredictionRate",
    "ExactMatch",
    "MetricsRegistry",
    "default_metrics_registry",
    "register_core_metrics",
    "register_metric",
]
