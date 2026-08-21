"""Schema provider protocol."""
from __future__ import annotations

from typing import Protocol

from ..contracts.schema import DatabaseSchema, EnrichedSchema


class SchemaProvider(Protocol):
    """Provides the schema for a database id.

    An ``EnrichedSchema`` *is a* ``DatabaseSchema``, so providers may return
    either; enrichment is an extension, not a parallel model.
    """

    def get_schema(self, database_id: str) -> DatabaseSchema:
        """Return the (possibly enriched) schema for ``database_id``."""
        ...

    def get_enriched_schema(self, database_id: str) -> EnrichedSchema | None:
        """Return the enriched schema, or None when no enrichment exists."""
        ...


__all__ = ["SchemaProvider"]
