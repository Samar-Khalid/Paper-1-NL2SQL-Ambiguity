"""Shared fixtures for the ambiguity detector tests.

The fixture schema is deliberately enterprise-shaped (docs/13 §9): a small
multi-table warehouse where the enrichment (business terms, synonyms, units,
domain values, descriptions) pins readings that the question text does not
name literally.
"""
import pytest
from eaa.metadata import enrich_schema

from eaa.core.contracts.schema import (
    ColumnSchema,
    ColumnSemantics,
    DatabaseSchema,
    EnrichedSchema,
    EnrichmentData,
    ForeignKeySpec,
    TableSchema,
)


def _base_schema() -> DatabaseSchema:
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


def _enrichment() -> EnrichmentData:
    return EnrichmentData(
        database_id="dw",
        table_descriptions={
            "customers": "customer profile records and their attributes",
            "orders": "orders list line items and amounts per customer",
            "fiscal_calendar": "fiscal year convention maps quarters to fiscal periods",
        },
        column_semantics={
            "orders": {
                "revenue": ColumnSemantics(
                    business_term="revenue",
                    synonyms=["net sales", "sales"],
                    unit="Million USD",
                ),
                "status": ColumnSemantics(
                    synonyms=["state"], domain_values=["Open", "Closed", "Cancelled"]
                ),
            },
            "customers": {
                "region": ColumnSemantics(
                    business_term="region",
                    synonyms=["area"],
                    domain_values=["North", "South", "East", "West"],
                ),
                "tier": ColumnSemantics(domain_values=["VIP", "Regular", "Premium"]),
                "last_order_date": ColumnSemantics(business_term="last order"),
                "status": ColumnSemantics(
                    description=(
                        "active status means the account is in good standing with "
                        "a positive balance"
                    )
                ),
            },
        },
    )


@pytest.fixture
def dw_base_schema() -> DatabaseSchema:
    """Return the warehouse schema without any enrichment (metadata absent)."""
    return _base_schema()


@pytest.fixture
def dw_schema() -> EnrichedSchema:
    """Return the warehouse schema merged with its enrichment (metadata present)."""
    return enrich_schema(_base_schema(), _enrichment())
