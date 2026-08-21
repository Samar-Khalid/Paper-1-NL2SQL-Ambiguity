"""Tests for the pre-registered ambiguity-detection metrics (docs/15 §4).

Synthetic gold/predicted span pairs exercise each metric on known inputs so
any change to the definitions (not just to a driver) is caught here.
"""
from __future__ import annotations

import pytest

from eaa.ambiguity_resolution.evaluation.metrics import (
    GoldSpan,
    PredictedSpan,
    QuestionComparison,
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

pytestmark = pytest.mark.unit


def _gold(start: int, end: int, code: str = "S1", persistence: str = "persistent") -> GoldSpan:
    return GoldSpan(start=start, end=end, code=code, persistence=persistence)


def _pred(start: int, end: int, code: str = "S1", confidence: float | None = None) -> PredictedSpan:
    return PredictedSpan(start=start, end=end, code=code, confidence=confidence)


def _comparison(
    gold: list[GoldSpan],
    predicted: list[PredictedSpan],
    gold_band: str = "persistent",
    predicted_band: str = "persistent",
) -> QuestionComparison:
    return QuestionComparison(
        question_id="q1",
        gold_band=gold_band,
        predicted_band=predicted_band,
        gold_spans=gold,
        predicted_spans=predicted,
    )


def test_iou_half_overlap() -> None:
    """IoU of two intervals overlapping by half their union."""
    assert iou(0, 10, 5, 15) == pytest.approx(5 / 15)


def test_iou_no_overlap_is_zero() -> None:
    """Disjoint intervals have zero IoU."""
    assert iou(0, 5, 10, 15) == 0.0


def test_iou_exact_match_is_one() -> None:
    """Identical intervals have unit IoU."""
    assert iou(2, 8, 2, 8) == 1.0


def test_match_spans_pairs_highest_iou_greedily() -> None:
    """Each predicted span pairs to its best valid gold span exactly once."""
    gold = [_gold(0, 10), _gold(20, 30)]
    predicted = [_pred(2, 16), _pred(19, 31)]
    matches, fps, fns = match_spans(gold, predicted, threshold=0.5)
    assert len(matches) == 2
    assert fps == [] and fns == []


def test_match_spans_type_mismatch_is_not_a_match() -> None:
    """A localized span whose type differs is an FP plus an FN, not a match."""
    gold = [_gold(0, 10, code="S1")]
    predicted = [_pred(0, 10, code="C2")]
    matches, fps, fns = match_spans(gold, predicted, threshold=0.5)
    assert matches == []
    assert len(fps) == 1 and len(fns) == 1


def test_match_spans_family_level_matches_by_family() -> None:
    """Family-level matching accepts same-family codes; type-level rejects."""
    gold = [_gold(0, 10, code="S1")]
    predicted = [_pred(0, 10, code="S2")]
    _, fps_family, _ = match_spans(gold, predicted, threshold=0.5, family_level=True)
    assert fps_family == []
    matches, fps_type, _ = match_spans(gold, predicted, threshold=0.5)
    assert matches == [] and len(fps_type) == 1


def test_span_metrics_exact_threshold_requires_boundary_match() -> None:
    """IoU=1.0 counts only boundary-identical spans as true positives."""
    comparisons = [_comparison(gold=[_gold(0, 10)], predicted=[_pred(1, 11)])]
    exact = span_metrics(comparisons, thresholds=(1.0,))["iou_1"]
    loose = span_metrics(comparisons, thresholds=(0.5,))["iou_0.5"]
    assert exact["tp"] == 0
    assert loose["tp"] == 1


def test_existence_metrics_contribution_matrix() -> None:
    """One question per cell of the existence contingency table."""
    comparisons = [
        _comparison([], [], gold_band="persistent", predicted_band="persistent"),  # tp
        _comparison([], [], gold_band="persistent", predicted_band="unambiguous"),  # fn
        _comparison([], [], gold_band="unambiguous", predicted_band="persistent"),  # fp
        _comparison([], [], gold_band="unambiguous", predicted_band="unambiguous"),  # tn
    ]
    metrics = existence_metrics(comparisons)
    assert metrics["counts"] == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}
    assert metrics["accuracy"] == 0.5
    assert metrics["ambiguous"]["precision"] == 0.5
    assert metrics["ambiguous"]["recall"] == 0.5


def test_classification_accuracy_type_and_family() -> None:
    """Type accuracy is stricter than family accuracy on localized spans."""
    comparisons = [
        _comparison(gold=[_gold(0, 10, code="S1")], predicted=[_pred(0, 10, code="S1")]),
        _comparison(gold=[_gold(0, 10, code="S1")], predicted=[_pred(0, 10, code="S2")]),
        _comparison(gold=[_gold(0, 10, code="C1")], predicted=[_pred(0, 10, code="R2")]),
    ]
    metrics = classification_accuracy(comparisons)
    assert metrics["localized_spans"] == 3
    assert metrics["type_accuracy"] == pytest.approx(1 / 3)
    assert metrics["family_accuracy"] == pytest.approx(2 / 3)


def test_per_family_metrics_separates_families() -> None:
    """Same-family predictions count as matches inside each family."""
    comparisons = [
        _comparison(
            gold=[_gold(0, 10, code="S1"), _gold(20, 30, code="C1")],
            predicted=[_pred(0, 10, code="S2"), _pred(20, 30, code="C3")],
        )
    ]
    metrics = per_family_metrics(comparisons)
    assert metrics["S"]["tp"] == 1 and metrics["C"]["tp"] == 1
    assert metrics["S"]["fp"] == 0 and metrics["C"]["fp"] == 0


def test_code_confusion_matrix() -> None:
    """A mismatched localized pair lands in the gold x predicted cell."""
    comparisons = [
        _comparison(gold=[_gold(0, 10, code="S1")], predicted=[_pred(0, 10, code="S2")])
    ]
    matrix = code_confusion(comparisons)
    assert "S1" in matrix["codes"] and "S2" in matrix["codes"]
    assert matrix["matrix"]["S1"]["S2"] == 1


def test_band_confusion_matrix() -> None:
    """Band confusion counts per-question gold vs predicted band."""
    comparisons = [
        _comparison([], [], gold_band="metadata_closable", predicted_band="persistent")
    ]
    matrix = band_confusion(comparisons)
    assert matrix["matrix"]["metadata_closable"]["persistent"] == 1


def test_persistence_accuracy_on_localized_spans() -> None:
    """A persistent prediction over metadata-closable gold is a persistence miss."""
    comparisons = [
        _comparison(
            gold=[_gold(0, 10, code="S1", persistence="metadata_closable")],
            predicted=[_pred(0, 10, code="S1")],  # defaults to persistent
        )
    ]
    metrics = persistence_metrics(comparisons)
    assert metrics["localized_spans"] == 1
    assert metrics["persistence_accuracy"] == 0.0


def test_prf_undefined_counts_yield_zero() -> None:
    """Zero denominators produce zero precision/recall/F1, not a division error."""
    assert prf(0, 0, 0) == {"precision": 0.0, "recall": 0.0, "f1": 0.0}


def test_family_of_unknown_code_is_unknown_family() -> None:
    """Unknown codes map to the unknown-family marker rather than crashing."""
    assert family_of("Z9") == "?"


def test_summarize_bundles_all_preregistered_metrics() -> None:
    """The summary object exposes every pre-registered metric group."""
    comparisons = [_comparison(gold=[_gold(0, 10)], predicted=[_pred(0, 10)])]
    summary = summarize(comparisons, label="baseline")
    assert summary["detector"] == "baseline"
    assert summary["num_questions"] == 1
    for key in (
        "existence",
        "span",
        "classification",
        "per_family",
        "code_confusion",
        "band_confusion",
        "persistence",
    ):
        assert key in summary
