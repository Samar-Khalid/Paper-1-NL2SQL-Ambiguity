"""Enterprise metadata: enriched schemas, synonyms, business terms, hierarchies.

Metadata is data, not code. This module defines the enrichment model and the
lookups that merge enrichment *source* documents (``EnrichmentData``, published
by dataset adapters as a metadata sidecar) into the single schema model
(``EnrichedSchema``). ``enrich_schema`` and ``EnrichedSchemaProvider`` are
dataset-independent: no dataset name, split, or record field appears here.
"""
from __future__ import annotations

from .enrichment import enrich_schema
from .errors import MetadataError
from .provider import EnrichedSchemaProvider

__all__ = [
    "EnrichedSchemaProvider",
    "MetadataError",
    "enrich_schema",
]
