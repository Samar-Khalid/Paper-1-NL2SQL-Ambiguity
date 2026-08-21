"""Task contract: the envelope and header for any analysis request."""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel, Envelope, Payload


class TaskHeader(ContractModel):
    """Header shared by all task envelopes."""

    task_id: str
    question: str
    dataset_id: str | None = None
    dialect: str | None = None
    tags: list[str] = Field(default_factory=list)


class SqlGenerationTask(Payload):
    """NL2SQL task payload: turn a question into an executable SQL query."""

    question: str
    database_id: str
    schema_id: str | None = None
    allowed_tables: list[str] | None = None


class VisualizationTask(Payload):
    """NL2VIS task payload: turn a question into an executable chart."""

    question: str
    dataset_id: str
    allowed_tables: list[str] | None = None
    preference: str | None = None


class DecisionTask(Payload):
    """Future decision-support task payload (reserved; not in scope for M0-M2)."""

    question: str
    context: dict[str, Any] = Field(default_factory=dict)


class GenericTask(Payload):
    """Catch-all payload for research/future task types.

    Prefer a dedicated registered payload type over ``GenericTask``.
    """

    question: str
    raw: dict[str, Any] = Field(default_factory=dict)


class TaskEnvelope(Envelope[Payload]):
    """Envelope for task contracts (type_key: ``nl2sql``, ``nl2vis``, ``decision``, ...).

    Always build through the payload registry so ``payload`` is validated as the
    registered model for the envelope's ``type_key``.
    """

    header: TaskHeader
