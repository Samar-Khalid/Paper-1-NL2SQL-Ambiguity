"""Load BEAVER raw files and convert them into core contracts.

Raw files -> ``Raw*`` models (``format.py``) -> core contracts: per-database
``DatabaseSchema``, ``TaskEnvelope(nl2sql)`` and ``GoldReferenceEnvelope(gold.nl2sql)``.
Envelopes are built exclusively through ``core.registry.envelope_for`` so the
payload is validated against the registered built-in model (ADR-001/002).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from eaa.core.contracts.errors import AdapterError
from eaa.core.contracts.gold import GoldReferenceEnvelope
from eaa.core.contracts.runtime import Budget, RuntimeContext, SessionState, Turn
from eaa.core.contracts.schema import ColumnSchema, DatabaseSchema, ForeignKeySpec, TableSchema
from eaa.core.contracts.task import TaskEnvelope
from eaa.core.registry import envelope_for

from . import manifest as beaver_manifest
from .format import RawColumn, RawQuestion, RawTable, parse_questions, parse_tables

_JOIN_RE = re.compile(r"\bjoin\b", re.IGNORECASE)


def load_json(path: Path) -> Any:
    """Load a JSON data file, raising ``AdapterError`` on decode errors."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AdapterError(f"{path} is not valid JSON: {exc}") from exc


def load_schema(root: Path, db_id: str, dialect: str) -> DatabaseSchema:
    """Build the core ``DatabaseSchema`` for one BEAVER database."""
    db_dir = root / db_id
    tables_path = next(
        (db_dir / name for name in beaver_manifest.TABLE_FILES if (db_dir / name).is_file()),
        None,
    )
    if tables_path is None:
        raise AdapterError(
            f"database '{db_id}' has no tables file "
            f"({', '.join(beaver_manifest.TABLE_FILES)})"
        )
    raw_tables = parse_tables(load_json(tables_path))
    return DatabaseSchema(
        database_id=db_id,
        dialect=dialect,
        tables=[_table_schema(t) for t in raw_tables],
        description=f"BEAVER warehouse '{db_id}'",
    )


def load_questions(root: Path, db_id: str) -> list[RawQuestion]:
    """Load the raw questions (with embedded gold SQL) for one database."""
    db_dir = root / db_id
    questions_path = next(
        (
            db_dir / name
            for name in beaver_manifest.QUESTION_FILES
            if (db_dir / name).is_file()
        ),
        None,
    )
    if questions_path is None:
        raise AdapterError(
            f"database '{db_id}' has no questions file "
            f"({', '.join(beaver_manifest.QUESTION_FILES)})"
        )
    return parse_questions(load_json(questions_path), db_id)


def _table_schema(table: RawTable) -> TableSchema:
    columns = [_column_schema(table, column) for column in table.columns]
    return TableSchema(
        name=table.name,
        columns=columns,
        primary_keys=list(table.primary_key),
        description=table.original_name,
    )


def _column_schema(table: RawTable, column: RawColumn) -> ColumnSchema:
    foreign_key = None
    for fk in table.foreign_keys:
        if fk.column == column.name:
            foreign_key = ForeignKeySpec(
                column=fk.column,
                references_table=fk.references_table,
                references_column=fk.references_column,
            )
            break
    return ColumnSchema(
        name=column.name,
        data_type=column.data_type,
        nullable=column.nullable,
        primary_key=column.name in table.primary_key,
        foreign_key=foreign_key,
        description=None,
    )


def check_fk_integrity(schema: DatabaseSchema) -> None:
    """Verify every foreign key references an existing table/column.

    Raises
    ------
        AdapterError: if a foreign key cannot be resolved.
    """
    tables = {table.name: table for table in schema.tables}
    for table in schema.tables:
        for column in table.columns:
            if column.foreign_key is None:
                continue
            referenced = tables.get(column.foreign_key.references_table)
            if referenced is None:
                raise AdapterError(
                    f"table '{table.name}'.'{column.name}' references unknown table "
                    f"'{column.foreign_key.references_table}' in database "
                    f"'{schema.database_id}'"
                )
            if column.foreign_key.references_column not in {
                c.name for c in referenced.columns
            }:
                raise AdapterError(
                    f"table '{table.name}'.'{column.name}' references unknown column "
                    f"'{column.foreign_key.references_table}."
                    f"{column.foreign_key.references_column}'"
                )


def task_envelope(question: RawQuestion, *, dialect: str, dataset_id: str) -> TaskEnvelope:
    """Build a ``TaskEnvelope(nl2sql)`` for a raw question.

    The task carries only the question and its database; gold tables/join keys
    stay in the gold reference so they are unreachable from prediction paths
    (ADR-009).
    """
    tags = ["beaver"]
    if question.category:
        tags.append(f"category:{question.category}")
    return envelope_for(
        TaskEnvelope,
        "nl2sql",
        {
            "header": {
                "task_id": question.question_id,
                "question": question.question,
                "dataset_id": dataset_id,
                "dialect": dialect,
                "tags": tags,
            },
            "payload": {
                "question": question.question,
                "database_id": question.db_id,
                "schema_id": None,
                "allowed_tables": None,
            },
        },
    )


def gold_envelope(
    question: RawQuestion,
    *,
    dataset_id: str,
    source_split: str | None,
) -> GoldReferenceEnvelope:
    """Build a ``GoldReferenceEnvelope(gold.nl2sql)`` for a raw question.

    Gold-side subtask annotations (gold tables, join keys, column mapping,
    domain knowledge, decomposition) ride in the envelope ``metadata`` so the
    evaluation harness can consume them (retrieval-free setting) without any
    core change.
    """
    annotations: dict[str, Any] = {}
    if question.gold_tables:
        annotations["gold_tables"] = question.gold_tables
    if question.join_keys:
        annotations["join_keys"] = [list(pair) for pair in question.join_keys]
    if question.column_mapping:
        annotations["column_mapping"] = question.column_mapping
    for key, value in question.extra.items():
        if value not in (None, [], {}):
            annotations[key] = value
    return envelope_for(
        GoldReferenceEnvelope,
        "gold.nl2sql",
        {
            "header": {
                "reference_id": question.question_id,
                "task_id": question.question_id,
                "dataset_id": dataset_id,
                "source_split": source_split,
            },
            "payload": {"sql": question.gold_sql},
            "metadata": annotations,
        },
    )


def context_for(task: TaskEnvelope) -> RuntimeContext:
    """Build the per-sample ``RuntimeContext`` for a task envelope."""
    payload = task.payload
    database_id = getattr(payload, "database_id", None)
    return RuntimeContext(
        session=SessionState(
            session_id=task.header.task_id,
            dialect=task.header.dialect,
            metadata={"dataset_id": task.header.dataset_id, "database_id": database_id},
        ),
        budget=Budget(),
        evaluation_mode=True,
        turns=[
            Turn(
                turn_index=0,
                question=task.header.question,
                task_id=task.header.task_id,
            )
        ],
    )


def compute_stats(
    questions: list[RawQuestion], schemas: dict[str, DatabaseSchema]
) -> dict[str, Any]:
    """Compute manifest statistics directly from the loaded data.

    The counts are computed, never assumed; the benchmark-level numbers cited in
    the docs are *verified against the pinned download* rather than hardcoded.
    """
    total_joins = sum(len(_JOIN_RE.findall(question.gold_sql)) for question in questions)
    column_count = sum(
        len(table.columns)
        for schema in schemas.values()
        for table in schema.tables
    )
    foreign_key_count = sum(
        1
        for schema in schemas.values()
        for table in schema.tables
        for column in table.columns
        if column.foreign_key is not None
    )
    return {
        "questions": len(questions),
        "gold_references": len(questions),
        "tables": sum(len(schema.tables) for schema in schemas.values()),
        "columns": column_count,
        "foreign_keys": foreign_key_count,
        "avg_joins": round(total_joins / len(questions), 2) if questions else 0.0,
    }
