"""Metrics and evaluation-report contracts (dataset-independent).

Metric computation is *registered per type_key* in the metrics registry; the
core only transports the results. Concrete metric logic lives in
``evaluation/`` and dataset adapters.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel, Envelope, Payload


class MetricResult(ContractModel):
    """The value of a single metric for a single (task, prediction, gold) triple."""

    metric_name: str
    type_key: str | None = None
    value: float
    supports: dict[str, Any] = Field(default_factory=dict)


class ReviewSummary(ContractModel):
    """Short summary section for a run."""

    run_id: str
    num_instances: int
    metrics: list[MetricResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EvaluationReportPayload(Payload):
    """The body of an evaluation report (dataset-independent)."""

    run_id: str
    dataset_id: str | None = None
    split: str | None = None
    metric_results: list[MetricResult] = Field(default_factory=list)
    per_instance: list[dict[str, Any]] = Field(default_factory=list)
    summary: ReviewSummary | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationReportHeader(ContractModel):
    """Header shared by all evaluation-report envelopes."""

    run_id: str
    dataset_id: str | None = None
    created_at: str | None = None


class EvaluationReportEnvelope(Envelope[Payload]):
    """Envelope for evaluation reports (type_key: ``evaluation_report``)."""

    header: EvaluationReportHeader
