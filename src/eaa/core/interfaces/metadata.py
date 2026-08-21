"""Metadata provider protocol: the enrichment-source boundary.

Adapters that ship enterprise metadata publish it as *data* (ADR-015): a
``MetadataProvider`` returns the dataset-independent ``EnrichmentData`` document
for a database, or ``None`` when no enrichment exists. The ``metadata/`` module
owns the merge into an ``EnrichedSchema`` (via ``EnrichedSchemaProvider``); core
only defines the boundary.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..contracts.schema import EnrichmentData


@runtime_checkable
class MetadataProvider(Protocol):
    """Provides enrichment data for a database id (dataset-independent).

    Structural protocol: any object with a ``metadata(database_id)`` method
    satisfies it. Adapters expose it alongside ``SchemaProvider``; ``metadata/``
    composes the two into enriched schemas.
    """

    def metadata(self, database_id: str) -> EnrichmentData | None:
        """Return the enrichment document for ``database_id``, or None."""
        ...


__all__ = ["MetadataProvider"]
