"""Typed errors for the enterprise metadata layer."""
from __future__ import annotations

from eaa.core.contracts.errors import EAAError


class MetadataError(EAAError):
    """Enrichment data or an enriched schema was invalid.

    Raised by ``eaa.metadata`` when enrichment *data* does not line up with the
    schema it describes (unknown table/column references, mismatched database
    id). It is a data-integrity error, distinct from ``AdapterError`` (raw data
    loading) — the enrichment layer validates the document it was given.
    """


__all__ = ["MetadataError"]
