"""Tests for the Surface B detector-evaluation driver (Phase C/D, docs/15).

Covers the driver's pure projections (bands, gold spans), each leg's wiring
(baseline determinism, reasoning via a canned backend, combined merge, the
metadata N/A refusal, and the real-backend fail-fast), plus one end-to-end run
against the frozen batch with the schema provider stubbed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eaa.ambiguity_resolution.annotations.ai_annotation import build_record
from eaa.ambiguity_resolution.annotations.models import AnnotationRecord
from eaa.ambiguity_resolution.evaluation.metrics import GoldSpan, PredictedSpan
from eaa.core.configuration import LLMConfig
from eaa.core.contracts.llm import Completion, Message, Usage
from eaa.core.contracts.schema import (
    ColumnSchema,
    DatabaseSchema,
    ForeignKeySpec,
    TableSchema,
)
from eaa.experiments import surface_b_detector_evaluation as ev
from eaa.experiments.errors import ExperimentError

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[4]
FROZEN_BATCH = _REPO_ROOT / "data" / "annotations" / "surface_b" / "batch-1"
FROZEN_SHA_PREFIX = "e215880a"
_CONFIG_PATH = str(_REPO_ROOT / "configs" / "experiments" / "phase1_beaver_eval.yaml")


@pytest.fixture
def dw_schema() -> DatabaseSchema:
    """Enterprise-shaped warehouse schema (no enrichment)."""
    return DatabaseSchema(
        database_id="dw",
        dialect="mysql",
        tables=[
            TableSchema(
                name="customers",
                columns=[
                    ColumnSchema(name="customer_id", data_type="int", primary_key=True),
                    ColumnSchema(name="name", data_type="varchar"),
                    ColumnSchema(name="region", data_type="varchar"),
                    ColumnSchema(name="status", data_type="varchar"),
                    ColumnSchema(name="tier", data_type="varchar"),
                    ColumnSchema(name="last_order_date", data_type="date"),
                ],
            ),
            TableSchema(
                name="orders",
                columns=[
                    ColumnSchema(name="order_id", data_type="int", primary_key=True),
                    ColumnSchema(
                        name="customer_id",
                        data_type="int",
                        foreign_key=ForeignKeySpec(
                            column="customer_id",
                            references_table="customers",
                            references_column="customer_id",
                        ),
                    ),
                    ColumnSchema(name="order_date", data_type="date"),
                    ColumnSchema(name="revenue", data_type="decimal"),
                    ColumnSchema(name="status", data_type="varchar"),
                ],
            ),
        ],
    )


def _persistent_record() -> AnnotationRecord:
    """Build a gold record whose span resolves via clarification (persistent)."""
    return build_record(
        question_id="q_persistent",
        question_text="What is the average revenue of the top 5 customers?",
        database_id="dw",
        spans=[
            {
                "type": "S1",
                "phrase": "average revenue",
                "resolution_channel": "clarification",
            }
        ],
        notes="test",
    )


def _deferred_record() -> AnnotationRecord:
    """Build a gold record with a deferred metadata-closable span."""
    return build_record(
        question_id="q_deferred",
        question_text="List all buildings and their current occupancy.",
        database_id="dw",
        spans=[
            {
                "type": "R1",
                "phrase": "buildings",
                "resolution_channel": "metadata",
                "metadata_resolution": False,
                "clarification_required": False,
                "assumption_risk": "high",
            }
        ],
        notes="test",
    )


def _unambiguous_record() -> AnnotationRecord:
    """Build a gold record with no ambiguity span."""
    return build_record(
        question_id="q_clean",
        question_text="Select all customer names.",
        database_id="dw",
        notes="test",
    )


def test_gold_band_projection() -> None:
    """Question bands derive from the resolution channels of their spans."""
    assert ev.gold_band_of(_persistent_record()) == "persistent"
    assert ev.gold_band_of(_deferred_record()) == "metadata_closable"
    assert ev.gold_band_of(_unambiguous_record()) == "unambiguous"


def test_gold_spans_projection_preserves_persistence() -> None:
    """Deferred metadata spans keep their metadata-closable persistence."""
    spans = ev.gold_spans_of(_deferred_record())
    assert spans == [
        GoldSpan(start=9, end=18, code="R1", persistence="metadata_closable")
    ]


def test_predict_baseline_is_deterministic_and_persistent(dw_schema) -> None:
    """The baseline leg is repeatable and never emits metadata-closable spans."""
    record = _persistent_record()
    first = ev.predict_baseline(record, dw_schema)
    second = ev.predict_baseline(record, dw_schema)
    assert first == second
    assert first.question_id == record.question.question_id
    assert first.predicted_band == "persistent"
    assert first.predicted_spans
    for span in first.predicted_spans:
        assert span.persistence == "persistent"
        text = record.question.question_text
        assert span.start < span.end <= len(text)


def test_predict_baseline_band_is_persistent_or_unambiguous(dw_schema) -> None:
    """The signal baseline predicts only the two bands it can evidence."""
    record = build_record(
        question_id="q_quiet",
        question_text="Show every customer name.",
        database_id="dw",
        notes="test",
    )
    result = ev.predict_baseline(record, dw_schema)
    assert result.predicted_band in {"persistent", "unambiguous"}
    assert result.question_id == "q_quiet"


class _CannedBackend:
    """Deterministic backend returning a fixed detector-format judgment."""

    model_id = "canned-reasoning-test"

    def __init__(self, content: str) -> None:
        self._content = content

    def complete(self, messages, params=None) -> Completion:
        return Completion(
            message=Message(role="assistant", content=self._content),
            usage=Usage(total_tokens=10),
            model_id=self.model_id,
            finish_reason="stop",
        )

    def complete_async(self, messages, params=None) -> Completion:
        return self.complete(messages, params)


def test_predict_reasoning_wiring_with_canned_judgment(dw_schema) -> None:
    """The reasoning leg builds a pipeline task/context and maps analysis spans."""
    question = "What is the average revenue of the top 5 customers?"
    start = question.index("top 5")
    end = start + len("top 5")
    content = json.dumps(
        {
            "verdict": "ambiguous",
            "confidence": 0.9,
            "spans": [
                {"type": "C2", "start": start, "end": end, "reasoning": "top-n ranking"}
            ],
        }
    )
    record = _persistent_record()
    result = ev.predict_reasoning(
        record, dw_schema, _CannedBackend(content), session_id="sess"
    )
    assert result.question_id == "q_persistent"
    assert result.predicted_band == "persistent"
    assert result.predicted_spans == (
        PredictedSpan(start=start, end=end, code="C2", confidence=0.9),
    )


def test_predict_reasoning_unambiguous_judgment(dw_schema) -> None:
    """An unambiguous verdict yields an unambiguous prediction with no spans."""
    content = json.dumps({"verdict": "unambiguous", "confidence": 0.0, "spans": []})
    result = ev.predict_reasoning(
        _persistent_record(), dw_schema, _CannedBackend(content), session_id="sess"
    )
    assert result.predicted_band == "unambiguous"
    assert result.predicted_spans == ()


def test_merge_precedence_and_conflict_reporting() -> None:
    """Persistent dominates, and cross-leg code conflicts are reported."""
    persistent = ev.PredictionResult(
        question_id="q", database_id="dw", predicted_band="persistent",
        predicted_spans=(PredictedSpan(0, 10, "S1"),),
    )
    clean = ev.PredictionResult(
        question_id="q", database_id="dw", predicted_band="unambiguous"
    )
    merged = ev._merge_results([("baseline", persistent), ("reasoning", clean)], "q")
    assert merged.predicted_band == "persistent"
    assert merged.predicted_spans == (PredictedSpan(0, 10, "S1"),)

    conflict = ev.PredictionResult(
        question_id="q", database_id="dw", predicted_band="persistent",
        predicted_spans=(PredictedSpan(0, 10, "C2"),),
    )
    conflicted = ev._merge_results([("baseline", persistent), ("reasoning", conflict)], "q")
    assert conflicted.errors and "overlaps" in conflicted.errors[0]


def test_merge_metadata_closable_when_no_persistent_span() -> None:
    """Metadata-closable is the middle band when no persistent span exists."""
    metadata = ev.PredictionResult(
        question_id="q", database_id="dw", predicted_band="metadata_closable",
        predicted_spans=(PredictedSpan(0, 10, "R1", persistence="metadata_closable"),),
    )
    merged = ev._merge_results([("metadata", metadata)], "q")
    assert merged.predicted_band == "metadata_closable"


@pytest.mark.parametrize(
    "config",
    [
        LLMConfig(),
        LLMConfig(provider="echo"),
        LLMConfig(provider="openai"),
        LLMConfig(provider="openai", model="gpt-x"),
    ],
)
def test_require_real_backend_fails_fast(config, monkeypatch) -> None:
    """Missing/echo providers and missing keys are configuration errors."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ExperimentError):
        ev._require_real_backend(config)


def test_require_real_backend_accepts_keyed_provider(monkeypatch) -> None:
    """A real provider with a keyed environment variable passes the guard."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    ev._require_real_backend(
        LLMConfig(provider="openai-compatible", model="test-model")
    )


def test_metadata_leg_is_explicitly_not_available(tmp_path) -> None:
    """Requesting the metadata leg fails rather than fabricating predictions."""
    with pytest.raises(ExperimentError, match="N/A"):
        ev.run(
            batch_root=FROZEN_BATCH,
            config_path=_CONFIG_PATH,
            out_root=tmp_path / "out",
            legs=("metadata",),
        )


def test_run_pilot_end_to_end_writes_artifacts(
    tmp_path, monkeypatch, dw_schema
) -> None:
    """A pilot run over the frozen batch writes stamped JSON artifacts."""
    monkeypatch.setattr(ev, "_load_schema", lambda config_path: dw_schema)
    summary = ev.run(
        batch_root=FROZEN_BATCH,
        config_path="configs/experiments/phase1_beaver_eval.yaml",
        out_root=tmp_path / "out",
        legs=("baseline", "combined"),
    )
    assert summary.run_record["evaluation_mode"] == ev.AI_GOLD_PILOT
    assert summary.run_record["gold"]["frozen_sha256"].startswith(FROZEN_SHA_PREFIX)
    assert summary.metrics["baseline"]["num_questions"] == 60
    assert summary.metrics["combined"]["num_questions"] == 60
    assert "existence" in summary.metrics["baseline"]
    assert (tmp_path / "out" / "run.json").is_file()
    assert (tmp_path / "out" / "metrics" / "baseline.json").is_file()
    assert (tmp_path / "out" / "tables.md").is_file()


def test_run_reasoning_without_real_backend_fails_clearly(
    tmp_path, monkeypatch, dw_schema
) -> None:
    """The reasoning leg refuses to run without a real, keyed backend."""
    monkeypatch.setattr(ev, "_load_schema", lambda config_path: dw_schema)
    with pytest.raises(ExperimentError, match="real LLM backend"):
        ev.run(
            batch_root=FROZEN_BATCH,
            config_path=_CONFIG_PATH,
            out_root=tmp_path / "out",
            legs=("reasoning",),
        )
