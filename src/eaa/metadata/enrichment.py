"""Enrichment merge: turn a base schema + enrichment data into an ``EnrichedSchema``.

This is the dataset-independent core of ``metadata/`` (ADR-015): adapters
publish enrichment *data* (``EnrichmentData``), and this module owns the merge
into the single schema model (``EnrichedSchema`` *is a* ``DatabaseSchema``, so
there is no parallel schema model to drift). No dataset name appears here.
"""
from __future__ import annotations

from collections.abc import Mapping

from eaa.core.contracts.schema import (
    ColumnSchema,
    ColumnSemantics,
    DatabaseSchema,
    EnrichedSchema,
    EnrichmentData,
    RelationshipSpec,
    TableSchema,
)

from .errors import MetadataError


def enrich_schema(schema: DatabaseSchema, enrichment: EnrichmentData) -> EnrichedSchema:
    """Merge ``enrichment`` into ``schema``, producing an ``EnrichedSchema``.

    The base schema fields are copied unchanged; table and column descriptions
    are filled from the enrichment document, and semantics/relationships are
    carried on the enriched model.

    Parameters
    ----------
    schema:
        The base (database-independent) schema to enrich.
    enrichment:
        The enrichment document for the same database.

    Raises
    ------
    MetadataError:
        If the enrichment references tables/columns that do not exist in
        ``schema``, or if its ``database_id`` contradicts the schema's.
    """
    _validate(schema, enrichment)
    enriched_tables = [
        _enrich_table(table, enrichment)
        for table in schema.tables
    ]
    return EnrichedSchema(
        database_id=schema.database_id,
        dialect=schema.dialect,
        tables=enriched_tables,
        description=schema.description,
        table_descriptions=dict(enrichment.table_descriptions),
        column_semantics={
            table_name: dict(columns)
            for table_name, columns in enrichment.column_semantics.items()
        },
        relationships=list(enrichment.relationships),
    )


def _enrich_table(table: TableSchema, enrichment: EnrichmentData) -> TableSchema:
    """Copy a table, filling descriptions from the enrichment document."""
    description = enrichment.table_descriptions.get(table.name, table.description)
    semantics = enrichment.column_semantics.get(table.name, {})
    columns = [
        _enrich_column(column, semantics)
        for column in table.columns
    ]
    return table.model_copy(update={"description": description, "columns": columns})


def _enrich_column(
    column: ColumnSchema, semantics: Mapping[str, ColumnSemantics]
) -> ColumnSchema:
    """Copy a column, filling its description from the column semantics."""
    item = semantics.get(column.name)
    description = (
        item.description if item is not None and item.description else column.description
    )
    if description == column.description:
        return column
    return column.model_copy(update={"description": description})


def _validate(schema: DatabaseSchema, enrichment: EnrichmentData) -> None:
    """Validate every enrichment reference against the schema (data integrity)."""
    if (
        enrichment.database_id is not None
        and enrichment.database_id != schema.database_id
    ):
        raise MetadataError(
            f"enrichment database_id {enrichment.database_id!r} does not match "
            f"schema database_id {schema.database_id!r}"
        )

    tables = {table.name: table for table in schema.tables}
    for name in enrichment.table_descriptions:
        if name not in tables:
            raise MetadataError(
                f"table description references unknown table {name!r} "
                f"(schema has: {sorted(tables)})"
            )

    for table_name, columns in enrichment.column_semantics.items():
        table = tables.get(table_name)
        if table is None:
            raise MetadataError(
                f"column semantics reference unknown table {table_name!r} "
                f"(schema has: {sorted(tables)})"
            )
        column_names = {column.name for column in table.columns}
        for column_name in columns:
            if column_name not in column_names:
                raise MetadataError(
                    f"column semantics reference unknown column "
                    f"'{table_name}.{column_name}' (table has: {sorted(column_names)})"
                )

    for relationship in enrichment.relationships:
        _validate_relationship(schema, tables, relationship)


def _validate_relationship(
    schema: DatabaseSchema,
    tables: dict[str, TableSchema],
    relationship: RelationshipSpec,
) -> None:
    """Validate one relationship's endpoints against the schema."""
    from_table = tables.get(relationship.from_table)
    if from_table is None:
        raise MetadataError(
            f"relationship from unknown table {relationship.from_table!r} "
            f"(schema has: {sorted(tables)})"
        )
    from_columns = {column.name for column in from_table.columns}
    if relationship.from_column not in from_columns:
        raise MetadataError(
            f"relationship references unknown column "
            f"'{relationship.from_table}.{relationship.from_column}' "
            f"(table has: {sorted(from_columns)})"
        )
    to_table = tables.get(relationship.to_table)
    if to_table is None:
        raise MetadataError(
            f"relationship to unknown table {relationship.to_table!r} "
            f"(schema has: {sorted(tables)})"
        )
    to_columns = {column.name for column in to_table.columns}
    if relationship.to_column not in to_columns:
        raise MetadataError(
            f"relationship references unknown column "
            f"'{relationship.to_table}.{relationship.to_column}' "
            f"(table has: {sorted(to_columns)})"
        )


__all__ = ["enrich_schema"]
