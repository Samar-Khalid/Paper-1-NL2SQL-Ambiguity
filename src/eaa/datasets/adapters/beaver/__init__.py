"""BEAVER benchmark adapter (Phase 1 — NL2SQL, Chen et al., arXiv:2409.02038).

Implements the core ``DatasetAdapter`` + ``BenchmarkAdapter`` interfaces
(ADR-002/006). All BEAVER-specific knowledge lives here; the core never imports
this package (enforced by the conformance import guard).

The adapter is discovered through the ``eaa.datasets`` entry-point group::

    [project.entry-points."eaa.datasets"]
    beaver = "eaa.datasets.adapters.beaver:plugin"

``plugin()`` is a zero-arg-compatible factory (it also accepts an optional
``root`` so an experiment driver can point it at ``dataset.data_root``). It
defaults to ``EAA_BEAVER_DATA_ROOT`` or the repo-default ``data/raw/beaver``;
data access is lazy and verified, so a plugin without data only fails (with
setup guidance) when a data method is used.
"""
from __future__ import annotations

from pathlib import Path

from .adapter import BeaverAdapter, BeaverSchemaProvider
from .manifest import BEAVER_DATA_VERSION, default_data_root
from .metadata import BeaverMetadataProvider

__all__ = [
    "BEAVER_DATA_VERSION",
    "BeaverAdapter",
    "BeaverMetadataProvider",
    "BeaverSchemaProvider",
    "default_data_root",
    "plugin",
]


def plugin(root: str | Path | None = None) -> BeaverAdapter:
    """Entry-point factory (zero-arg compatible) returning a ``BeaverAdapter``.

    ``root`` lets an experiment driver point the adapter at a configured data
    root (e.g. ``dataset.data_root``); with no argument the env/repo default
    applies.
    """
    return BeaverAdapter(root=root)
