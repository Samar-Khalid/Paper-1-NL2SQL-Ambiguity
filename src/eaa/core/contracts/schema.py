"""Generic relational schema contracts.

Both NL2SQL and NL2VIS tasks describe relational data, so a single
dataset-independent schema contract covers them. Enterprise enrichment
(business terms, synonyms, units) is an *extension* (``EnrichedSchema``), not a
parallel model (see the review finding on dual schema models).

Enrichment *source* data (what adapters publish as a metadata sidecar) is a
separate, generic document (``EnrichmentData``): the raw catalog/glossary for a
database. ``eaa.metadata`` merges it into an ``EnrichedSchema`` (ADR-015). The
base ``DatabaseSchema`` remains the single schema model; ``EnrichmentData`` is a
*description* of that schema, not a second schema model.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import ContractModel


class ForeignKeySpec(ContractModel):
    """A single foreign-key reference from a column to another table."""

    column: str
    references_table: str
    references_column: str


class ColumnSchema(ContractModel):
    """A column in a relational table."""

    name: str
    data_type: str
    nullable: bool = True
    primary_key: bool = False
    foreign_key: ForeignKeySpec | None = None
    description: str | None = None


class TableSchema(ContractModel):
    """A relational table."""

    name: str
    columns: list[ColumnSchema]
    primary_keys: list[str] = Field(default_factory=list)
    description: str | None = None


class DatabaseSchema(ContractModel):
    """A database as seen by the framework (relational, dataset-independent)."""

    database_id: str
    dialect: str | None = None
    tables: list[TableSchema]
    description: str | None = None


class ColumnSemantics(ContractModel):
    """Enterprise metadata attached to one column (part of ``EnrichedSchema``)."""

    synonyms: list[str] = Field(default_factory=list)
    business_term: str | None = None
    unit: str | None = None
    domain_values: list[str] = Field(default_factory=list)
    description: str | None = None


class RelationshipSpec(ContractModel):
    """An explicit relationship between two columns (enrichment source data).

    Foreign keys already live on ``ColumnSchema.foreign_key``; this adds a
    *semantic* view (business relationships and descriptions) that enriches the
    prompt without changing the base schema model.
    """

    from_table: str
    from_column: str
    to_table: str
    to_column: str
    kind: Literal["foreign_key", "semantic"] = "semantic"
    description: str | None = None


class EnrichmentData(ContractModel):
    """Dataset-independent enrichment source document for one database.

    Adapters publish their metadata sidecar in this generic shape (metadata is
    *data*, ADR-015); ``eaa.metadata`` merges it into an ``EnrichedSchema``.
    Column semantics reuse ``ColumnSemantics``; table descriptions are plain
    strings; relationships complement the schema's foreign keys.
    """

    database_id: str | None = None
    table_descriptions: dict[str, str] = Field(default_factory=dict)
    column_semantics: dict[str, dict[str, ColumnSemantics]] = Field(
        default_factory=dict, description="table name -> column name -> semantics"
    )
    relationships: list[RelationshipSpec] = Field(default_factory=list)


class EnrichedSchema(DatabaseSchema):
    """``DatabaseSchema`` extended with enterprise metadata.

    Composition over extension: an ``EnrichedSchema`` *is a* ``DatabaseSchema``
    with additional per-column/table semantic data. This prevents a second,
    parallel schema model from drifting out of sync.
    """

    column_semantics: dict[str, dict[str, ColumnSemantics]] = Field(
        default_factory=dict, description="table name -> column name -> semantics"
    )
    table_descriptions: dict[str, str] = Field(default_factory=dict)
    relationships: list[RelationshipSpec] = Field(default_factory=list)

    @property
    def has_enrichment(self) -> bool:
        """Whether this schema carries content beyond the base schema.

        An enriched schema with empty semantics renders exactly like its base
        schema; the prompt builder uses this to pick the enriched prompt
        variant and its version token.
        """
        return bool(
            self.table_descriptions or self.column_semantics or self.relationships
        )
