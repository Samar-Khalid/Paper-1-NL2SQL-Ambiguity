"""Experiments: run identity, artifact layout, and tracking.

Every research run gets a ``RunId`` and a deterministic artifact layout under
``experiments/runs/<run_id>/`` so runs are reproducible and comparable.
"""
from __future__ import annotations

from .artifact_store_tracker import ArtifactStoreTracker
from .artifacts import ArtifactStore, default_artifact_root
from .run_id import RunId, generate_run_id
from .tracker import NullTracker, Tracker

__all__ = [
    "ArtifactStore",
    "ArtifactStoreTracker",
    "NullTracker",
    "RunId",
    "Tracker",
    "default_artifact_root",
    "generate_run_id",
]
