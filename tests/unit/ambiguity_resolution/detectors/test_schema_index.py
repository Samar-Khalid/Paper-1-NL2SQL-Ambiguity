"""Tests for the schema/enrichment lookup index."""
import pytest

from eaa.ambiguity_resolution.detectors.schema_index import ColumnRef, SchemaIndex

pytestmark = pytest.mark.unit


def test_has_enrichment_distinguishes_metadata_presence(
    dw_base_schema, dw_schema
) -> None:
    """A plain schema has no enrichment; the merged schema does."""
    assert SchemaIndex(dw_base_schema).has_enrichment is False
    assert SchemaIndex(dw_schema).has_enrichment is True


def test_literal_names_normalized(dw_schema) -> None:
    """Table and column names are indexed in normalized form."""
    index = SchemaIndex(dw_schema)
    assert "customer id" in index.literal_names
    assert "fiscal calendar" in index.literal_names
    assert "last order date" in index.literal_names


def test_column_aliases_from_semantics(dw_schema) -> None:
    """Business terms and synonyms index to the column they alias."""
    index = SchemaIndex(dw_schema)
    assert index.column_aliases["net sales"] == [ColumnRef("orders", "revenue")]
    assert index.column_aliases["sales"] == [ColumnRef("orders", "revenue")]
    assert index.column_aliases["revenue"] == [ColumnRef("orders", "revenue")]
    assert index.column_aliases["area"] == [ColumnRef("customers", "region")]
    assert index.column_aliases["last order"] == [
        ColumnRef("customers", "last_order_date")
    ]


def test_unit_and_currency_metadata(dw_schema) -> None:
    """Declared units index to tokens and flag currency mentions."""
    index = SchemaIndex(dw_schema)
    assert index.unit_terms == {"million", "usd"}
    assert index.unit_mentions_currency is True


def test_domain_values_index(dw_schema) -> None:
    """Domain values index to the column enumerating them."""
    index = SchemaIndex(dw_schema)
    assert index.domain_values["open"] == [ColumnRef("orders", "status")]
    assert index.domain_values["vip"] == [ColumnRef("customers", "tier")]


def test_table_description_terms(dw_schema) -> None:
    """Enriched table descriptions contribute singular significant terms."""
    index = SchemaIndex(dw_schema)
    assert "quarter" in index.table_description_terms["fiscal_calendar"]
    assert "customer" in index.table_description_terms["orders"]


def test_fiscal_entities_from_descriptions(dw_schema) -> None:
    """A fiscal convention declared in enrichment is recorded."""
    index = SchemaIndex(dw_schema)
    assert "fiscal_calendar" in index.fiscal_entities


def test_hierarchy_columns_deduplicated(dw_schema) -> None:
    """Hierarchy mentions resolve to a single enriched column."""
    index = SchemaIndex(dw_schema)
    refs = index.hierarchy_columns["region"]
    assert len(set(refs)) == 1
    assert set(refs) == {ColumnRef("customers", "region")}


def test_base_schema_index_is_empty(dw_base_schema) -> None:
    """Without enrichment every metadata lookup stays empty."""
    index = SchemaIndex(dw_base_schema)
    assert index.column_aliases == {}
    assert index.unit_terms == set()
    assert index.domain_values == {}
    assert index.table_description_terms == {}
    assert index.rule_descriptions == []
    assert index.fiscal_entities == set()
    assert index.hierarchy_columns == {}
