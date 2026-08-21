"""Pipeline runner: ordered stages, budget enforcement, and tracing."""
from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from ..contracts.errors import BudgetExceededError, PipelineError
from ..contracts.runtime import Budget, RuntimeContext, SessionState
from ..contracts.task import TaskEnvelope
from .stage import (
    BUDGET_LEDGER_KEY,
    BudgetLedger,
    PipelineResult,
    Stage,
    StepResult,
)


def _json_safe(value: Any) -> Any:
    """Recursively strip non-JSON-safe values (budget ledgers, models)."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


class Pipeline:
    """Runs an ordered list of stages over one task with budget enforcement.

    The runner seeds ``context.state[BUDGET_LEDGER_KEY]`` with a ``BudgetLedger``,
    checks the ledger after every stage, records per-stage timing/failure, and
    snapshots the final (JSON-safe) context state on the result.
    """

    def __init__(
        self,
        stages: Sequence[Stage],
        *,
        budget: Budget | None = None,
        fail_fast: bool = True,
    ) -> None:
        names = [stage.name for stage in stages]
        if len(names) != len(set(names)):
            raise PipelineError("pipeline stages must have unique names")
        self.stages = list(stages)
        self.budget = budget if budget is not None else Budget()
        self.fail_fast = fail_fast

    def run(
        self,
        task: TaskEnvelope,
        *,
        session: SessionState | None = None,
    ) -> PipelineResult:
        """Run all stages over ``task`` and return a ``PipelineResult``."""
        context = RuntimeContext(
            session=session if session is not None else SessionState(session_id="local"),
            budget=self.budget,
        )
        ledger = BudgetLedger(self.budget)
        context = context.model_copy(
            update={"state": {**context.state, BUDGET_LEDGER_KEY: ledger}}
        )
        steps: list[StepResult] = []
        current = task
        for stage in self.stages:
            started = time.perf_counter()
            try:
                current = stage.run(context, current)
                if not isinstance(current, TaskEnvelope):
                    raise PipelineError(
                        f"stage '{stage.name}' must return a TaskEnvelope, got "
                        f"{type(current).__name__}"
                    )
                ledger.check()
                steps.append(
                    StepResult(
                        stage=stage.name,
                        ok=True,
                        elapsed_ms=(time.perf_counter() - started) * 1000.0,
                    )
                )
            except BudgetExceededError as exc:
                steps.append(
                    StepResult(
                        stage=stage.name,
                        ok=False,
                        error=f"BudgetExceededError: {exc}",
                        elapsed_ms=(time.perf_counter() - started) * 1000.0,
                    )
                )
                return self._result(task, steps, context, ledger, ok=False, error=str(exc))
            except Exception as exc:  # stage raised; abort if fail_fast
                steps.append(
                    StepResult(
                        stage=stage.name,
                        ok=False,
                        error=f"{type(exc).__name__}: {exc}",
                        elapsed_ms=(time.perf_counter() - started) * 1000.0,
                    )
                )
                if self.fail_fast:
                    return self._result(task, steps, context, ledger, ok=False, error=str(exc))
        return self._result(task, steps, context, ledger, ok=True)

    @staticmethod
    def _result(
        task: TaskEnvelope,
        steps: list[StepResult],
        context: RuntimeContext,
        ledger: BudgetLedger,
        *,
        ok: bool,
        error: str | None = None,
    ) -> PipelineResult:
        snapshot = {key: _json_safe(value) for key, value in context.state.items()}
        snapshot.pop(BUDGET_LEDGER_KEY, None)
        return PipelineResult(
            task_id=task.header.task_id,
            steps=steps,
            ok=ok,
            error=error,
            budget=ledger.budget,
            llm_calls=ledger.llm_calls,
            llm_tokens=ledger.llm_tokens,
            executions=ledger.executions,
            state=snapshot,
        )


def run_pipeline(
    task: TaskEnvelope,
    stages: Sequence[Stage],
    *,
    budget: Budget | None = None,
    session: SessionState | None = None,
) -> PipelineResult:
    """Build a ``Pipeline`` and run one task."""
    return Pipeline(stages, budget=budget).run(task, session=session)


__all__ = ["Pipeline", "run_pipeline"]
