"""Ambiguity-detection evaluation: pre-registered docs/15 §4 metrics.

The metrics in :mod:`.metrics` are mechanism-independent: they compare a
detector's per-question span/verdict output against any gold annotation
dataset (AI-generated today, independent human/validation annotations later)
without the detector or the metric implementation changing.
"""

from .metrics import (
    BANDS,
    FAMILY_OF_CODE,
    GoldSpan,
    PredictedSpan,
    QuestionComparison,
    SpanMatch,
    band_confusion,
    classification_accuracy,
    code_confusion,
    existence_metrics,
    family_of,
    iou,
    match_spans,
    per_family_metrics,
    persistence_metrics,
    prf,
    span_metrics,
    summarize,
)

__all__ = [
    "BANDS",
    "FAMILY_OF_CODE",
    "GoldSpan",
    "PredictedSpan",
    "QuestionComparison",
    "SpanMatch",
    "band_confusion",
    "classification_accuracy",
    "code_confusion",
    "existence_metrics",
    "family_of",
    "iou",
    "match_spans",
    "per_family_metrics",
    "persistence_metrics",
    "prf",
    "span_metrics",
    "summarize",
]
