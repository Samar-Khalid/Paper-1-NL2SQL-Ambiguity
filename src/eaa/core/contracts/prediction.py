"""Prediction contract: the model/agent output for a task."""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel, Envelope, Payload
from .visualization import ChartSpec


class PredictionHeader(ContractModel):
    """Header shared by all prediction envelopes."""

    prediction_id: str
    task_id: str | None = None
    created_at: str | None = None
    model_id: str | None = None


class SqlPrediction(Payload):
    """NL2SQL prediction payload."""

    sql: str


class ChartSpecPrediction(Payload):
    """NL2VIS prediction payload: the intended chart specification."""

    chart: ChartSpec
    rationale: str | None = None


class DecisionPrediction(Payload):
    """Future decision-support prediction payload (reserved)."""

    recommendation: str
    rationale: str | None = None


class GenericPrediction(Payload):
    """Catch-all payload for research/future prediction types."""

    value: dict[str, Any] = Field(default_factory=dict)


class PredictionError(ContractModel):
    """A structured failure attached to a prediction envelope."""

    error_type: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class PredictionEnvelope(Envelope[Payload]):
    """Envelope for prediction contracts (type_key matches the source task).

    Always build through the payload registry so ``payload`` is validated as the
    registered model for the envelope's ``type_key``.
    """

    header: PredictionHeader
    error: PredictionError | None = None
