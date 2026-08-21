"""RuntimeContext contract: per-session runtime state shared across stages.

The context is the only object that travels through every pipeline stage. It
holds identity, budgets, evaluation mode, and free-form state (keyspaced so
stages/adapters cannot collide), but never the task data itself.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel


class Budget(ContractModel):
    """Resource budgets governing a session or single task."""

    max_llm_calls: int | None = None
    max_llm_tokens: int | None = None
    max_executions: int | None = None
    max_elapsed_seconds: float | None = None
    max_cost_usd: float | None = None


class Turn(ContractModel):
    """One user turn within a session."""

    turn_index: int
    question: str
    task_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class SessionState(ContractModel):
    """Persistable session identity and state."""

    session_id: str
    user_id: str | None = None
    dialect: str | None = None
    created_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeContext(ContractModel):
    """Shared runtime state for one session/task execution.

    ``state`` is a namespaced key-value bag (e.g. ``adapter:myname:something``).
    The keyspace contract is: ``<owner>:<subkey>``. Use pydantic's
    ``model_copy`` / ``from_attributes`` on the immutable contract to add state
    without mutation.
    """

    session: SessionState
    budget: Budget = Field(default_factory=Budget)
    evaluation_mode: bool = False
    turns: list[Turn] = Field(default_factory=list)
    state: dict[str, Any] = Field(default_factory=dict)
