"""Surface B candidate selection (docs/19 §5.1, M1.5).

Builds the deterministic, gold-free candidate pool for the first annotation
batch from the benchmark adapter's dev split: every question is scored with the
transparent structural/textual signals in ``signals.py`` and the pool is
written to ``data/annotations/surface_b/candidates.json``. The pool is a
screening surface for human annotators; it contains no labels and no gold
fields.
"""
from __future__ import annotations

from .errors import CandidateSelectionError
from .selection import (
    GOLD_FIELDS,
    CandidatePool,
    CandidateRecord,
    build_candidate_pool,
    candidate_to_dict,
    load_candidates,
    write_candidates,
)
from .signals import (
    CANDIDATE_SCHEMA_VERSION,
    SIGNALS,
    SIGNALS_BY_ID,
    Signal,
    SignalHit,
    SignalScorer,
    evaluate_question,
)

__all__ = [
    "CANDIDATE_SCHEMA_VERSION",
    "CandidatePool",
    "CandidateRecord",
    "CandidateSelectionError",
    "GOLD_FIELDS",
    "SIGNALS",
    "SIGNALS_BY_ID",
    "Signal",
    "SignalHit",
    "SignalScorer",
    "build_candidate_pool",
    "candidate_to_dict",
    "evaluate_question",
    "load_candidates",
    "write_candidates",
]
