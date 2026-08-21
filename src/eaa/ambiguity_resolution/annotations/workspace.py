"""Annotator workspace construction for a selected Surface B batch.

The workspace is the *input* artifact a human research team screens and labels
against. It exposes exactly what docs/19 §5.1 and the protocol allow the
annotator to see — question id, question text, database id, the warehouse
schema (tables, columns, types, PK/FK) and the candidate signals — and nothing
else. Gold fields (ADR-009) are excluded by construction and asserted by the
leakage tests in ``tests/unit/ambiguity_resolution/annotations/``.

Label templates are blank scaffolds: identity fields are copied from the pool
(they are facts), while every label field is ``null``/empty so the scaffold can
never be mistaken for production data (the loader rejects it).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from eaa.ambiguity_resolution.candidates import CandidatePool
from eaa.core.contracts.schema import DatabaseSchema

from ._io import write_json
from .batch import BATCH_ID, PROTOCOL_VERSION
from .errors import AnnotationPrepError
from .provenance import build_provenance_skeleton, write_sidecar

BATCH_INPUT_VERSION = "surface-b-batch-input-v1"


def schema_to_annotator_view(schema: DatabaseSchema) -> dict[str, Any]:
    """Serialize the schema to the minimal view annotators may see.

    Only tables, columns, types, nullability, primary keys and foreign keys are
    emitted; descriptions and any enrichment-like content are excluded.
    """
    return {
        "database_id": schema.database_id,
        "dialect": schema.dialect,
        "tables": [
            {
                "name": table.name,
                "primary_keys": list(table.primary_keys),
                "columns": [
                    {
                        "name": column.name,
                        "data_type": column.data_type,
                        "nullable": column.nullable,
                        "primary_key": column.primary_key,
                        "foreign_key": (
                            None
                            if column.foreign_key is None
                            else {
                                "column": column.foreign_key.column,
                                "references_table": column.foreign_key.references_table,
                                "references_column": column.foreign_key.references_column,
                            }
                        ),
                    }
                    for column in table.columns
                ],
            }
            for table in schema.tables
        ],
    }


def _lookup(record: Any) -> dict[str, str]:
    """Read the three identity fields off a candidate record."""
    return {
        "question_id": record.question_id,
        "question_text": record.question,
        "database_id": record.database_id,
    }


def blank_template(record: Any) -> dict[str, Any]:
    """Build the blank label scaffold for one question (identity pre-filled)."""
    return {
        "schema_version": PROTOCOL_VERSION,
        **_lookup(record),
        "answerability": {"label": None, "confidence": 0.0},
        "spans": [],
        "interpretations": None,
        "notes": None,
    }


def build_batch_input(
    pool: CandidatePool,
    schemas: Mapping[str, DatabaseSchema],
    selected_ids: Sequence[str],
    *,
    batch_id: str = BATCH_ID,
) -> dict[str, Any]:
    """Build the boundary artifact for the selected questions (gold-free)."""
    selection = set(selected_ids)
    available = {record.question_id for record in pool.candidates}
    missing = selection - available
    if missing:
        raise AnnotationPrepError(
            f"selection contains ids absent from the candidate pool: "
            f"{sorted(missing)[:5]}"
        )
    by_id = {record.question_id: record for record in pool.candidates}

    questions: list[dict[str, Any]] = []
    for question_id in sorted(selection):
        record = by_id[question_id]
        questions.append(
            {
                "question_id": record.question_id,
                "database_id": record.database_id,
                "question": record.question,
                "signals": sorted({hit.signal for hit in record.signals}),
            }
        )

    return {
        "artifact": "surface-b-batch-input",
        "artifact_version": BATCH_INPUT_VERSION,
        "batch_id": batch_id,
        "protocol_version": PROTOCOL_VERSION,
        "gold_excluded": True,
        "schemas": {
            database_id: schema_to_annotator_view(schemas[database_id])
            for database_id in sorted(schemas)
        },
        "questions": questions,
    }


def build_annotation_workspace(
    pool: CandidatePool,
    schemas: Mapping[str, DatabaseSchema],
    selected_ids: Sequence[str],
    *,
    out_root: str | Path,
    annotators: Sequence[str] = ("annotator-a", "annotator-b"),
    batch_id: str = BATCH_ID,
) -> Path:
    """Write the full annotation workspace for a human-selected batch.

    Layout (``data/annotations/surface_b/batch-1/``):

    - ``batch.json``: the gold-free boundary input artifact (schemas + questions).
    - ``annotator-<name>/<question_id>.json``: one blank label scaffold per
      annotator per question.
    - ``provenance-v1.json``: the unpopulated Option B sidecar skeleton.
    - ``README.md``: what annotators receive, what they must not see.

    Returns the workspace root path.
    """
    root = Path(out_root)
    selection = sorted(set(selected_ids))

    batch_input = build_batch_input(pool, schemas, selection, batch_id=batch_id)
    write_json(batch_input, root / "batch.json")

    database_ids = sorted(
        {
            record.database_id
            for record in pool.candidates
            if record.question_id in selection
        }
    )

    records_by_id = {record.question_id: record for record in pool.candidates}
    sidecar: dict[str, dict[str, Any]] = {}
    for question_id in selection:
        database_id = records_by_id[question_id].database_id
        sidecar.update(
            build_provenance_skeleton([question_id], database_id=database_id)
        )

    for annotator in annotators:
        annotator_dir = root / annotator
        for question_id in selection:
            template = blank_template(records_by_id[question_id])
            write_json(template, annotator_dir / f"{question_id}.json")

    write_sidecar(sidecar, root / "provenance-v1.json")
    write_json(
        {
            "batch_id": batch_id,
            "protocol_version": PROTOCOL_VERSION,
            "gold_excluded": True,
            "annotators": list(annotators),
            "readme": "See docs/20_M1_5_Surface_B_Annotator_Instructions.md",
            "databases": database_ids,
        },
        root / "README.json",
    )
    return root


__all__ = [
    "BATCH_INPUT_VERSION",
    "blank_template",
    "build_annotation_workspace",
    "build_batch_input",
    "schema_to_annotator_view",
]
