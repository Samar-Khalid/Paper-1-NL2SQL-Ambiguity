"""Evaluator protocol."""
from __future__ import annotations

from typing import Protocol

from ..contracts.metrics import EvaluationReportEnvelope


class Evaluator(Protocol):
    """Runs a benchmark and produces an evaluation report.

    Implementations live in ``eaa.evaluation`` and consume the contracts.
    """

    def evaluate(
        self,
        *,
        run_id: str,
        dataset_id: str,
        split: str | None = None,
        limit: int | None = None,
    ) -> EvaluationReportEnvelope:
        """Evaluate predictions for ``dataset_id`` and return a report."""
        ...


__all__ = ["Evaluator"]
