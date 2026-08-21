"""Built-in (dataset-independent) payload registrations.

Only types defined in ``core/contracts`` may be registered here. Dataset/benchmark
payload types are registered by the adapters themselves (ADR-002, ADR-001).
"""
from __future__ import annotations

from ..contracts import (
    ChartSpecGoldReference,
    ChartSpecPrediction,
    DecisionGoldReference,
    DecisionPrediction,
    DecisionTask,
    GenericGoldReference,
    GenericPrediction,
    GenericTask,
    SqlGenerationTask,
    SqlGoldReference,
    SqlPrediction,
    VisualizationTask,
)
from ..contracts.metrics import EvaluationReportPayload
from ..contracts.report import AnalysisReportPayload
from ..contracts.visualization import VisualizationPayload
from .payload_registry import PayloadRegistry

BUILTIN_TYPE_KEYS: dict[str, type] = {
    "nl2sql": SqlGenerationTask,
    "nl2vis": VisualizationTask,
    "decision": DecisionTask,
    "task.generic": GenericTask,
    "prediction.nl2sql": SqlPrediction,
    "prediction.nl2vis": ChartSpecPrediction,
    "prediction.decision": DecisionPrediction,
    "prediction.generic": GenericPrediction,
    "gold.nl2sql": SqlGoldReference,
    "gold.nl2vis": ChartSpecGoldReference,
    "gold.decision": DecisionGoldReference,
    "gold.generic": GenericGoldReference,
    "analysis_report": AnalysisReportPayload,
    "evaluation_report": EvaluationReportPayload,
    "visualization": VisualizationPayload,
}


def register_builtins(payload_registry: PayloadRegistry) -> None:
    """Register the built-in (dataset-independent) payload models."""
    for key, model in BUILTIN_TYPE_KEYS.items():
        payload_registry.register(key, model)
