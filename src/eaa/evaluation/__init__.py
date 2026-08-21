"""Evaluation subsystem: metrics, harness, statistics, reports.

Decoupled from prediction. Dataset-specific metrics register from adapters.
"""
from __future__ import annotations

from .harness import EvaluationHarness
from .metrics import (
    CORE_METRICS,
    CleanPredictionRate,
    ExactMatch,
    MetricsRegistry,
    default_metrics_registry,
    register_core_metrics,
    register_metric,
)

__all__ = [
    "CORE_METRICS",
    "CleanPredictionRate",
    "EvaluationHarness",
    "ExactMatch",
    "MetricsRegistry",
    "default_metrics_registry",
    "register_core_metrics",
    "register_metric",
]
