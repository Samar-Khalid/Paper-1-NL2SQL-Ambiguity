"""Ambiguity resolution for enterprise questions (Phase 1, M1.5).

M1.5 slice 1: dataset-independent contracts (``core.contracts.ambiguity``),
protocols (``core.interfaces.ambiguity``), and this module's error type.
M1.5 slice 2: the ``annotations`` subpackage loads and validates
``annotation-schema-v1`` label files into an immutable typed representation and
provides read-only dataset statistics; the ``detectors`` subpackage ships both
evidence families of the ambiguity detector — the deterministic,
metadata-grounded ``MetadataGroundedDetector`` (docs/14 §4A, slice 2.8) and the
model-based ``ReasoningBasedDetector`` for persistent ambiguity (docs/14 §4B,
slice 2.9). The ``candidates`` subpackage builds the deterministic, gold-free
Surface B candidate pool (the human-screening surface for the first annotation
batch, docs/19 §5.1). The formalizer / resolver / answerability implementations
and the pipeline stage arrive in later M1.5 slices.
"""
from __future__ import annotations

from .annotations import (
    BATCH1_TARGET,
    EVALUABLE_CODES,
    AnnotatedQuestion,
    AnnotationDataset,
    AnnotationDatasetLoader,
    AnnotationLoadError,
    AnnotationPrepError,
    AnnotationRecord,
    AnnotationValidationError,
    Interpretation,
    build_annotation_workspace,
    build_batch_input,
    build_provenance_skeleton,
    build_screening_manifest,
    freeze_batch,
    select_third_label_sample,
    validate_batch,
)
from .candidates import (
    CANDIDATE_SCHEMA_VERSION,
    GOLD_FIELDS,
    SIGNALS,
    CandidatePool,
    CandidateRecord,
    CandidateSelectionError,
    SignalHit,
    SignalScorer,
    build_candidate_pool,
    evaluate_question,
    load_candidates,
    write_candidates,
)
from .detectors import (
    METADATA_GROUNDED_TYPES,
    REASONING_TYPES,
    MetadataGroundedDetector,
    ReasoningBasedDetector,
)
from .errors import AmbiguityResolutionError

__all__ = [
    "AmbiguityResolutionError",
    "AnnotationDataset",
    "AnnotationDatasetLoader",
    "AnnotationLoadError",
    "AnnotationPrepError",
    "AnnotationRecord",
    "AnnotationValidationError",
    "AnnotatedQuestion",
    "BATCH1_TARGET",
    "CANDIDATE_SCHEMA_VERSION",
    "CandidatePool",
    "CandidateRecord",
    "CandidateSelectionError",
    "EVALUABLE_CODES",
    "GOLD_FIELDS",
    "Interpretation",
    "METADATA_GROUNDED_TYPES",
    "MetadataGroundedDetector",
    "REASONING_TYPES",
    "ReasoningBasedDetector",
    "SIGNALS",
    "SignalHit",
    "SignalScorer",
    "build_annotation_workspace",
    "build_batch_input",
    "build_candidate_pool",
    "build_provenance_skeleton",
    "build_screening_manifest",
    "evaluate_question",
    "freeze_batch",
    "load_candidates",
    "select_third_label_sample",
    "validate_batch",
    "write_candidates",
]
