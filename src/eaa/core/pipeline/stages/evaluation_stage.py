"""Evaluation stage: pair a prediction with its gold and record a report.

Offline and dataset-independent (ADR-009): gold is reachable only through the
injected ``gold_for`` callable, the harness consumes (prediction, gold) pairs,
and tasks never carry gold. The stage stores the ``EvaluationReportEnvelope``
in state; it does not alter the prediction.
"""
from __future__ import annotations

from collections.abc import Callable

from eaa.core.contracts.errors import PipelineError
from eaa.core.contracts.gold import GoldReferenceEnvelope
from eaa.core.contracts.prediction import PredictionEnvelope
from eaa.core.contracts.runtime import RuntimeContext
from eaa.core.contracts.task import TaskEnvelope
from eaa.evaluation.harness import EvaluationHarness

from ..stage import OUTPUT_KEY, REPORT_KEY, get_state, set_state


class EvaluationStage:
    """Stage 4: evaluate one (prediction, gold) pair and record the report."""

    name = "evaluation"

    def __init__(
        self,
        gold_for: Callable[[str], GoldReferenceEnvelope],
        *,
        harness: EvaluationHarness | None = None,
        run_id: str | None = None,
    ) -> None:
        self._gold_for = gold_for
        self._harness = harness if harness is not None else EvaluationHarness()
        self._run_id = run_id

    def run(self, context: RuntimeContext, task: TaskEnvelope) -> TaskEnvelope:
        """Evaluate the prediction against its gold and store the report."""
        prediction = get_state(context, OUTPUT_KEY)
        if not isinstance(prediction, PredictionEnvelope):
            raise PipelineError(
                f"no prediction in state under '{OUTPUT_KEY}'; evaluation "
                "must run after the generation stage"
            )
        gold = self._gold_for(task.header.task_id)
        report = self._harness.evaluate_pairs(
            run_id=self._run_id or context.session.session_id,
            dataset_id=task.header.dataset_id,
            split=gold.header.source_split,
            pairs=[(prediction, gold)],
        )
        set_state(context, REPORT_KEY, report)
        return task
