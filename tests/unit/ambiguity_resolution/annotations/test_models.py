"""Tests for the annotation internal models."""
import pytest
from pydantic import ValidationError

from eaa.ambiguity_resolution.annotations import (
    AnnotatedQuestion,
    AnnotationDataset,
    AnnotationRecord,
    AnnotationSpan,
    Answerability,
    AnswerabilityLabel,
    Interpretation,
)

pytestmark = pytest.mark.unit

QUESTION_TEXT = "What was the total revenue last quarter?"


def make_span(
    span_id: str = "s1",
    start: int = 27,
    end: int = 39,
    text: str = "last quarter",
    **overrides,
) -> dict:
    """Build a valid span dict, applying overrides."""
    span = {
        "span_id": span_id,
        "text": text,
        "start": start,
        "end": end,
        "ambiguity_type": "T1",
        "metadata_resolution": False,
        "clarification_required": True,
        "assumption_risk": "low",
        "resolution_channel": "clarification",
    }
    span.update(overrides)
    return span


def make_question(**overrides) -> dict:
    """Build a valid question dict, applying overrides."""
    question = {
        "question_id": "q1",
        "question_text": QUESTION_TEXT,
        "database_id": "warehouse",
        "answerability": {"label": "answerable", "confidence": 0.95},
        "spans": [make_span()],
    }
    question.update(overrides)
    return question


def test_valid_question_loads() -> None:
    """A question with a valid span loads and exposes the span offsets."""
    question = AnnotatedQuestion.model_validate(make_question())
    assert question.question_id == "q1"
    assert len(question.spans) == 1
    assert question.spans[0].ambiguity_type.value == "T1"
    assert QUESTION_TEXT[27:39] == "last quarter"


def test_duplicate_span_ids_rejected() -> None:
    """Two spans with the same span_id in one question are rejected."""
    spans = [make_span(), make_span(span_id="s1", start=0, end=4, text="What")]
    with pytest.raises(ValidationError):
        AnnotatedQuestion.model_validate(make_question(spans=spans))


def test_span_text_mismatch_rejected() -> None:
    """A span whose text does not match the offsets is rejected."""
    with pytest.raises(ValidationError):
        AnnotatedQuestion.model_validate(
            make_question(spans=[make_span(text="quarter")])
        )


def test_span_end_exceeds_question_length_rejected() -> None:
    """A span extending past the question text is rejected."""
    with pytest.raises(ValidationError):
        AnnotatedQuestion.model_validate(
            make_question(spans=[make_span(end=len(QUESTION_TEXT) + 1)])
        )


def test_span_non_positive_length_rejected() -> None:
    """A span with end <= start is rejected."""
    with pytest.raises(ValidationError):
        AnnotatedQuestion.model_validate(make_question(spans=[make_span(start=10, end=10)]))


def test_answerability_confidence_range_enforced() -> None:
    """Answerability confidence must lie in [0, 1]."""
    with pytest.raises(ValidationError):
        Answerability(label=AnswerabilityLabel.ANSWERABLE, confidence=1.5)


def test_invalid_ambiguity_code_rejected() -> None:
    """An unknown ambiguity_type code is rejected."""
    with pytest.raises(ValidationError):
        AnnotatedQuestion.model_validate(
            make_question(spans=[make_span(ambiguity_type="XX")])
        )


def test_invalid_assumption_risk_rejected() -> None:
    """An unknown assumption_risk value is rejected."""
    with pytest.raises(ValidationError):
        AnnotatedQuestion.model_validate(
            make_question(spans=[make_span(assumption_risk="extreme")])
        )


def test_invalid_resolution_channel_rejected() -> None:
    """An unknown resolution_channel value is rejected."""
    with pytest.raises(ValidationError):
        AnnotatedQuestion.model_validate(
            make_question(spans=[make_span(resolution_channel="telepathy")])
        )


def test_interpretations_require_both_readings() -> None:
    """Present interpretations must include both sql_reading_A and B."""
    partial = {
        "sql_reading_A": {
            "sql": "SELECT SUM(revenue) FROM fact WHERE period = 'last quarter'"
        }
    }
    with pytest.raises(ValidationError):
        AnnotationRecord.model_validate(
            {
                "schema_version": "annotation-schema-v1",
                "question": make_question(),
                "interpretations": partial,
            }
        )


def test_interpretations_optional() -> None:
    """Clear questions load without interpretations."""
    record = AnnotationRecord.model_validate(
        {"schema_version": "annotation-schema-v1", "question": make_question()}
    )
    assert record.interpretations is None


def test_interpretation_requires_sql() -> None:
    """An interpretation without sql is rejected."""
    with pytest.raises(ValidationError):
        Interpretation(sql="")


def test_extra_fields_rejected() -> None:
    """Unknown fields fail loudly instead of being ignored."""
    with pytest.raises(ValidationError):
        AnnotatedQuestion.model_validate(make_question(spans=[make_span(extra="boom")]))
    with pytest.raises(ValidationError):
        AnnotationSpan.model_validate({**make_span(), "extra": True})


def test_models_are_frozen() -> None:
    """Models are immutable after construction."""
    question = AnnotatedQuestion.model_validate(make_question())
    with pytest.raises(ValidationError):
        question.question_text = "changed"  # type: ignore[misc]


def test_dataset_round_trip() -> None:
    """A dataset serializes and re-validates to the same structure."""
    record = AnnotationRecord.model_validate(
        {"schema_version": "annotation-schema-v1", "question": make_question()}
    )
    dataset = AnnotationDataset(schema_version="annotation-schema-v1", records=[record])
    assert dataset.records == (record,)
    again = AnnotationDataset.model_validate(dataset.model_dump())
    assert again == dataset
