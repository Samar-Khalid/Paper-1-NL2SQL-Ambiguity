"""Query executor protocol (read-only by default)."""
from __future__ import annotations

from typing import Protocol

from ..contracts.query import QueryResult


class QueryExecutor(Protocol):
    """Executes SQL read-only against a database.

    Implementations MUST enforce the security model (read-only statements,
    timeouts, result-size caps) — see the ``security`` module.
    """

    def execute(
        self,
        sql: str,
        *,
        database_id: str | None = None,
        limit: int | None = None,
    ) -> QueryResult:
        """Execute ``sql`` read-only and return the result."""
        ...


__all__ = ["QueryExecutor"]
