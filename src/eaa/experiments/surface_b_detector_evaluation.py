"""Detector-evaluation driver for the frozen Surface B batch (Paper 1, Phase C/D).

Runs the pre-registered docs/15 §4 metrics of a detector against a gold
annotation batch. The current batch is AI-generated, so every run here is an
**AI-gold pilot / internal-consistency evaluation** — NOT a benchmark-accuracy
measurement. The run record states this explicitly, and the gold loader is a
plain function over the batch files, so the same driver can later consume
independent validation annotations without changing detector or metric code
(Output B / docs/15 §7).

Legs (docs/15 §3):

- ``baseline`` — deterministic ``SignalAnnotator``. Its spans come from
  lexical signals against the schema, never from the gold labels, so it is a
  mechanism-independent floor.
- ``reasoning`` — ``ReasoningBasedDetector`` over a real configured LLM
  backend. It refuses to run without one (``EchoBackend`` is test-only and is
  never used for research numbers; a missing provider is a configuration
  error, not a silent skip).
- ``metadata`` — N/A in this setting: no legitimate enrichment sidecar exists,
  so no metadata-grounded prediction is manufactured (ADR-015).
- ``combined`` — architecture-justified merge of the enabled legs with explicit
  conflict reporting; it never invents spans of its own.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from eaa.ambiguity_resolution.annotations.ai_annotation import SignalAnnotator
from eaa.ambiguity_resolution.annotations.models import (
    AnnotationDataset,
    AnnotationRecord,
    ResolutionChannel,
)
from eaa.ambiguity_resolution.annotations.qc import load_batch
from eaa.ambiguity_resolution.candidates.signals import evaluate_question
from eaa.ambiguity_resolution.detectors import ReasoningBasedDetector
from eaa.ambiguity_resolution.evaluation.metrics import (
    GoldSpan,
    PredictedSpan,
    QuestionComparison,
    iou,
    match_spans,
    summarize,
)
from eaa.core.configuration import LLMConfig, resolve_config
from eaa.core.contracts.ambiguity import AmbiguityAnalysis
from eaa.core.contracts.runtime import Budget, RuntimeContext, SessionState
from eaa.core.contracts.schema import DatabaseSchema
from eaa.core.contracts.task import TaskEnvelope
from eaa.core.pipeline import BUDGET_LEDGER_KEY, BudgetLedger
from eaa.core.registry import envelope_for, plugin_registry

from .errors import ExperimentError

RUN_TAG = "surface-b-detector-eval"

#: Every run against the current batch is an internal-consistency pilot.
AI_GOLD_PILOT = "AI_GOLD_PILOT"

#: The baseline + reasoning detectors emit persistent-type spans only.
_REAL_PROVIDERS = ("openai", "openai-compatible", "vllm", "ollama")

DEFAULT_CONFIG = "configs/experiments/phase1_beaver_eval.yaml"
DEFAULT_BATCH_ROOT = "data/annotations/surface_b/batch-1"
DEFAULT_OUT_ROOT = "experiments/runs/surface_b_detector_eval"


@dataclass(frozen=True)
class PredictionResult:
    """One detector's prediction for one question."""

    question_id: str
    database_id: str
    predicted_band: str
    predicted_spans: tuple[PredictedSpan, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunSummary:
    """Structured outcome of one detector-evaluation run."""

    out_dir: Path
    run_record: dict[str, Any]
    metrics: dict[str, dict[str, Any]]


def gold_band_of(record: AnnotationRecord) -> str:
    """Project a gold record onto the resolution band (docs/15 §5.3)."""
    spans = record.question.spans
    if not spans:
        return "unambiguous"
    if any(
        span.resolution_channel == ResolutionChannel.METADATA for span in spans
    ):
        return "metadata_closable"
    return "persistent"


def gold_spans_of(record: AnnotationRecord) -> list[GoldSpan]:
    """Convert the gold annotation spans into metric spans."""
    spans: list[GoldSpan] = []
    for span in record.question.spans:
        persistence = (
            "metadata_closable"
            if span.resolution_channel == ResolutionChannel.METADATA
            else "persistent"
        )
        spans.append(
            GoldSpan(
                start=span.start,
                end=span.end,
                code=span.ambiguity_type.value,
                persistence=persistence,
            )
        )
    return spans


def _predicted_spans_of(analysis: AmbiguityAnalysis) -> tuple[PredictedSpan, ...]:
    """Convert detector analysis spans into metric spans."""
    return tuple(
        PredictedSpan(
            start=span.start,
            end=span.end,
            code=span.type.value,
            confidence=span.confidence,
        )
        for span in analysis.ambiguous_spans
    )


def predict_baseline(
    record: AnnotationRecord, schema: DatabaseSchema
) -> PredictionResult:
    """Deterministic signal-based prediction (Annotator A as detector)."""
    question = record.question
    annotator = SignalAnnotator()
    label = annotator.annotate(
        question_id=question.question_id,
        question_text=question.question_text,
        database_id=question.database_id,
        signals=(asdict(hit) for hit in evaluate_question(question.question_text, schema)),
    )
    spans = tuple(
        PredictedSpan(
            start=span.start,
            end=span.end,
            code=span.ambiguity_type.value,
        )
        for span in label.question.spans
    )
    return PredictionResult(
        question_id=question.question_id,
        database_id=question.database_id,
        predicted_band="persistent" if spans else "unambiguous",
        predicted_spans=spans,
    )


def _require_real_backend(config: LLMConfig) -> None:
    """Fail loudly unless a real, keyed LLM backend is configured.

    Research numbers must never come from ``EchoBackend`` or from a provider
    that cannot actually call a model; a missing key is a configuration error
    here, not a reason to degrade silently.
    """
    provider = (config.provider or "").lower()
    if provider in ("", "echo", "echo-local"):
        raise ExperimentError(
            "the reasoning leg needs a real LLM backend, but config.llm "
            f"provider is {config.provider!r}; EchoBackend is test-only and "
            "must never back research numbers. Set llm.provider and llm.model "
            "in the experiment config."
        )
    if provider not in _REAL_PROVIDERS:
        raise ExperimentError(
            f"unknown LLM provider {config.provider!r} for the reasoning leg"
        )
    if not config.model:
        raise ExperimentError(
            "the reasoning leg needs llm.model set to a real model id"
        )
    key_env = config.api_key_env or "OPENAI_API_KEY"
    if not _env_has(key_env):
        raise ExperimentError(
            f"llm.api_key_env is {key_env!r} but that environment variable is "
            "not set; the reasoning leg refuses to run without credentials."
        )


def _env_has(name: str) -> bool:
    import os

    return bool(os.environ.get(name))


def _task_for(record: AnnotationRecord) -> TaskEnvelope:
    """Build a valid ``nl2sql`` task envelope for the reasoning detector."""
    question = record.question
    return envelope_for(
        TaskEnvelope,
        "nl2sql",
        {
            "header": {
                "task_id": f"det-{question.question_id}",
                "question": question.question_text,
                "dataset_id": question.database_id,
                "dialect": "mysql",
            },
            "payload": {
                "question": question.question_text,
                "database_id": question.database_id,
                "schema_id": None,
                "allowed_tables": None,
            },
        },
    )


def _context_for(session_id: str) -> RuntimeContext:
    """Runtime context with a fresh budget ledger (pipeline contract)."""
    context = RuntimeContext(
        session=SessionState(session_id=session_id), budget=Budget()
    )
    ledger = BudgetLedger(context.budget)
    return context.model_copy(update={"state": {BUDGET_LEDGER_KEY: ledger}})


def predict_reasoning(
    record: AnnotationRecord,
    schema: DatabaseSchema,
    backend: Any,
    *,
    session_id: str,
) -> PredictionResult:
    """Reasoning-based prediction via ``ReasoningBasedDetector``."""
    question = record.question
    detector = ReasoningBasedDetector(schema=schema, backend=backend)
    analysis = detector.analyze(
        _task_for(record), _context_for(session_id=session_id)
    )
    spans = _predicted_spans_of(analysis)
    return PredictionResult(
        question_id=question.question_id,
        database_id=question.database_id,
        predicted_band="persistent" if spans else "unambiguous",
        predicted_spans=spans,
    )


def _merge_results(
    legs: Sequence[tuple[str, PredictionResult]], question_id: str
) -> PredictionResult:
    """Combine enabled legs into one prediction with conflict reporting.

    The combined band follows the documented precedence (docs/15 §5.3):
    persistent > metadata-closable > unambiguous. Spans are unioned by
    (start, end, code); overlapping spans with different codes across legs are
    reported as conflicts, not silently resolved.
    """
    spans: list[PredictedSpan] = []
    seen: set[tuple[int, int, str]] = set()
    conflicts: list[str] = []
    for name, result in legs:
        for span in result.predicted_spans:
            key = (span.start, span.end, span.code)
            if key not in seen:
                seen.add(key)
                spans.append(span)
        for span in result.predicted_spans:
            for other_name, other in legs:
                if other_name == name:
                    continue
                for other_span in other.predicted_spans:
                    if (
                        other_span.code != span.code
                        and iou(span.start, span.end, other_span.start, other_span.end) > 0.0
                    ):
                        conflicts.append(
                            f"{question_id}: {name}.{span.code}@{span.start}-{span.end} "
                            f"overlaps {other_name}.{other_span.code}"
                        )
    band = "unambiguous"
    if any(span.persistence == "persistent" for span in spans):
        band = "persistent"
    elif spans:
        band = "metadata_closable"
    result = PredictionResult(
        question_id=question_id,
        database_id=legs[0][1].database_id if legs else "",
        predicted_band=band,
        predicted_spans=tuple(spans),
    )
    if conflicts:
        result = PredictionResult(
            question_id=question_id,
            database_id=result.database_id,
            predicted_band=band,
            predicted_spans=tuple(spans),
            errors=tuple(dict.fromkeys(conflicts)),
        )
    return result


def build_comparison(
    record: AnnotationRecord, result: PredictionResult
) -> QuestionComparison:
    """Pair one gold record with one detector prediction."""
    gold_spans = gold_spans_of(record)
    comparison = QuestionComparison(
        question_id=record.question.question_id,
        gold_band=gold_band_of(record),
        predicted_band=result.predicted_band,
        gold_spans=gold_spans,
        predicted_spans=list(result.predicted_spans),
    )
    comparison.matches, comparison.false_positives, comparison.false_negatives = (
        match_spans(gold_spans, list(result.predicted_spans), threshold=0.5)
    )
    return comparison


def load_dataset(batch_root: str | Path) -> AnnotationDataset:
    """Load the frozen batch; validation problems are fatal here."""
    dataset, problems = load_batch(
        batch_root, required_families=("S", "R", "C", "T", "K", "I")
    )
    if problems:
        raise ExperimentError(
            "gold batch is not evaluable: " + "; ".join(problems)
        )
    return dataset


def _load_schema(config_path: str | Path) -> DatabaseSchema:
    """Resolve the adapter's schema provider for the batch's database id.

    Only the plain (un-enriched) schema is read here; enrichment is deferred
    in this setting (no sidecar exists, ADR-015), so the metadata leg is N/A.
    """
    config = resolve_config(config_path)
    name = config.root.dataset.name
    if not name:
        raise ExperimentError("dataset.name is not set in the experiment config")
    factory = plugin_registry.discover().get(name)
    if factory is None:
        raise ExperimentError(
            f"no dataset adapter plugin named {name!r} in 'eaa.datasets'"
        )
    data_root = config.root.dataset.data_root
    if data_root:
        try:
            adapter = cast(Any, factory)(root=data_root)
        except TypeError:
            adapter = factory()
    else:
        adapter = factory()
    provider = getattr(adapter, "schema_provider", None)
    if not callable(provider):
        raise ExperimentError(
            "adapter must expose schema_provider() returning a SchemaProvider"
        )
    return cast(DatabaseSchema, provider().get_schema("dw"))


def _metrics_for(
    detector_label: str,
    records: list[AnnotationRecord],
    results: list[PredictionResult],
) -> dict[str, Any]:
    by_id = {result.question_id: result for result in results}
    comparisons = [
        build_comparison(record, by_id[record.question.question_id])
        for record in records
        if record.question.question_id in by_id
    ]
    return summarize(comparisons, label=detector_label)


def _run_record(
    *,
    batch_root: str,
    config_path: str,
    legs: Sequence[str],
    database_id: str,
    gold_frozen_sha256: str | None,
    extra: dict[str, Any],
) -> dict[str, Any]:
    """Provenance for one pilot run (never claims independent gold)."""
    return {
        "run_tag": RUN_TAG,
        "evaluation_mode": AI_GOLD_PILOT,
        "statement": (
            "internal-consistency evaluation against the frozen AI-generated "
            "annotation batch; NOT a benchmark-accuracy measurement and NOT "
            "independent human-gold validation (docs/15 §7)"
        ),
        "gold": {
            "batch_root": str(Path(batch_root).resolve()),
            "source": "ai_generated",
            "frozen_sha256": gold_frozen_sha256,
        },
        "config": str(Path(config_path).resolve()),
        "database_id": database_id,
        "legs": list(legs),
        "created_at": datetime.now(UTC).isoformat(),
        **extra,
    }


def evaluate_leg(
    leg_name: str,
    records: list[AnnotationRecord],
    predictions: Iterable[PredictionResult],
    *,
    note: str | None = None,
) -> dict[str, Any]:
    """Bundle metrics for one leg, plus its note and the run stamp."""
    results = list(predictions)
    return {
        "detector": leg_name,
        "metrics": _metrics_for(leg_name, records, results),
        "failed": [result for result in results if result.errors],
        "note": note,
    }


def run(
    *,
    batch_root: str | Path = DEFAULT_BATCH_ROOT,
    config_path: str | Path = DEFAULT_CONFIG,
    out_root: str | Path = DEFAULT_OUT_ROOT,
    legs: Sequence[str] = ("baseline", "combined"),
    limit: int | None = None,
) -> RunSummary:
    """Run the pilot and write machine-readable artifacts under ``out_root``.

    Legs are resolved independently; the ``combined`` leg merges whatever
    other legs ran (baseline and/or reasoning) and never invents spans.
    """
    dataset = load_dataset(batch_root)
    records = list(dataset.records)
    if limit is not None:
        records = records[: max(0, limit)]

    selected = list(dict.fromkeys(legs))
    known = {"baseline", "reasoning", "metadata", "combined"}
    unknown = [name for name in selected if name not in known]
    if unknown:
        raise ExperimentError(f"unknown leg(s): {', '.join(unknown)}")
    if "metadata" in selected:
        raise ExperimentError(
            "the metadata leg is N/A in this setting: no legitimate enrichment "
            "sidecar exists, and no metadata-grounded prediction is fabricated "
            "(ADR-015); metadata-aware evaluation is deferred."
        )

    schema = _load_schema(config_path)
    session_id = f"{RUN_TAG}-{Path(out_root).name}"
    per_leg: dict[str, list[PredictionResult]] = {}

    if "baseline" in selected:
        per_leg["baseline"] = [
            predict_baseline(record, schema) for record in records
        ]
    if "reasoning" in selected:
        config = resolve_config(config_path)
        _require_real_backend(config.root.llm)
        from eaa.llm import backend_from_config

        backend = backend_from_config(config.root.llm)
        per_leg["reasoning"] = [
            predict_reasoning(
                record, schema, backend, session_id=session_id
            )
            for record in records
        ]

    metrics: dict[str, dict[str, Any]] = {}
    for name in selected:
        if name == "metadata":
            continue
        predictions = per_leg.get(name, [])
        if name == "combined":
            source_legs = [
                (other, per_leg[other])
                for other in selected
                if other in ("baseline", "reasoning")
            ]
            if not source_legs:
                raise ExperimentError(
                    "combined needs at least one of baseline or reasoning"
                )
            by_id: dict[str, list[tuple[str, PredictionResult]]] = {}
            for other, preds in source_legs:
                for result in preds:
                    by_id.setdefault(result.question_id, []).append(
                        (other, result)
                    )
            predictions = [
                _merge_results(by_id[record.question.question_id], record.question.question_id)
                for record in records
                if record.question.question_id in by_id
            ]
        metrics[name] = evaluate_leg(
            name,
            records,
            predictions,
            note=(
                "merge of the enabled legs; conflicts are reported, never "
                "silently resolved"
                if name == "combined"
                else None
            ),
        )

    out_dir = Path(out_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics").mkdir(parents=True, exist_ok=True)

    # The gold is validated but its frozen hash lives in the lock file; read
    # it only if present (never recompute a "new" hash over the gold here).
    frozen_sha256 = None
    lock = Path(batch_root).parent / "surface_b.v1.lock"
    if lock.is_file():
        try:
            frozen_sha256 = json.loads(lock.read_text(encoding="utf-8")).get("sha256")
        except (OSError, ValueError):
            frozen_sha256 = None

    run_record = _run_record(
        batch_root=str(batch_root),
        config_path=str(config_path),
        legs=list(metrics),
        database_id=schema.database_id,
        gold_frozen_sha256=frozen_sha256,
        extra={
            "legs_detail": {
                name: {
                    "detector": entry["detector"],
                    "num_questions": entry["metrics"]["num_questions"],
                    "num_failed": len(entry["failed"]),
                    "note": entry["note"],
                }
                for name, entry in metrics.items()
            },
        },
    )

    (out_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, sort_keys=True), encoding="utf-8"
    )
    for name, entry in metrics.items():
        (out_dir / "metrics" / f"{name}.json").write_text(
            json.dumps(entry, indent=2, sort_keys=True), encoding="utf-8"
        )
    _write_tables(out_dir, metrics, records)
    return RunSummary(out_dir=out_dir, run_record=run_record, metrics={
        name: entry["metrics"] for name, entry in metrics.items()
    })


def _write_tables(
    out_dir: Path,
    metrics: dict[str, dict[str, Any]],
    records: list[AnnotationRecord],
) -> None:
    """Human-readable markdown summary (never the evidence of record)."""
    lines = [
        "# Surface B detector-evaluation pilot (AI-gold, internal consistency)",
        "",
        f"questions: {len(records)}  evaluation mode: `{AI_GOLD_PILOT}`",
        "",
    ]
    for name, entry in metrics.items():
        lines.append(f"## {name}")
        lines.append("")
        existence = entry["metrics"]["existence"]
        lines.append(
            f"- existence F1 (macro): {existence['macro_f1']:.4f} "
            f"(acc {existence['accuracy']:.4f})"
        )
        span = entry["metrics"]["span"].get("iou_0.5")
        if span:
            lines.append(
                f"- span IoU>=0.5 F1: {span['f1']:.4f} "
                f"(P {span['precision']:.4f}, R {span['recall']:.4f})"
            )
        lines.append("")
    (out_dir / "tables.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the pilot from the command line; return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-root", default=DEFAULT_BATCH_ROOT)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--legs",
        nargs="+",
        default=["baseline", "combined"],
        choices=["baseline", "reasoning", "metadata", "combined"],
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        summary = run(
            batch_root=args.batch_root,
            config_path=args.config,
            out_root=args.out_dir,
            legs=args.legs,
            limit=args.limit,
        )
    except ExperimentError as exc:
        print(f"error: {exc}")
        return 1
    print(f"legs: {', '.join(summary.metrics)}")
    for name, metrics in summary.metrics.items():
        existence = metrics["existence"]
        print(
            f"  {name}: existence macro-F1={existence['macro_f1']:.4f} "
            f"acc={existence['accuracy']:.4f}"
        )
    print(f"artifacts: {summary.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AI_GOLD_PILOT",
    "PredictionResult",
    "RUN_TAG",
    "RunSummary",
    "build_comparison",
    "evaluate_leg",
    "gold_band_of",
    "gold_spans_of",
    "load_dataset",
    "main",
    "predict_baseline",
    "predict_reasoning",
    "run",
]
