"""Tests for annotation dataset statistics."""
import json
from dataclasses import FrozenInstanceError

import pytest

from eaa.ambiguity_resolution.annotations import (
    AnnotationDatasetLoader,
    AnnotationDatasetStats,
    compute_stats,
)

pytestmark = pytest.mark.unit

QUESTION_TEXT = "What was the total revenue last quarter?"
UNANSWERABLE_TEXT = "What was the quarterly revenue for this quarter?"
SCHEMA = "annotation-schema-v1"
loader = AnnotationDatasetLoader()


def make_span(
    span_id: str,
    start: int,
    end: int,
    text: str,
    ambiguity_type: str,
    **overrides,
) -> dict:
    """Build a valid span dict, applying overrides."""
    span = {
        "span_id": span_id,
        "text": text,
        "start": start,
        "end": end,
        "ambiguity_type": ambiguity_type,
        "metadata_resolution": False,
        "clarification_required": True,
        "assumption_risk": "low",
        "resolution_channel": "clarification",
    }
    span.update(overrides)
    return span


def build_dataset(tmp_path) -> None:
    """Write two labeled questions (answerable + unanswerable) to ``tmp_path``."""
    answerable = {
        "schema_version": SCHEMA,
        "question_id": "q1",
        "question_text": QUESTION_TEXT,
        "database_id": "warehouse",
        "answerability": {"label": "answerable", "confidence": 0.95},
        "spans": [
            make_span("s1", 27, 39, "last quarter", "T1"),
            make_span("s2", 19, 26, "revenue", "L1"),
        ],
    }
    unanswerable = {
        "schema_version": SCHEMA,
        "question_id": "q2",
        "question_text": UNANSWERABLE_TEXT,
        "database_id": "warehouse",
        "answerability": {"label": "unanswerable", "confidence": 0.9},
        "spans": [
            make_span(
                "s1",
                35,
                47,
                "this quarter",
                "U1",
                clarification_required=False,
                resolution_channel="refusal",
            )
        ],
        "interpretations": {
            "sql_reading_A": {
                "sql": "SELECT SUM(revenue) FROM fact WHERE period = 'this quarter'"
            },
            "sql_reading_B": {
                "sql": "SELECT SUM(revenue) FROM fact WHERE period = 'current quarter'"
            },
        },
    }
    (tmp_path / "q1.json").write_text(json.dumps(answerable), encoding="utf-8")
    (tmp_path / "q2.json").write_text(json.dumps(unanswerable), encoding="utf-8")


def test_compute_stats_counts(tmp_path) -> None:
    """Stats count questions, spans per family, types, and answerability."""
    build_dataset(tmp_path)
    stats: AnnotationDatasetStats = compute_stats(loader.load(tmp_path))
    assert stats.num_questions == 2
    assert stats.answerable == 1
    assert stats.unanswerable == 1
    assert stats.num_ambiguity_types == 3
    assert stats.family_distribution == {"L": 1, "T": 1, "U": 1}
    assert stats.num_interpretations == 2


def test_dataset_stats_property_matches_function(tmp_path) -> None:
    """The dataset.stats property agrees with compute_stats."""
    build_dataset(tmp_path)
    dataset = loader.load(tmp_path)
    assert dataset.stats == compute_stats(dataset)


def test_stats_frozen() -> None:
    """The stats object cannot be mutated after construction."""
    stats = AnnotationDatasetStats(
        num_questions=0,
        num_ambiguity_types=0,
        family_distribution={},
        answerable=0,
        unanswerable=0,
        num_interpretations=0,
    )
    with pytest.raises(FrozenInstanceError):
        stats.num_questions = 1
