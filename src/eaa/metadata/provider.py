"""Schema provider composition: expose enriched schemas to the pipeline.

``EnrichedSchemaProvider`` wraps a base ``SchemaProvider`` and a
``MetadataProvider`` and returns an ``EnrichedSchema`` when enrichment exists,
otherwise the base schema unchanged. The pipeline therefore stays ignorant of
metadata: the *injected* schema provider already resolves it (the controlled
experiment flips which provider is injected — metadata OFF uses the base
provider, metadata ON uses this wrapper).
"""
from __future__ import annotations

from eaa.core.contracts.schema import DatabaseSchema, EnrichedSchema
from eaa.core.interfaces.metadata import MetadataProvider
from eaa.core.interfaces.schema import SchemaProvider

from .enrichment import enrich_schema


class EnrichedSchemaProvider:
    """A ``SchemaProvider`` that enriches every resolved schema on the fly.

    ``get_schema`` returns the base schema unchanged when the metadata source
    has no entry for the database (graceful degradation), so a run configured
    with enrichment but lacking a sidecar still produces valid base prompts.
    """

    def __init__(self, base: SchemaProvider, metadata: MetadataProvider) -> None:
        self._base = base
        self._metadata = metadata

    def get_schema(self, database_id: str) -> DatabaseSchema:
        """Return the enriched schema when metadata exists, else the base."""
        schema = self._base.get_schema(database_id)
        enrichment = self._metadata.metadata(database_id)
        if enrichment is None:
            return schema
        return enrich_schema(schema, enrichment)

    def get_enriched_schema(self, database_id: str) -> EnrichedSchema | None:
        """Return the enriched schema, or None when no enrichment exists."""
        schema = self._base.get_schema(database_id)
        enrichment = self._metadata.metadata(database_id)
        if enrichment is None:
            return None
        return enrich_schema(schema, enrichment)


__all__ = ["EnrichedSchemaProvider"]
