"""Tests for the reasoning-only / metadata-deferred AI-annotation batch (docs/19 §11).

Covers the minimal validation-layer change for the reasoning-only mode:

- deferred metadata-closable spans (``resolution_channel == "metadata"``,
  resolution not asserted, no clarification requested) classify as the
  ``metadata_closable`` stratum — never as persistent, and never as
  successfully metadata-resolved;
- the persistent-stratum family-presence check is parameterizable
  (``required_families``) so the L/V "metadata-present-but-not-decisive"
  families can be deferred without failing the batch;
- the per-family span cap counts persistent (reasoning) spans only, so
  deferred metadata-closable candidates do not push a family over the cap;
- the generated 60-question batch (``surface_b_ai_annotation``) passes the
  loader and the reasoning-mode batch validation end to end.
"""
import json
from pathlib import Path

import pytest

from eaa.ambiguity_resolution.annotations import (
    AnnotationDataset,
    AnnotationDatasetLoader,
    AnnotationRecord,
    validate_batch,
)
from eaa.ambiguity_resolution.annotations.qc import _stratum
from eaa.ambiguity_resolution.candidates import load_candidates
from eaa.experiments.surface_b_ai_annotation import (
    REASONING_FAMILIES,
    _build_records,
    _serialize,
)

pytestmark = pytest.mark.unit

PERSISTENT_QUESTION = "Show the top 5 rooms by area."
UNAMBIGUOUS_QUESTION = "List all buildings."

REASONING_CODES = ["S1", "R2", "C2", "T1", "K1", "I2"]
DEFERRED_CODES = ["R1"] * 7 + ["V1", "V3", "T2", "K2"] * 2


def _span(
    code: str,
    channel: str,
    *,
    metadata_resolution: bool,
    clarification_required: bool,
) -> dict:
    text = "top 5"
    start = PERSISTENT_QUESTION.index(text)
    return {
        "span_id": "sp1",
        "text": text,
        "start": start,
        "end": start + len(text),
        "ambiguity_type": code,
        "metadata_resolution": metadata_resolution,
        "clarification_required": clarification_required,
        "assumption_risk": "high" if channel == "metadata" else "low",
        "resolution_channel": channel,
    }


def _interpretations() -> dict:
    return {
        "sql_reading_A": {
            "sql": "SELECT area FROM room ORDER BY area DESC LIMIT 5",
            "note": "top 5 largest",
        },
        "sql_reading_B": {
            "sql": "SELECT area FROM room ORDER BY area ASC LIMIT 5",
            "note": "top 5 smallest",
        },
    }


def _record(
    question_id: str,
    question: str,
    spans: list[dict],
    *,
    interpretations: dict | None = None,
) -> dict:
    return {
        "schema_version": "annotation-schema-v1",
        "question_id": question_id,
        "question_text": question,
        "database_id": "dw",
        "answerability": {"label": "answerable", "confidence": 1.0},
        "spans": spans,
        "interpretations": interpretations,
        "notes": None,
    }


def _dataset(records: list[dict]) -> AnnotationDataset:
    parsed = []
    for raw in records:
        parsed.append(
            {
                "schema_version": raw["schema_version"],
                "question": {
                    "question_id": raw["question_id"],
                    "question_text": raw["question_text"],
                    "database_id": raw["database_id"],
                    "answerability": raw["answerability"],
                    "spans": raw["spans"],
                },
                "interpretations": raw["interpretations"],
                "notes": raw["notes"],
            }
        )
    return AnnotationDataset(
        schema_version="annotation-schema-v1",
        records=tuple(AnnotationRecord.model_validate(entry) for entry in parsed),
    )


def _reasoning_mode_batch(*, include_i: bool = True) -> list[dict]:
    """30 reasoning + 15 deferred + 15 unambiguous (7 deferred R1 spans)."""
    records: list[dict] = []
    reasoning_codes = REASONING_CODES if include_i else ["S1", "R2", "C2", "T1", "K1"]
    for i in range(30):
        code = reasoning_codes[i % len(reasoning_codes)]
        records.append(
            _record(
                f"pers-{i:03d}",
                PERSISTENT_QUESTION,
                [
                    _span(
                        code,
                        "clarification",
                        metadata_resolution=False,
                        clarification_required=True,
                    )
                ],
                interpretations=_interpretations(),
            )
        )
    for i in range(15):
        code = DEFERRED_CODES[i]
        records.append(
            _record(
                f"meta-{i:03d}",
                PERSISTENT_QUESTION,
                [_span(code, "metadata", metadata_resolution=False, clarification_required=False)],
                interpretations=_interpretations(),
            )
        )
    for i in range(15):
        records.append(_record(f"unamb-{i:03d}", UNAMBIGUOUS_QUESTION, []))
    return records


# ---------------------------------------------------------------------------
# deferred metadata-closable stratum classification
# ---------------------------------------------------------------------------


def test_deferred_metadata_span_classifies_as_metadata_closable() -> None:
    """A deferred metadata span is never counted as persistent or resolved."""
    record = _record(
        "meta-000",
        PERSISTENT_QUESTION,
        [_span("R1", "metadata", metadata_resolution=False, clarification_required=False)],
        interpretations=_interpretations(),
    )
    dataset = _dataset([record])
    assert _stratum(dataset.records[0]) == "metadata_closable"


def test_deferred_span_is_not_asserted_as_resolved() -> None:
    """The deferred representation keeps metadata_resolution False."""
    record = _record(
        "meta-000",
        PERSISTENT_QUESTION,
        [_span("R1", "metadata", metadata_resolution=False, clarification_required=False)],
        interpretations=_interpretations(),
    )
    span = _dataset([record]).records[0].question.spans[0]
    assert span.metadata_resolution is False
    assert span.resolution_channel.value == "metadata"


def test_reasoning_span_with_metadata_channel_is_not_deferred() -> None:
    """Only the exact deferred pattern classifies as metadata-closable."""
    record = _record(
        "pers-000",
        PERSISTENT_QUESTION,
        [_span("R2", "clarification", metadata_resolution=False, clarification_required=True)],
        interpretations=_interpretations(),
    )
    assert _stratum(_dataset([record]).records[0]) == "persistent_ambiguity"


# ---------------------------------------------------------------------------
# reasoning-only validate_batch
# ---------------------------------------------------------------------------


def test_reasoning_mode_batch_passes_with_deferred_stratum() -> None:
    """15/30/15 reasoning-mode batch is valid; deferred R1 spans do not hit the cap."""
    dataset = _dataset(_reasoning_mode_batch())
    assert validate_batch(dataset, required_families=REASONING_FAMILIES) == []


def test_reasoning_mode_default_still_requires_all_families() -> None:
    """Without required_families the default (all 8) behavior is unchanged."""
    dataset = _dataset(_reasoning_mode_batch())
    problems = validate_batch(dataset)
    assert any("misses families" in p for p in problems)
    assert any("'L'" in p or "'V'" in p for p in problems)


def test_reasoning_mode_missing_reasoning_family_is_rejected() -> None:
    """Removing a reasoning family still fails under required_families."""
    dataset = _dataset(_reasoning_mode_batch(include_i=False))
    problems = validate_batch(dataset, required_families=REASONING_FAMILIES)
    assert any("misses families" in p and "'I'" in p for p in problems)


# ---------------------------------------------------------------------------
# the generated 60-question artifact (skips when data/ is absent)
# ---------------------------------------------------------------------------


def _candidates_path():
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "data" / "annotations" / "surface_b" / "candidates.json"


def test_generated_60_question_batch_is_valid(tmp_path) -> None:
    """The emitted batch-1 artifact passes the loader and reasoning-mode QC."""
    candidates = _candidates_path()
    if not candidates.is_file():
        pytest.skip("candidate pool artifact not present (data/ is gitignored)")
    pool = load_candidates(candidates)
    records = _build_records(pool)
    assert len(records) == 60
    label_dir = tmp_path / "dw"
    label_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        payload = _serialize(record)
        (label_dir / f"{record.question.question_id}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    from eaa.ambiguity_resolution.annotations import load_batch

    dataset, problems = load_batch(tmp_path, required_families=REASONING_FAMILIES)
    assert problems == []
    assert len(dataset.records) == 60
    assert len({r.question.question_id for r in dataset.records}) == 60

    from eaa.ambiguity_resolution.annotations.qc import _stratum_counts

    strata = _stratum_counts(dataset)
    assert strata["persistent_ambiguity"] == 30
    assert strata["metadata_closable"] == 15
    assert strata["unambiguous"] == 15

    loader_dataset = AnnotationDatasetLoader().load(label_dir)
    assert len(loader_dataset.records) == 60
