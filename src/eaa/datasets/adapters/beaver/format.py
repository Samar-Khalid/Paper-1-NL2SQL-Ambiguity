"""Raw BEAVER data models and parsers.

The BEAVER distribution (Chen et al., 2024, arXiv:2409.02038) has shipped under
two record shapes:

- ``dev_tables.json`` tables as ``{db_id, table_name_original,
  column_names_original, column_types, primary_key, foreign_key}`` (MIT
  distribution), or ``{db, table_name, column_names, column_types,
  example_rows, example_columns}`` (official leaderboard distribution). The
  official distribution also keys the file by ``db#sep#table``.
- question records as ``{question, db/db_id, sql, tables/gold_tables,
  column_mapping/mapping, join_keys, category, ...}``.

This module normalizes either shape into the frozen ``Raw*`` models used by the
adapter. Nothing here may reference core framework types; conversion to core
contracts happens in ``loader.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from eaa.core.contracts.errors import AdapterError

#: The separator used to qualify table ids in the official distribution
#: (``<db_id>#sep#<table_name>``).
_SEP = "#sep#"


@dataclass(frozen=True)
class RawColumn:
    """A single column as recorded in the raw tables file."""

    name: str
    data_type: str
    raw_type: str
    nullable: bool


@dataclass(frozen=True)
class RawForeignKey:
    """A foreign key as recorded in the raw tables file."""

    column: str
    references_table: str
    references_column: str


@dataclass(frozen=True)
class RawTable:
    """A table as recorded in the raw tables file."""

    db_id: str
    name: str
    original_name: str | None
    columns: list[RawColumn]
    primary_key: list[str]
    foreign_keys: list[RawForeignKey]


@dataclass(frozen=True)
class RawQuestion:
    """A question plus its gold SQL and subtask annotations."""

    question_id: str
    question: str
    db_id: str
    gold_sql: str
    gold_tables: list[str]
    join_keys: list[tuple[str, str]]
    column_mapping: dict[str, list[str]]
    category: str | None
    detailed_category: str | None
    split: str | None
    extra: dict[str, Any] = field(default_factory=dict)


def _last_id_part(key: str) -> str:
    """Return the table name part of a ``db#sep#table`` id."""
    return key.rsplit(_SEP, 1)[-1]


def _first_id_part(key: str) -> str:
    """Return the db part of a ``db#sep#table`` id."""
    return key.split(_SEP, 1)[0]


def normalize_type(raw_type: str) -> str:
    """Normalize a MySQL column type string to its bare type.

    ``"int NOT NULL AUTO_INCREMENT"`` -> ``"int"``; ``"varchar(255) DEFAULT
    NULL"`` -> ``"varchar(255)"``.
    """
    return raw_type.split(None, 1)[0]


def _is_not_null(raw_type: str) -> bool:
    """Return whether the raw type declares ``NOT NULL``."""
    return "NOT NULL" in raw_type.upper()


def parse_tables(data: Any) -> list[RawTable]:
    """Parse a raw tables file (dict keyed by id, or list) into ``RawTable``s.

    Raises
    ------
        AdapterError: if a record is malformed.
    """
    records: dict[Any, Any]
    if isinstance(data, dict):
        records = data
    elif isinstance(data, list):
        records = {i: item for i, item in enumerate(data)}
    else:
        raise AdapterError("tables file must be a list of tables or a dict keyed by table id")

    tables: list[RawTable] = []
    for key, record in records.items():
        if not isinstance(record, dict):
            raise AdapterError(f"table record '{key}' must be an object")
        tables.append(_parse_table(key, record))
    return tables


def _parse_table(key: Any, record: dict[str, Any]) -> RawTable:
    db_id = _as_str(record.get("db_id") or record.get("db") or _first_id_part(str(key)))
    name = _as_str(
        record.get("table_name_original")
        or record.get("table_name")
        or _last_id_part(str(key))
    )

    raw_columns = record.get("column_names_original") or record.get("column_names")
    raw_types = record.get("column_types")
    if not isinstance(raw_columns, list) or not isinstance(raw_types, list):
        raise AdapterError(f"table '{name}' must define column_names and column_types lists")
    if len(raw_columns) != len(raw_types):
        raise AdapterError(
            f"table '{name}' column_names ({len(raw_columns)}) and "
            f"column_types ({len(raw_types)}) length mismatch"
        )

    columns = [
        RawColumn(
            name=_as_str(col),
            data_type=normalize_type(_as_str(raw_type)),
            raw_type=_as_str(raw_type),
            nullable=not _is_not_null(_as_str(raw_type)),
        )
        for col, raw_type in zip(raw_columns, raw_types, strict=True)
    ]

    primary_key = [_as_str(v) for v in record.get("primary_key", [])]
    foreign_keys = _parse_foreign_keys(record, name)
    return RawTable(
        db_id=db_id,
        name=name,
        original_name=record.get("table_name_original"),
        columns=columns,
        primary_key=primary_key,
        foreign_keys=foreign_keys,
    )


def _parse_foreign_keys(record: dict[str, Any], table_name: str) -> list[RawForeignKey]:
    raw = record.get("foreign_key", record.get("foreign_keys", []))
    if not isinstance(raw, list):
        raise AdapterError(f"table '{table_name}' foreign_key must be a list")
    parsed: list[RawForeignKey] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise AdapterError(
                f"table '{table_name}' foreign key entries must be objects"
            )
        column = _as_str(entry.get("column_name"))
        ref_table = _last_id_part(_as_str(entry.get("referenced_table_name")))
        ref_column = _as_str(entry.get("referenced_column_name"))
        if not column or not ref_table or not ref_column:
            raise AdapterError(
                f"table '{table_name}' has an incomplete foreign key entry: {entry}"
            )
        parsed.append(
            RawForeignKey(column=column, references_table=ref_table, references_column=ref_column)
        )
    return parsed


def parse_questions(data: Any, db_id: str) -> list[RawQuestion]:
    """Parse a raw questions file (list, or dict keyed by id) into ``RawQuestion``s.

    Question ids are taken from the ``id``/``question_id`` field when present,
    otherwise derived deterministically as ``<db_id>:<zero-padded index>``.
    """
    records: dict[Any, Any]
    if isinstance(data, list):
        records = {i: item for i, item in enumerate(data)}
    elif isinstance(data, dict):
        records = data
    else:
        raise AdapterError("questions file must be a list of questions or a dict keyed by id")

    questions: list[RawQuestion] = []
    for key, record in records.items():
        if not isinstance(record, dict):
            raise AdapterError(f"question record '{key}' must be an object")
        questions.append(_parse_question(key, record, db_id))
    return questions


def _parse_question(key: Any, record: dict[str, Any], db_id: str) -> RawQuestion:
    question = record.get("question")
    if not isinstance(question, str) or not question:
        raise AdapterError(f"question record '{key}' is missing the 'question' field")
    gold_sql = record.get("sql")
    if not isinstance(gold_sql, str) or not gold_sql:
        raise AdapterError(f"question record '{key}' is missing the gold 'sql' field")

    record_db = _as_str(record.get("db_id") or record.get("db") or db_id)
    raw_id = record.get("id") or record.get("question_id")
    if raw_id is not None:
        question_id = _as_str(raw_id) if isinstance(raw_id, str) else str(raw_id)
    else:
        question_id = _derived_id(db_id, key)

    raw_gold_tables = record.get("tables", record.get("gold_tables"))
    gold_tables = [_as_str(v) for v in raw_gold_tables] if isinstance(raw_gold_tables, list) else []

    raw_join_keys = record.get("join_keys")
    join_keys: list[tuple[str, str]] = []
    if isinstance(raw_join_keys, list):
        for pair in raw_join_keys:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                join_keys.append((_as_str(pair[0]), _as_str(pair[1])))

    raw_mapping = record.get("column_mapping", record.get("mapping"))
    column_mapping: dict[str, list[str]] = {}
    if isinstance(raw_mapping, dict):
        for phrase, columns in raw_mapping.items():
            if isinstance(columns, list):
                column_mapping[_as_str(phrase)] = [_as_str(c) for c in columns]

    extra_keys = (
        "oracle_sql",
        "domain_knowledge",
        "sub_questions",
        "sub_sqls",
        "contains_domain_knowledge",
    )
    extra = {k: record[k] for k in extra_keys if k in record}

    return RawQuestion(
        question_id=question_id,
        question=question,
        db_id=record_db,
        gold_sql=gold_sql,
        gold_tables=gold_tables,
        join_keys=join_keys,
        column_mapping=column_mapping,
        category=_as_str(record["category"]) if record.get("category") is not None else None,
        detailed_category=(
            _as_str(record["detailed_category"])
            if record.get("detailed_category") is not None
            else None
        ),
        split=_as_str(record["split"]) if record.get("split") is not None else None,
        extra=extra,
    )


def _derived_id(db_id: str, key: Any) -> str:
    """Derive a deterministic question id from the record position."""
    if isinstance(key, int):
        return f"{db_id}:{key:04d}"
    return f"{db_id}:{_as_str(key)}"


def _as_str(value: Any) -> str:
    if not isinstance(value, str):
        raise AdapterError(f"expected a string value, got {type(value).__name__}")
    return value
