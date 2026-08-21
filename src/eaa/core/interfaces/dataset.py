"""Dataset adapter protocols — the dataset-independence boundary.

Concrete implementations live ONLY in ``eaa.datasets.adapters.<name>``.
The core, pipeline, and evaluation harness interact with datasets exclusively
through these protocols (ADR-002, ADR-001).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from ..contracts import DatasetManifest
from ..contracts.gold import GoldReferenceEnvelope
from ..contracts.schema import DatabaseSchema
from ..contracts.task import TaskEnvelope


class DatasetAdapter(Protocol):
    """Reads schema and manifest for one dataset (data source)."""

    name: str

    def schema(self) -> DatabaseSchema:
        """Return the database schema for this dataset."""
        ...

    def manifest(self) -> DatasetManifest:
        """Return the self-description manifest for this dataset."""
        ...


class BenchmarkAdapter(DatasetAdapter, Protocol):
    """Reads tasks and gold references for one benchmark split."""

    def task_stream(self, split: str | None = None) -> AsyncIterator[TaskEnvelope]:
        """Yield task envelopes, optionally filtered by split."""
        ...

    def gold_for(self, task_id: str) -> GoldReferenceEnvelope:
        """Return the gold reference for a task id."""
        ...

    def splits(self) -> list[str]:
        """Return the available split names."""
        ...


__all__ = ["BenchmarkAdapter", "DatasetAdapter"]
