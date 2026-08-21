"""Pre-registered ambiguity-detection metrics (docs/15 §4).

Implements the docs/15 §4 metrics that are measurable in the current
reasoning-only / metadata-deferred setting:

- §4.1 question-level existence Precision / Recall / F1 (ambiguous vs not);
- §4.3 span Precision / Recall / F1 under the primary IoU ≥ 0.5 + type-match
  rule, the secondary IoU ≥ 0.7 rule, and the exact-boundary (IoU = 1.0) rule,
  plus the IoU sweep values;
- type accuracy and family accuracy on localized (IoU ≥ 0.5) spans;
- §5.2 per-family span P/R/F1;
- per-code confusion matrix and §5.3 band confusion matrix
  (persistent / metadata-closable / unambiguous);
- persistence judgment accuracy on localized spans (metadata-closable vs
  persistent, docs/15 §4.5's persistence component, measurable without
  enrichment because the deferred metadata-closable gold spans still carry a
  ``resolution_channel == "metadata"`` marker).

Not implemented here (reported as N/A with reasons by the evaluation driver):
confidence quality (§4.4 AUROC / ECE — requires a confidence-bearing
detector), false-ambiguity / unnecessary-clarification rates (§4.5 — require
legitimate enrichment), and answerability (§4.6 — the batch contains no
unanswerable gold items).

The metric definitions are the pre-registered docs/15 definitions. They are
not adjusted to any observed score. Matching is greedy per question (pair the
highest-IoU valid pair first), the standard bipartite span-matching convention.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Family letter of every canonical taxonomy code (docs/13 §2 families).
FAMILY_OF_CODE: dict[str, str] = {
    "L1": "L",
    "L2": "L",
    "S1": "S",
    "S2": "S",
    "R1": "R",
    "R2": "R",
    "V1": "V",
    "V2": "V",
    "V3": "V",
    "C1": "C",
    "C2": "C",
    "C3": "C",
    "C4": "C",
    "T1": "T",
    "T2": "T",
    "K1": "K",
    "K2": "K",
    "I1": "I",
    "I2": "I",
    "I3": "I",
    "U1": "U",
    "U2": "U",
    "U3": "U",
    "U4": "U",
}

#: Documented resolution bands (docs/12 §5, docs/14 §6, docs/15 §5.3).
BANDS: tuple[str, ...] = ("persistent", "metadata_closable", "unambiguous")


def family_of(code: str) -> str:
    """Return the family letter of a taxonomy code."""
    return FAMILY_OF_CODE.get(code, "?")


@dataclass(frozen=True)
class GoldSpan:
    """A gold span: half-open offsets, code, and its persistence band."""

    start: int
    end: int
    code: str
    persistence: str  # "persistent" | "metadata_closable"


@dataclass(frozen=True)
class PredictedSpan:
    """A detector span: half-open offsets, code, and optional confidence."""

    start: int
    end: int
    code: str
    persistence: str = "persistent"
    confidence: float | None = None


@dataclass
class SpanMatch:
    """One localized (gold, predicted) pair and its IoU."""

    gold: GoldSpan
    predicted: PredictedSpan
    iou: float


@dataclass
class QuestionComparison:
    """Per-question gold/prediction pairing for one detector."""

    question_id: str
    gold_band: str
    predicted_band: str
    gold_spans: list[GoldSpan]
    predicted_spans: list[PredictedSpan]
    matches: list[SpanMatch] = field(default_factory=list)
    false_positives: list[PredictedSpan] = field(default_factory=list)
    false_negatives: list[GoldSpan] = field(default_factory=list)


def iou(a_start: int, a_end: int, b_start: int, b_end: int) -> float:
    """Return the Jaccard index of two half-open character intervals."""
    overlap = max(0, min(a_end, b_end) - max(a_start, b_start))
    union = (a_end - a_start) + (b_end - b_start) - overlap
    if union <= 0:
        return 0.0
    return overlap / union


def _code_matches(pred_code: str, gold_code: str, *, family_level: bool) -> bool:
    if family_level:
        return family_of(pred_code) == family_of(gold_code)
    return pred_code == gold_code


def match_spans(
    gold: list[GoldSpan],
    predicted: list[PredictedSpan],
    *,
    threshold: float,
    family_level: bool = False,
) -> tuple[list[SpanMatch], list[PredictedSpan], list[GoldSpan]]:
    """Greedily pair predicted spans to gold spans (highest IoU first).

    A pair is valid when ``IoU >= threshold`` and the codes match (or their
    families match when ``family_level``). Unpaired predicted spans are false
    positives; unpaired gold spans are false negatives.
    """
    matches: list[SpanMatch] = []
    fps: list[PredictedSpan] = []
    fns: list[GoldSpan] = []
    used_gold: set[int] = set()
    used_pred: set[int] = set()
    candidates: list[tuple[float, int, int]] = []
    for gi, g in enumerate(gold):
        for pi, p in enumerate(predicted):
            value = iou(g.start, g.end, p.start, p.end)
            if value >= threshold and _code_matches(p.code, g.code, family_level=family_level):
                candidates.append((value, gi, pi))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    for value, gi, pi in candidates:
        if gi in used_gold or pi in used_pred:
            continue
        used_gold.add(gi)
        used_pred.add(pi)
        matches.append(SpanMatch(gold=gold[gi], predicted=predicted[pi], iou=value))
    for pi, p in enumerate(predicted):
        if pi not in used_pred:
            fps.append(p)
    for gi, g in enumerate(gold):
        if gi not in used_gold:
            fns.append(g)
    return matches, fps, fns


def _pair_by_localization(
    gold: list[GoldSpan], predicted: list[PredictedSpan], threshold: float = 0.5
) -> list[SpanMatch]:
    """Pair spans by IoU alone (any code) — for classification accuracy."""
    matches: list[SpanMatch] = []
    used_gold: set[int] = set()
    used_pred: set[int] = set()
    candidates: list[tuple[float, int, int]] = []
    for gi, g in enumerate(gold):
        for pi, p in enumerate(predicted):
            value = iou(g.start, g.end, p.start, p.end)
            if value >= threshold:
                candidates.append((value, gi, pi))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    for value, gi, pi in candidates:
        if gi in used_gold or pi in used_pred:
            continue
        used_gold.add(gi)
        used_pred.add(pi)
        matches.append(SpanMatch(gold=gold[gi], predicted=predicted[pi], iou=value))
    return matches


def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    """Precision / Recall / F1 over aggregate counts (0.0 when undefined)."""
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def _span_counts(
    comparisons: list[QuestionComparison],
    *,
    threshold: float,
    family_level: bool,
) -> tuple[int, int, int]:
    tp = fp = fn = 0
    for comparison in comparisons:
        matches, fps, fns = match_spans(
            comparison.gold_spans,
            comparison.predicted_spans,
            threshold=threshold,
            family_level=family_level,
        )
        tp += len(matches)
        fp += len(fps)
        fn += len(fns)
    return tp, fp, fn


def span_metrics(
    comparisons: list[QuestionComparison], thresholds: tuple[float, ...] = (0.5, 0.7, 1.0)
) -> dict[str, Any]:
    """Span P/R/F1 per IoU threshold with type-match (docs/15 §4.3)."""
    result: dict[str, Any] = {}
    for threshold in thresholds:
        tp, fp, fn = _span_counts(comparisons, threshold=threshold, family_level=False)
        result[f"iou_{threshold:g}"] = {
            **prf(tp, fp, fn),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }
    return result


def existence_metrics(comparisons: list[QuestionComparison]) -> dict[str, Any]:
    """Question-level existence P/R/F1 (docs/15 §4.1)."""
    tp = fp = fn = tn = 0
    for comparison in comparisons:
        gold = comparison.gold_band != "unambiguous"
        pred = comparison.predicted_band != "unambiguous"
        if gold and pred:
            tp += 1
        elif gold and not pred:
            fn += 1
        elif not gold and pred:
            fp += 1
        else:
            tn += 1
    ambiguous = prf(tp, fp, fn)
    unambiguous = prf(tn, fn, fp)
    macro_f1 = (ambiguous["f1"] + unambiguous["f1"]) / 2
    n = len(comparisons)
    return {
        "accuracy": (tp + tn) / n if n else 0.0,
        "ambiguous": ambiguous,
        "unambiguous": unambiguous,
        "macro_f1": macro_f1,
        "counts": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }


def classification_accuracy(comparisons: list[QuestionComparison]) -> dict[str, Any]:
    """Type / family accuracy over localized (IoU >= 0.5) spans."""
    localized = total = 0
    type_correct = family_correct = 0
    for comparison in comparisons:
        pairs = _pair_by_localization(comparison.gold_spans, comparison.predicted_spans)
        localized += len(pairs)
        total += len(comparison.predicted_spans)
        for pair in pairs:
            if pair.predicted.code == pair.gold.code:
                type_correct += 1
            if family_of(pair.predicted.code) == family_of(pair.gold.code):
                family_correct += 1
    return {
        "localized_spans": localized,
        "predicted_spans": total,
        "type_accuracy": type_correct / localized if localized else 0.0,
        "family_accuracy": family_correct / localized if localized else 0.0,
    }


def per_family_metrics(comparisons: list[QuestionComparison]) -> dict[str, Any]:
    """Per-family span P/R/F1 (family-match, IoU >= 0.5; docs/15 §5.2)."""
    families = sorted(
        {
            family_of(g.code)
            for comparison in comparisons
            for g in comparison.gold_spans
        }
        | {
            family_of(p.code)
            for comparison in comparisons
            for p in comparison.predicted_spans
        }
    )
    result: dict[str, Any] = {}
    for family in families:
        tp = fp = fn = 0
        for comparison in comparisons:
            gold = [g for g in comparison.gold_spans if family_of(g.code) == family]
            pred = [p for p in comparison.predicted_spans if family_of(p.code) == family]
            matches, fps, fns = match_spans(gold, pred, threshold=0.5, family_level=True)
            tp += len(matches)
            fp += len(fps)
            fn += len(fns)
        result[family] = {**prf(tp, fp, fn), "tp": tp, "fp": fp, "fn": fn}
    return result


def code_confusion(comparisons: list[QuestionComparison]) -> dict[str, Any]:
    """Gold-code x predicted-code counts over localized (IoU >= 0.5) pairs."""
    codes = sorted(
        {
            g.code for c in comparisons for g in c.gold_spans
        }
        | {
            p.code for c in comparisons for p in c.predicted_spans
        }
    )
    matrix = {gold: {pred: 0 for pred in codes} for gold in codes}
    for comparison in comparisons:
        for pair in _pair_by_localization(comparison.gold_spans, comparison.predicted_spans):
            matrix[pair.gold.code][pair.predicted.code] += 1
    return {"codes": codes, "matrix": matrix}


def band_confusion(comparisons: list[QuestionComparison]) -> dict[str, Any]:
    """Gold band x predicted band counts over questions (docs/15 §5.3)."""
    matrix = {gold: {pred: 0 for pred in BANDS} for gold in BANDS}
    for comparison in comparisons:
        matrix[comparison.gold_band][comparison.predicted_band] += 1
    return {"bands": list(BANDS), "matrix": matrix}


def persistence_metrics(comparisons: list[QuestionComparison]) -> dict[str, Any]:
    """Return persistence judgment accuracy on localized spans.

    A predicted span matches its gold span when IoU >= 0.5 (type ignored); the
    persistence judgment is correct when both predict the same band
    (persistent vs metadata-closable). Measurable without enrichment because
    the deferred metadata-closable gold spans carry ``persistence =
    "metadata_closable"``.
    """
    localized = correct = 0
    for comparison in comparisons:
        for pair in _pair_by_localization(comparison.gold_spans, comparison.predicted_spans):
            localized += 1
            if pair.gold.persistence == pair.predicted.persistence:
                correct += 1
    return {
        "localized_spans": localized,
        "persistence_accuracy": correct / localized if localized else 0.0,
    }


def summarize(
    comparisons: list[QuestionComparison],
    *,
    label: str,
) -> dict[str, Any]:
    """Bundle every pre-registered metric for one detector into a JSON shape."""
    return {
        "detector": label,
        "num_questions": len(comparisons),
        "existence": existence_metrics(comparisons),
        "span": span_metrics(comparisons),
        "classification": classification_accuracy(comparisons),
        "per_family": per_family_metrics(comparisons),
        "code_confusion": code_confusion(comparisons),
        "band_confusion": band_confusion(comparisons),
        "persistence": persistence_metrics(comparisons),
    }


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
