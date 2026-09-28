# `metadata/` — Enterprise Metadata

## Purpose

The enterprise knowledge layer: enriched schemas, business terms, synonyms,
units, and relationship notes that make enterprise questions interpretable.
Metadata is **data, not code** (docs/03 §3.6, ADR-015): dataset adapters
publish enrichment as a sidecar (`EnrichmentData`); this module owns the merge
into the single schema model.

## Responsibilities

- **Enrichment merge** — `enrich_schema(base, sidecar)` copies a `DatabaseSchema`
  and fills it with table/column descriptions, column semantics
  (`ColumnSemantics`: business term, synonyms, unit, domain values,
  description), and relationship notes (`RelationshipSpec`), producing an
  `EnrichedSchema`. Every reference is validated (unknown table/column →
  `MetadataError`).
- **Schema-provider composition** — `EnrichedSchemaProvider(base, metadata)`
  implements `SchemaProvider` (`get_schema` / `get_enriched_schema`) by merging
  the adapter's `MetadataProvider.metadata(database_id)` on the fly, degrading
  to the base schema when no sidecar exists.
- **Business-term lookup** — later phases (ambiguity resolution, metadata-aware
  schema linking) read `EnrichedSchema.column_semantics[*][*].business_term`.

## Boundaries

- **Dataset-independent** (enforced by the conformance guard): no dataset name
  or adapter import appears here.
- Adapters publish only `EnrichmentData` data through a `metadata()` factory
  (ADR-015); they never merge it themselves (R2).
- The metadata OFF/ON experiment is a provider swap selected by the generic
  `schema.enriched` toggle (see `configs/experiments/phase1_{baseline,metadata}.yaml`).

## Status

Implemented (M1.4): `errors.py`, `enrichment.py`, `provider.py`. The `eaa.run`
drivers wrap the schema provider with `EnrichedSchemaProvider` when the toggle
is on, and the prompt builder renders the versioned `enriched-v1` prompt.
