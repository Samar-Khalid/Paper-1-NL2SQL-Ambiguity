"""Baseline NL2SQL pipeline assembly helpers (dataset-independent).

Convenience glue over :class:`BaselinePipelineBuilder` for drivers, tests, and
experiment scripts. The pipeline consumes only core contracts and injected
collaborators, so it is interchangeable across dataset adapters.
"""
from __future__ import annotations

from collections.abc import Callable

from eaa.evaluation.harness import EvaluationHarness

from ..contracts.gold import GoldReferenceEnvelope
from ..contracts.runtime import Budget
from ..interfaces.llm import LLMBackend
from ..interfaces.schema import SchemaProvider
from .builder import BaselinePipelineBuilder
from .runner import Pipeline
from .stages.prompt_builder import PROMPT_VERSION


def build_baseline_pipeline(
    llm: LLMBackend,
    schema_provider: SchemaProvider,
    *,
    gold_for: Callable[[str], GoldReferenceEnvelope] | None = None,
    harness: EvaluationHarness | None = None,
    run_id: str | None = None,
    prompt_version: str = PROMPT_VERSION,
    budget: Budget | None = None,
) -> Pipeline:
    """Build the baseline NL2SQL pipeline for a dataset adapter's tasks.

    Parameters
    ----------
    llm : LLMBackend
        Backend used for SQL generation (injected, provider-agnostic).
    schema_provider : SchemaProvider
        Resolves each task's ``database_id`` to a ``DatabaseSchema``.
    gold_for : callable, optional
        Maps a task id to its ``GoldReferenceEnvelope``; when provided, an
        evaluation stage is appended (offline, ADR-009).
    harness, run_id, prompt_version, budget : optional
        Evaluation harness, run identity, prompt version, and run budget.

    Returns
    -------
    Pipeline
        A runnable ``Pipeline`` over the composed baseline stages.
    """
    return BaselinePipelineBuilder(
        llm=llm,
        schema_provider=schema_provider,
        gold_for=gold_for,
        harness=harness,
        run_id=run_id,
        prompt_version=prompt_version,
    ).build(budget=budget)
