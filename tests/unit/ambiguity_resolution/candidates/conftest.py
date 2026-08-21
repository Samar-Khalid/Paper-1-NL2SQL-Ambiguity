"""Shared fixtures for the candidate-selection tests.

The warehouse schema is deliberately small and multi-table (mirroring the
detector test fixtures) so the schema-grounded signals have something to match:
``status`` appears in both ``customers`` and ``orders`` (R1 risk), ``revenue``
is unique to ``orders``, and the table names themselves resolve mentions.
"""
import pytest

from eaa.core.contracts.schema import (
    ColumnSchema,
    DatabaseSchema,
    ForeignKeySpec,
    TableSchema,
)
from eaa.core.contracts.task import TaskEnvelope
from eaa.core.registry import envelope_for


@pytest.fixture
def warehouse_schema() -> DatabaseSchema:
    """Return a small enterprise-shaped warehouse schema (no enrichment)."""
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
            TableSchema(
                name="fiscal_calendar",
                columns=[
                    ColumnSchema(name="date", data_type="date"),
                    ColumnSchema(name="fiscal_quarter", data_type="int"),
                    ColumnSchema(name="fiscal_year", data_type="int"),
                ],
            ),
        ],
    )


@pytest.fixture
def make_task() -> callable:
    """Build a TaskEnvelope with the same shape the BEAVER adapter emits."""

    def _make(question_id: str, question: str, database_id: str = "dw") -> TaskEnvelope:
        return envelope_for(
            TaskEnvelope,
            "nl2sql",
            {
                "header": {
                    "task_id": question_id,
                    "question": question,
                    "dataset_id": "beaver",
                    "dialect": "mysql",
                },
                "payload": {
                    "question": question,
                    "database_id": database_id,
                    "schema_id": None,
                    "allowed_tables": None,
                },
            },
        )

    return _make
