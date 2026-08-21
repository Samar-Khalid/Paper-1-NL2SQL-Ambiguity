"""Evaluation harness: per-instance metric computation and report assembly.

The harness consumes (prediction, gold) envelope pairs, computes the selected
metrics (filtered by ``type_key``), aggregates them, and returns a
``EvaluationReportEnvelope``. It optionally logs instances and metrics to a
``Tracker`` (see ``core.experiments``) so runs leave a reproducible artifact trail.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from ..core.contracts.gold import GoldReferenceEnvelope
from ..core.contracts.metrics import (
    EvaluationReportEnvelope,
    EvaluationReportPayload,
    MetricResult,
    ReviewSummary,
)
from ..core.contracts.prediction import PredictionEnvelope
from ..core.interfaces.tracking import Tracker
from ..core.registry import envelope_for
from .metrics import MetricsRegistry, register_core_metrics


class EvaluationHarness:
    """Computes metrics over prediction/gold pairs and assembles a report."""

    def __init__(
        self,
        registry: MetricsRegistry | None = None,
        *,
        tracker: Tracker | None = None,
    ) -> None:
        self.registry = registry if registry is not None else MetricsRegistry()
        register_core_metrics(self.registry)
        self.tracker = tracker

    def evaluate_pairs(
        self,
        *,
        run_id: str,
        dataset_id: str | None,
        split: str | None,
        pairs: Iterable[tuple[PredictionEnvelope, GoldReferenceEnvelope]],
        metric_names: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EvaluationReportEnvelope:
        """Evaluate ``pairs`` and return an ``EvaluationReportEnvelope``.

        Only metrics whose ``type_key`` is ``None`` or matches the prediction's
        ``type_key`` are applied to an instance. Aggregates are means over the
        applied instances, with support counts recorded in ``supports``.
        """
        names = metric_names if metric_names is not None else self.registry.names()
        selected = [self.registry.get(name) for name in names]
        per_instance: list[dict[str, Any]] = []
        values: dict[str, list[float]] = defaultdict(list)
        for prediction, gold in pairs:
            instance_id = prediction.header.prediction_id
            results: list[MetricResult] = []
            for metric in selected:
                if metric.type_key is not None and metric.type_key != prediction.type_key:
                    continue
                result = metric.compute(
                    prediction,
                    gold,
                    context={"dataset_id": dataset_id, "split": split},
                )
                results.append(result)
                values[result.metric_name].append(result.value)
            per_instance.append(
                {
                    "instance_id": instance_id,
                    "task_id": prediction.header.task_id,
                    "type_key": prediction.type_key,
                    "metrics": [result.model_dump() for result in results],
                    "error": (
                        prediction.error.model_dump() if prediction.error is not None else None
                    ),
                }
            )
            if self.tracker is not None:
                self.tracker.log_instance(
                    run_id,
                    instance_id,
                    prediction=prediction.model_dump(mode="json"),
                    gold=gold.model_dump(mode="json"),
                )
        metric_results = [
            MetricResult(
                metric_name=name,
                value=statistics.fmean(samples),
                supports={"n": len(samples)},
            )
            for name, samples in sorted(values.items())
        ]
        if self.tracker is not None:
            for result in metric_results:
                self.tracker.log_metric(run_id, result)
        return self._report(
            run_id=run_id,
            dataset_id=dataset_id,
            split=split,
            per_instance=per_instance,
            metric_results=metric_results,
            metadata=metadata or {},
        )

    def _report(
        self,
        *,
        run_id: str,
        dataset_id: str | None,
        split: str | None,
        per_instance: list[dict[str, Any]],
        metric_results: list[MetricResult],
        metadata: dict[str, Any],
    ) -> EvaluationReportEnvelope:
        payload = EvaluationReportPayload(
            run_id=run_id,
            dataset_id=dataset_id,
            split=split,
            metric_results=metric_results,
            per_instance=per_instance,
            summary=ReviewSummary(
                run_id=run_id,
                num_instances=len(per_instance),
                metrics=metric_results,
            ),
            metadata=metadata,
        )
        envelope = envelope_for(
            EvaluationReportEnvelope,
            "evaluation_report",
            {
                "header": {
                    "run_id": run_id,
                    "dataset_id": dataset_id,
                    "created_at": None,
                },
                "payload": payload,
            },
        )
        return envelope


__all__ = ["EvaluationHarness"]
