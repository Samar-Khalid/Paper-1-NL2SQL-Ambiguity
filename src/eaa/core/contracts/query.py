"""Query result contract produced by SQL execution."""
from __future__ import annotations

from typing import Any

from .base import ContractModel


class QueryColumn(ContractModel):
    """A result column."""

    name: str
    data_type: str | None = None


class QueryResult(ContractModel):
    """The executed result of a query.

    Rows are row-major lists of JSON-safe values. The executed SQL and latency
    are carried for provenance and reliability metrics.
    """

    columns: list[QueryColumn]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False
    latency_ms: float | None = None
    sql: str | None = None
    error: str | None = None
