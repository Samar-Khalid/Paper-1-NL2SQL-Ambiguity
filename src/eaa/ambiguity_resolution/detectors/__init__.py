"""Ambiguity detectors (docs/14).

The detector is organized as two evidence families (docs/14 §4). M1.5 slice 2.8
shipped the first family — the deterministic, metadata-grounded
``MetadataGroundedDetector`` that establishes the metadata-closable band for the
seven enrichment-resolvable taxonomy types (L2, R1, V1, V2, V3, T2, K2). M1.5
slice 2.9 adds the second family — the model-based ``ReasoningBasedDetector``
that establishes the persistent-ambiguity band for the ten types metadata
cannot close (S1, S2, R2, C1, C2, C3, T1, K1, I2, I3), obtained through the
existing ``LLMBackend`` protocol with run-ledger budget accounting.
"""
from __future__ import annotations

from .metadata_grounded import (
    METADATA_GROUNDED_TYPES,
    MetadataGroundedDetector,
)
from .reasoning_based import (
    REASONING_TYPES,
    SYSTEM_PROMPT,
    ReasoningBasedDetector,
)

__all__ = [
    "METADATA_GROUNDED_TYPES",
    "MetadataGroundedDetector",
    "REASONING_TYPES",
    "ReasoningBasedDetector",
    "SYSTEM_PROMPT",
]
