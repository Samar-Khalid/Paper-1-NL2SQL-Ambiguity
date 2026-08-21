"""Schema linking protocol."""
from __future__ import annotations

from typing import Any, Protocol

from ..contracts.schema import DatabaseSchema
from ..contracts.task import TaskEnvelope


class SchemaLinker(Protocol):
    """Links a question to the relevant subset of a schema."""

    def link(
        self,
        task: TaskEnvelope,
        schema: DatabaseSchema,
        context: dict[str, Any] | None = None,
    ) -> list[str]:
        """Return the names of tables relevant to the task."""
        ...


__all__ = ["SchemaLinker"]
