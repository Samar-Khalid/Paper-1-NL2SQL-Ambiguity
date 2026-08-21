"""Pipeline engine: stages, DAG composition, and runner with budget control.

Purpose: compose typed research steps into reproducible pipelines. Stages are
dataset-independent and communicate through the keyspaced ``context.state``;
the runner enforces resource budgets (LLM calls, executions, elapsed time).
"""
from __future__ import annotations

from .runner import Pipeline, run_pipeline
from .stage import (
    BUDGET_LEDGER_KEY,
    GENERATION_KEY,
    OUTPUT_KEY,
    PROMPT_KEY,
    REPORT_KEY,
    VALIDATION_KEY,
    BudgetLedger,
    PipelineResult,
    Stage,
    StepResult,
    get_budget_ledger,
    get_state,
    set_state,
)

__all__ = [
    "BUDGET_LEDGER_KEY",
    "GENERATION_KEY",
    "OUTPUT_KEY",
    "PROMPT_KEY",
    "REPORT_KEY",
    "VALIDATION_KEY",
    "BudgetLedger",
    "Pipeline",
    "PipelineResult",
    "Stage",
    "StepResult",
    "get_budget_ledger",
    "get_state",
    "run_pipeline",
    "set_state",
]
