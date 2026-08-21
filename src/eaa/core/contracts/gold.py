"""Gold-reference contract: the ground truth for a task."""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel, Envelope, Payload
from .visualization import ChartSpec


class GoldHeader(ContractModel):
    """Header shared by all gold-reference envelopes."""

    reference_id: str
    task_id: str | None = None
    dataset_id: str | None = None
    source_split: str | None = None


class SqlGoldReference(Payload):
    """NL2SQL gold reference payload."""

    sql: str


class ChartSpecGoldReference(Payload):
    """NL2VIS gold reference payload: the expected chart specification."""

    chart: ChartSpec
    rationale: str | None = None


class DecisionGoldReference(Payload):
    """Future decision-support gold reference payload (reserved)."""

    recommendation: str
    rationale: str | None = None


class GenericGoldReference(Payload):
    """Catch-all payload for research/future gold-reference types."""

    value: dict[str, Any] = Field(default_factory=dict)


class GoldReferenceEnvelope(Envelope[Payload]):
    """Envelope for gold-reference contracts (type_key matches the source task).

    Always build through the payload registry so ``payload`` is validated as the
    registered model for the envelope's ``type_key``.
    """

    header: GoldHeader
