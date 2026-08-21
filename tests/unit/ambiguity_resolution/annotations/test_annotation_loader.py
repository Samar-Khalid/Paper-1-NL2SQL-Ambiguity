"""Tests for the annotation dataset loader."""
import json

import pytest

from eaa.ambiguity_resolution.annotations import (
    AnnotationDataset,
    AnnotationDatasetLoader,
    AnnotationLoadError,
    AnnotationValidationError,
)

pytestmark = pytest.mark.unit

QUESTION_TEXT = "What was the total revenue last quarter?"
SCHEMA = "annotation-schema-v1"
loader = AnnotationDatasetLoader()


def make_record(question_id: str = "q1", spans=None, **overrides) -> dict:
    """Build a valid annotation record dict, applying overrides."""
    record = {
        "schema_version": SCHEMA,
        "question_id": question_id,
        "question_text": QUESTION_TEXT,
        "database_id": "warehouse",
        "answerability": {"label": "answerable", "confidence": 0.95},
        "spans": spans if spans is not None else [],
    }
    record.update(overrides)
    return record


def make_span(**overrides) -> dict:
    """Build a valid span dict, applying overrides."""
    span = {
        "span_id": "s1",
        "text": "last quarter",
        "start": 27,
        "end": 39,
        "ambiguity_type": "T1",
        "metadata_resolution": False,
        "clarification_required": True,
        "assumption_risk": "low",
        "resolution_channel": "clarification",
    }
    span.update(overrides)
    return span


def write_json(path, data) -> None:
    """Write ``data`` as JSON to ``path``."""
    path.write_text(json.dumps(data), encoding="utf-8")


def test_load_single_object_file(tmp_path) -> None:
    """A single annotation object file loads as a one-record dataset."""
    path = tmp_path / "q1.json"
    write_json(path, make_record())
    dataset = loader.load(path)
    assert isinstance(dataset, AnnotationDataset)
    assert dataset.schema_version == SCHEMA
    assert len(dataset.records) == 1
    assert dataset.records[0].question.question_id == "q1"


def test_load_array_file(tmp_path) -> None:
    """A JSON array of annotation objects loads in order."""
    path = tmp_path / "many.json"
    write_json(path, [make_record("q1"), make_record("q2")])
    dataset = loader.load(path)
    assert [r.question.question_id for r in dataset.records] == ["q1", "q2"]


def test_load_directory_sorted(tmp_path) -> None:
    """A directory of .json files loads in sorted filename order."""
    write_json(tmp_path / "q2.json", make_record("q2"))
    write_json(tmp_path / "q1.json", make_record("q1"))
    dataset = loader.load(tmp_path)
    assert [r.question.question_id for r in dataset.records] == ["q1", "q2"]


def test_missing_source_raises_load_error(tmp_path) -> None:
    """A nonexistent path raises AnnotationLoadError."""
    with pytest.raises(AnnotationLoadError):
        loader.load(tmp_path / "missing.json")


def test_directory_without_json_raises_load_error(tmp_path) -> None:
    """A directory with no .json files raises AnnotationLoadError."""
    (tmp_path / "readme.txt").write_text("hi", encoding="utf-8")
    with pytest.raises(AnnotationLoadError):
        loader.load(tmp_path)


def test_invalid_json_raises_load_error(tmp_path) -> None:
    """Malformed JSON raises AnnotationLoadError."""
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(AnnotationLoadError):
        loader.load(path)


def test_non_object_root_raises_load_error(tmp_path) -> None:
    """A JSON scalar root raises AnnotationLoadError."""
    path = tmp_path / "scalar.json"
    write_json(path, 42)
    with pytest.raises(AnnotationLoadError):
        loader.load(path)


def test_non_object_record_in_list_raises_load_error(tmp_path) -> None:
    """An array element that is not an object raises AnnotationLoadError."""
    path = tmp_path / "bad.json"
    write_json(path, [make_record(), "not-an-object"])
    with pytest.raises(AnnotationLoadError):
        loader.load(path)


def test_missing_schema_version(tmp_path) -> None:
    """A record without schema_version is rejected with question_id context."""
    path = tmp_path / "q1.json"
    write_json(path, make_record(schema_version=None))
    with pytest.raises(AnnotationValidationError) as excinfo:
        loader.load(path)
    assert excinfo.value.context["question_id"] == "q1"
    assert "schema_version" in str(excinfo.value)


def test_unknown_schema_version(tmp_path) -> None:
    """An unsupported schema version is rejected."""
    path = tmp_path / "q1.json"
    write_json(path, make_record(schema_version="annotation-schema-v2"))
    with pytest.raises(AnnotationValidationError) as excinfo:
        loader.load(path)
    assert excinfo.value.context["field"] == "schema_version"
    assert "v2" in str(excinfo.value)


def test_missing_required_field(tmp_path) -> None:
    """A missing required field is rejected with a field location."""
    path = tmp_path / "q1.json"
    record = make_record()
    del record["answerability"]
    write_json(path, record)
    with pytest.raises(AnnotationValidationError) as excinfo:
        loader.load(path)
    assert excinfo.value.context["question_id"] == "q1"
    assert "answerability" in excinfo.value.context["field"]


def test_invalid_ambiguity_code(tmp_path) -> None:
    """An invalid ambiguity_type code is rejected."""
    path = tmp_path / "q1.json"
    write_json(path, make_record(spans=[make_span(ambiguity_type="XX")]))
    with pytest.raises(AnnotationValidationError):
        loader.load(path)


def test_invalid_span_bounds(tmp_path) -> None:
    """A span exceeding the question text is rejected."""
    path = tmp_path / "q1.json"
    write_json(path, make_record(spans=[make_span(end=999)]))
    with pytest.raises(AnnotationValidationError):
        loader.load(path)


def test_invalid_interpretations(tmp_path) -> None:
    """Interpretations with a missing reading are rejected."""
    path = tmp_path / "q1.json"
    write_json(
        path,
        make_record(
            interpretations={
                "sql_reading_A": {
                    "sql": "SELECT SUM(revenue) FROM fact WHERE period = 'last quarter'"
                }
            }
        ),
    )
    with pytest.raises(AnnotationValidationError):
        loader.load(path)


def test_duplicate_question_ids(tmp_path) -> None:
    """Two records with the same question_id are rejected."""
    path = tmp_path / "many.json"
    write_json(path, [make_record("q1"), make_record("q1")])
    with pytest.raises(AnnotationValidationError) as excinfo:
        loader.load(path)
    assert "q1" in str(excinfo.value)
    assert excinfo.value.context["question_id"] == "q1"


def test_valid_span_pairs_load(tmp_path) -> None:
    """A strict-ambiguity record with both readings loads."""
    path = tmp_path / "q1.json"
    write_json(
        path,
        make_record(
            interpretations={
                "sql_reading_A": {
                    "sql": "SELECT SUM(revenue) FROM fact WHERE period = 'last quarter'"
                },
                "sql_reading_B": {
                    "sql": "SELECT SUM(revenue) FROM fact WHERE period = 'previous quarter'"
                },
            }
        ),
    )
    dataset = loader.load(path)
    record = dataset.records[0]
    assert record.interpretations is not None
    assert set(record.interpretations) == {"sql_reading_A", "sql_reading_B"}
