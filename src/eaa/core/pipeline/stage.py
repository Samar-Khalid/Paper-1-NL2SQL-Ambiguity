"""Pipeline stage contracts, budget accounting, and run results."""
from __future__ import annotations

import time
from typing import Any, Protocol

from pydantic import Field

from ..contracts.base import ContractModel
from ..contracts.errors import BudgetExceededError, PipelineError
from ..contracts.runtime import Budget, RuntimeContext
from ..contracts.task import TaskEnvelope

#: Reserved, namespaced state key holding a serialized ``AmbiguityAnalysis``
#: and, after resolution, the ``ClarifiedQuestion`` (or an unanswerable
#: ``AnswerabilityVerdict``) produced by the ambiguity_resolution stage
#: (ADR-014; written only when ``AmbiguityConfig.resolution`` is not ``off``).
AMBIGUITY_KEY = "core:pipeline:ambiguity"

#: Reserved, namespaced state key holding the per-run ``BudgetLedger``.
BUDGET_LEDGER_KEY = "core:pipeline:budget_ledger"

#: Reserved, namespaced state key holding the pipeline's final prediction
#: (a serialized ``PredictionEnvelope``) once a generating stage has run.
OUTPUT_KEY = "core:pipeline:output"

#: Reserved, namespaced state key holding the built prompt as
#: ``{"messages", "prompt_version", "schema_tables", "metadata_enriched"}``.
#: ``prompt_version`` is ``baseline-v1`` or ``enriched-v1`` (ADR-004/ADR-015);
#: ``metadata_enriched`` flags which variant was rendered.
PROMPT_KEY = "core:pipeline:prompt"

#: Reserved, namespaced state key holding the LLM generation trace as
#: ``{"model_id", "sql", "total_tokens", "finish_reason"}``.
GENERATION_KEY = "core:pipeline:generation"

#: Reserved, namespaced state key holding the baseline validation verdict dict.
VALIDATION_KEY = "core:pipeline:validation"

#: Reserved, namespaced state key holding a serialized ``EvaluationReportEnvelope``.
REPORT_KEY = "core:pipeline:report"


class Stage(Protocol):
    """One typed, dataset-independent pipeline step.

    A stage transforms a ``TaskEnvelope`` (usually returning it unchanged) and
    records its outputs in ``context.state`` under a keyspaced key
    (``<owner>:<subkey>``). Stages that spend budget must report it through the
    ``BudgetLedger`` found via :func:`get_budget_ledger`.
    """

    name: str

    def run(self, context: RuntimeContext, task: TaskEnvelope) -> TaskEnvelope:
        """Run one stage for ``task``, returning the (possibly updated) task."""
        ...


class StepResult(ContractModel):
    """Outcome of one pipeline stage for one task."""

    stage: str
    ok: bool
    elapsed_ms: float | None = None
    error: str | None = None


class PipelineResult(ContractModel):
    """Outcome of a full pipeline run over one task."""

    task_id: str
    steps: list[StepResult] = Field(default_factory=list)
    ok: bool = False
    error: str | None = None
    budget: Budget = Field(default_factory=Budget)
    llm_calls: int = 0
    llm_tokens: int = 0
    executions: int = 0
    state: dict[str, Any] = Field(default_factory=dict)


class BudgetLedger:
    """Mutable budget accounting for one pipeline run.

    The runner stores the ledger in ``context.state[BUDGET_LEDGER_KEY]``. Stages
    report spending through it; the runner calls :meth:`check` after every stage
    and raises ``BudgetExceededError`` when a limit is crossed.
    """

    def __init__(self, budget: Budget) -> None:
        self._budget = budget
        self.llm_calls = 0
        self.llm_tokens = 0
        self.executions = 0
        self._started_at = time.perf_counter()

    @property
    def budget(self) -> Budget:
        """Return the immutable budget limits this ledger enforces."""
        return self._budget

    def spend_llm_calls(self, n: int = 1) -> None:
        """Account for ``n`` LLM call(s)."""
        self.llm_calls += n

    def spend_llm_tokens(self, n: int) -> None:
        """Account for ``n`` LLM token(s)."""
        self.llm_tokens += n

    def spend_executions(self, n: int = 1) -> None:
        """Account for ``n`` query execution(s)."""
        self.executions += n

    @property
    def elapsed_seconds(self) -> float:
        """Return seconds since the ledger was created."""
        return time.perf_counter() - self._started_at

    def check(self) -> None:
        """Raise ``BudgetExceededError`` if any configured limit was exceeded."""
        limits = self._budget
        if limits.max_llm_calls is not None and self.llm_calls > limits.max_llm_calls:
            raise BudgetExceededError(
                f"LLM call budget exceeded: {self.llm_calls} > {limits.max_llm_calls}"
            )
        if limits.max_llm_tokens is not None and self.llm_tokens > limits.max_llm_tokens:
            raise BudgetExceededError(
                f"LLM token budget exceeded: {self.llm_tokens} > {limits.max_llm_tokens}"
            )
        if limits.max_executions is not None and self.executions > limits.max_executions:
            raise BudgetExceededError(
                f"execution budget exceeded: {self.executions} > {limits.max_executions}"
            )
        if limits.max_cost_usd is not None:
            raise BudgetExceededError(
                f"cost budget is not accounted for yet (max_cost_usd={limits.max_cost_usd})"
            )
        if limits.max_elapsed_seconds is not None:
            elapsed = self.elapsed_seconds
            if elapsed > limits.max_elapsed_seconds:
                raise BudgetExceededError(
                    f"elapsed budget exceeded: {elapsed:.2f}s > {limits.max_elapsed_seconds}s"
                )


def get_budget_ledger(context: RuntimeContext) -> BudgetLedger:
    """Return the run's ``BudgetLedger`` from ``context.state``.

    Raises
    ------
        PipelineError: if the ledger is absent (stage run outside a runner).
    """
    ledger = context.state.get(BUDGET_LEDGER_KEY)
    if not isinstance(ledger, BudgetLedger):
        raise PipelineError(
            f"no budget ledger in context under {BUDGET_LEDGER_KEY!r}; "
            "run the stage inside a Pipeline"
        )
    return ledger


def set_state(context: RuntimeContext, key: str, value: Any) -> RuntimeContext:
    """Set ``context.state[key]`` in place and return ``context``.

    ``state`` is the runtime's namespaced key-value bag (``<owner>:<subkey>``)
    and is the intended mutable extension point: stages write their artifacts
    here and the runner snapshots them at the end. A fresh ``RuntimeContext`` is
    created per pipeline run, so there is no cross-run aliasing.
    """
    context.state[key] = value
    return context


def get_state(context: RuntimeContext, key: str, default: Any = None) -> Any:
    """Return ``context.state[key]``, or ``default`` when absent."""
    return context.state.get(key, default)


__all__ = [
    "AMBIGUITY_KEY",
    "BUDGET_LEDGER_KEY",
    "GENERATION_KEY",
    "OUTPUT_KEY",
    "PROMPT_KEY",
    "REPORT_KEY",
    "VALIDATION_KEY",
    "BudgetLedger",
    "PipelineResult",
    "Stage",
    "StepResult",
    "get_budget_ledger",
    "get_state",
    "set_state",
]
