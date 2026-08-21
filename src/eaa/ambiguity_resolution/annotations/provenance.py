"""Option B provenance sidecar for Surface B labels (docs/19 §8).

The sidecar is ``provenance-v1``: one JSON object per ``question_id`` living
next to the label files, included in the freeze hash. It is **never
populated** by this slice: annotator identities, third-annotator ids, and
adjudication records are real human measurements, and the enrichment snapshot
token is derived only from a legitimate per-database ``enrichment.json`` when
one exists.

Enrichment rule (docs/19 §8): ``token = sha256(<exact enrichment.json
bytes>)`` for the sidecar the annotators actually consulted. No
``enrichment.json`` exists in this repository today, so the skeleton marks the
snapshot unavailable (``token = null``); the freeze checker refuses any
metadata-grounded label while the snapshot is unavailable. No token is ever
derived from anything else.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import Field

from eaa.core.contracts.base import ContractModel

from ._io import write_json
from .batch import PROTOCOL_VERSION

PROVENANCE_VERSION = "provenance-v1"

#: The documented, reproducible derivation rule (docs/19 §8): the exact bytes
#: of the per-database enrichment file under the raw data root.
ENRICHMENT_TOKEN_DERIVATION = (
    "sha256(<exact bytes of <raw-data-root>/<database_id>/enrichment.json>)"  # noqa: S105
)

#: Sidecar values that are scaffolding, not real measurements.
PLACEHOLDER = "__PLACEHOLDER__"


class EnrichmentSnapshot(ContractModel):
    """Which enrichment build the annotators consulted for a question."""

    database_id: str
    token: str | None = None
    derivation: str = ENRICHMENT_TOKEN_DERIVATION

    @property
    def available(self) -> bool:
        """Whether a real enrichment token is recorded."""
        return bool(self.token)


class Adjudication(ContractModel):
    """Third-senior-annotator record for unresolved disagreements."""

    required: bool = False
    senior_annotator_id: str | None = None
    resolved_span_ids: list[str] = Field(default_factory=list)
    outcome: str | None = None


class ProvenanceSidecar(ContractModel):
    """The Option B sidecar entry for one ``question_id`` (docs/19 §8)."""

    provenance_version: str = PROVENANCE_VERSION
    question_id: str
    annotator_ids: list[str] = Field(default_factory=list)
    third_annotator_id: str | None = None
    protocol_version: str = PROTOCOL_VERSION
    enrichment_snapshot: EnrichmentSnapshot
    adjudication: Adjudication = Field(default_factory=Adjudication)


def build_provenance_skeleton(
    question_ids: Sequence[str],
    *,
    database_id: str,
) -> dict[str, dict[str, Any]]:
    """Build the unpopulated sidecar: one entry per question id.

    The skeleton carries only structure — empty annotator lists, ``null``
    enrichment token, and empty adjudication. It must never be treated as
    provenance data; the freeze checker rejects it as incomplete.
    """
    entries: dict[str, dict[str, Any]] = {}
    for question_id in sorted(set(question_ids)):
        entry = ProvenanceSidecar(
            question_id=question_id,
            annotator_ids=[],
            enrichment_snapshot=EnrichmentSnapshot(
                database_id=database_id, token=None
            ),
            adjudication=Adjudication(),
        )
        entries[question_id] = entry.model_dump()
    return entries


def derive_enrichment_token(
    data_root: Path, database_id: str
) -> tuple[str | None, Path | None]:
    """Compute the enrichment-snapshot token for one database.

    Returns ``(token, path)`` when a legitimate ``enrichment.json`` exists
    under ``data_root/<database_id>/``, else ``(None, None)``. The token is the
    SHA-256 over the exact file bytes (docs/19 §8); nothing is fabricated and
    nothing else is hashed.
    """
    candidate = Path(data_root) / database_id / "enrichment.json"
    if not candidate.is_file():
        return None, None
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return digest, candidate


def load_sidecar(path: str | Path) -> dict[str, dict[str, Any]]:
    """Load a sidecar file as a mapping of question_id to entry dict."""
    import json

    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a provenance sidecar mapping")
    return {str(key): value for key, value in payload.items()}


def write_sidecar(entries: Mapping[str, Any], path: str | Path) -> Path:
    """Write the sidecar mapping deterministically (sorted keys)."""
    return write_json(dict(entries), path)


__all__ = [
    "ENRICHMENT_TOKEN_DERIVATION",
    "Adjudication",
    "EnrichmentSnapshot",
    "PLACEHOLDER",
    "PROVENANCE_VERSION",
    "ProvenanceSidecar",
    "build_provenance_skeleton",
    "derive_enrichment_token",
    "load_sidecar",
    "write_sidecar",
]
