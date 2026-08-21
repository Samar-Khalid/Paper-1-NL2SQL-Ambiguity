"""Schema + enrichment lookup index for the metadata-grounded detector.

The index turns one ``DatabaseSchema`` (possibly an ``EnrichedSchema``) into
the normalized lookup structures the detection rules consult: column aliases
from ``ColumnSemantics`` (business terms and synonyms), declared units, domain
values, table descriptions, rule-defining descriptions, and fiscal-convention
presence. It reads only the schema and its enrichment (docs/14 §2.1) and is
fully deterministic.

When the schema is a plain ``DatabaseSchema`` (no enrichment), every lookup
stays empty and each rule degrades to no detection — the metadata-absent
condition of the detector evaluation (docs/15 §6, baseline 2).
"""
from __future__ import annotations

from dataclasses import dataclass

from eaa.core.contracts.schema import (
    ColumnSemantics,
    DatabaseSchema,
    EnrichedSchema,
)

from .text_matching import normalize_phrase, significant_terms, singularize, split_terms

HIERARCHY_WORDS = frozenset(
    {
        "region", "state", "city", "country", "department", "division",
        "category", "segment", "level", "month", "week", "quarter", "year",
        "grade", "channel", "territory",
    }
)


def _unit_tokens(unit: str) -> set[str]:
    """Normalize a declared unit string into its token set.

    ``"Million USD"`` yields ``{"million", "usd"}``; ``"k"`` yields ``{"k"}``.

    Parameters
    ----------
    unit:
        The declared unit text.

    Returns
    -------
    set[str]:
        The normalized unit tokens.
    """
    return {term.text.lower() for term in split_terms(unit)}


@dataclass(frozen=True)
class ColumnRef:
    """A resolved reference to one column of one table."""

    table: str
    column: str


class SchemaIndex:
    """Normalized lookup over one schema and its optional enrichment.

    Parameters
    ----------
    schema:
        The resolved schema for the database being analyzed. An
        ``EnrichedSchema`` with content enables metadata lookups; a plain
        ``DatabaseSchema`` leaves them empty.
    """

    def __init__(self, schema: DatabaseSchema) -> None:
        self._schema = schema
        self._enrichment: EnrichedSchema | None = (
            schema if isinstance(schema, EnrichedSchema) and schema.has_enrichment else None
        )

        self.literal_names: set[str] = set()
        self.column_aliases: dict[str, list[ColumnRef]] = {}
        self.unit_terms: set[str] = set()
        self.unit_mentions_currency: bool = False
        self.domain_values: dict[str, list[ColumnRef]] = {}
        self.table_description_terms: dict[str, frozenset[str]] = {}
        self.rule_descriptions: list[tuple[str, str]] = []
        self.fiscal_entities: set[str] = set()
        self.hierarchy_columns: dict[str, list[ColumnRef]] = {}

        self._build()

    @property
    def schema(self) -> DatabaseSchema:
        """The schema this index was built from."""
        return self._schema

    @property
    def has_enrichment(self) -> bool:
        """Whether any enrichment content is available for lookups."""
        return self._enrichment is not None

    def _build(self) -> None:
        for table in self._schema.tables:
            self.literal_names.add(normalize_phrase(table.name))
            for column in table.columns:
                self.literal_names.add(normalize_phrase(column.name))

        enrichment = self._enrichment
        if enrichment is None:
            return

        for table_name, columns in enrichment.column_semantics.items():
            for column_name, semantics in columns.items():
                ref = ColumnRef(table=table_name, column=column_name)
                self._index_semantics(ref, semantics)

        for table_name, description in enrichment.table_descriptions.items():
            self.table_description_terms[table_name] = frozenset(
                singularize(term.text.lower())
                for term in significant_terms(description)
            )
            self.rule_descriptions.append((table_name, description))
            normalized = normalize_phrase(description)
            if "fiscal" in normalized:
                self.fiscal_entities.add(table_name)

        for key, refs in self.column_aliases.items():
            singular_key = singularize(key)
            if singular_key in HIERARCHY_WORDS:
                self.hierarchy_columns.setdefault(singular_key, []).extend(refs)

    def _index_semantics(self, ref: ColumnRef, semantics: ColumnSemantics) -> None:
        if semantics.business_term:
            self._add_alias(normalize_phrase(semantics.business_term), ref)
        for synonym in semantics.synonyms:
            self._add_alias(normalize_phrase(synonym), ref)

        if semantics.unit:
            tokens = _unit_tokens(semantics.unit)
            self.unit_terms.update(tokens)
            if tokens & {"usd", "dollar", "dollars"}:
                self.unit_mentions_currency = True

        for value in semantics.domain_values:
            key = normalize_phrase(value)
            if key:
                self.domain_values.setdefault(key, []).append(ref)

        if semantics.description:
            self.rule_descriptions.append((f"{ref.table}.{ref.column}", semantics.description))

        for field in (semantics.business_term, semantics.unit, semantics.description):
            if field and "fiscal" in normalize_phrase(field):
                self.fiscal_entities.add(f"{ref.table}.{ref.column}")

        name_key = normalize_phrase(ref.column)
        if (
            singularize(name_key) in HIERARCHY_WORDS
            and (semantics.domain_values or semantics.business_term)
        ):
            self.hierarchy_columns.setdefault(singularize(name_key), []).append(ref)

    def _add_alias(self, key: str, ref: ColumnRef) -> None:
        if key:
            self.column_aliases.setdefault(key, []).append(ref)


__all__ = [
    "HIERARCHY_WORDS",
    "ColumnRef",
    "SchemaIndex",
]
