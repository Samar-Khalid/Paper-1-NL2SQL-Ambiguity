"""BEAVER adapter metadata sidecar: publish enrichment data as a core contract.

Enrichment is *data* (ADR-015): the adapter reads an optional per-database
``enrichment.json`` file from the data root and validates it into the generic
``EnrichmentData`` core contract. It never merges anything itself — the
``metadata/`` module owns the merge into an ``EnrichedSchema`` (R2: adapters
import only core interfaces/contracts/configuration helpers). When no sidecar
file exists, ``metadata()`` returns ``None`` and the enrichment layer degrades
to the base schema.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from eaa.core.contracts.errors import AdapterError
from eaa.core.contracts.schema import EnrichmentData

#: Canonical sidecar filename first, then accepted aliases.
METADATA_FILES = ("enrichment.json", "metadata.json")


def load_enrichment(root: Path, db_id: str) -> EnrichmentData | None:
    """Load the enrichment sidecar for one database, or ``None`` when absent.

    The sidecar is validated against the generic ``EnrichmentData`` contract and
    its ``database_id`` must match ``db_id`` (guards against a file dropped into
    the wrong warehouse directory).

    Raises
    ------
        AdapterError: if the sidecar exists but is invalid JSON or fails
            contract validation.
    """
    db_dir = root / db_id
    path = next(
        (db_dir / name for name in METADATA_FILES if (db_dir / name).is_file()),
        None,
    )
    if path is None:
        return None
    return _parse_enrichment(path, db_id)


def _parse_enrichment(path: Path, db_id: str) -> EnrichmentData:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AdapterError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise AdapterError(f"{path} must contain a JSON object")
    recorded = raw.get("database_id")
    if recorded is not None and recorded != db_id:
        raise AdapterError(
            f"{path} records database_id {recorded!r} but sits in database "
            f"directory {db_id!r}"
        )
    raw["database_id"] = db_id
    try:
        return EnrichmentData.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError; keep AdapterError stable
        raise AdapterError(f"{path} is not a valid enrichment sidecar: {exc}") from exc


class BeaverMetadataProvider:
    """Per-warehouse ``MetadataProvider`` backed by loaded sidecar documents."""

    def __init__(self, enrichment: Mapping[str, EnrichmentData]) -> None:
        self._enrichment = dict(enrichment)

    def metadata(self, database_id: str) -> EnrichmentData | None:
        """Return the enrichment document for one warehouse, or None."""
        return self._enrichment.get(database_id)


__all__ = ["BeaverMetadataProvider", "METADATA_FILES", "load_enrichment"]
