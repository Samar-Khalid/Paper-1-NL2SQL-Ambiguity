# `beaver/` — BEAVER Dataset Adapter

> BEAVER: an enterprise **text-to-SQL** benchmark (Chen et al., 2024, arXiv:2409.02038)
> — 9,128 question-SQL pairs, 812 tables, two warehouses (DW, NW), MySQL dialect
> (Phase 1 — NL2SQL). See ADR-013.

## Purpose

Connect the BEAVER benchmark to the framework as a `BenchmarkAdapter`, keeping all BEAVER-specific knowledge out of the core. The adapter implements `DatasetAdapter` + `BenchmarkAdapter` from `eaa.core.interfaces.dataset` (ADR-002/006) and is discovered via the `eaa.datasets` entry-point group.

## Raw data layout (not shipped)

The framework redistributes no BEAVER data (license: confirm at download; docs/05 §5).
Download the raw distribution, then arrange it so each warehouse is a subdirectory of a
**data root** containing a `manifest.json`:

```text
data/raw/beaver/                # EAA_BEAVER_DATA_ROOT or repo default
  manifest.json                 # adapter-local integrity manifest (below)
  dw/                           # one directory per warehouse/database
    tables.json                 # raw table records (or dev_tables.json)
    questions.json              # raw question records (or dev.json)
  nw/
    tables.json
    questions.json
```

The official `data/download_hf.py` already produces `dev.json` (questions with embedded
gold `sql`) and `dev_tables.json` (tables keyed by `db#sep#table`); the adapter reads
either filename. Both known record shapes are accepted (the MIT
`primary_key`/`foreign_key` shape and the official leaderboard shape).

### `manifest.json`

```json
{
  "name": "beaver",
  "version": "1.0",
  "license": "research-use",
  "citation": "BEAVER: An Enterprise Benchmark for Text-to-SQL (Chen et al., 2024, arXiv:2409.02038)",
  "splits": ["dev", "test"],
  "default_split": "dev",
  "databases": ["dw", "nw"],
  "checksum": "<sha256 over the data files>"
}
```

- **Version** pins the data contract and must match `BEAVER_DATA_VERSION` in
  `manifest.py` / `configs/datasets/beaver.yaml` (ADR-013). A mismatch is rejected.
- **Checksum** is a deterministic sha256 over the resolved tables/questions files
  (`eaa.datasets.adapters.beaver.manifest.compute_checksum`); a recorded checksum that
  does not match the data is rejected (docs/05 §5 integrity). Fill it at download time:
  `python -c "from eaa.datasets.adapters.beaver import manifest; ..."`
- **Splits** are the locally downloaded splits (benchmark identity is `["dev","test"]`;
  the private test set is "unavailable locally").

## Responsibilities

- Load BEAVER tables and questions from raw files into core contracts: per-database
  `DatabaseSchema` (via `schema_provider()`), aggregate `schema()`, `TaskEnvelope(nl2sql)`,
  `GoldReferenceEnvelope(gold.nl2sql)`, `DatasetManifest`, and per-sample `RuntimeContext`.
- Envelopes are built only through `eaa.core.registry.envelope_for`, so payloads validate
  against the built-in `nl2sql` / `gold.nl2sql` models; the adapter adds **no** payload types
  to the registry.
- Gold (SQL + gold tables/join keys/column mappings/subtask annotations) is reachable **only**
  through `gold_for()` (ADR-009); tasks never carry gold.
- **Per ADR-013, do not register `answerability_accuracy` as an official benchmark metric** —
  that is the E6 research metric on the project's own labeled subset.

## What must NOT be placed here

- Any logic the core or research modules should rely on at import time.
- General-purpose schema/SQL logic (belongs in `core/` or `schema_linking/`, `sql_*`).
- Raw data files (gitignored).

## Usage

```python
from eaa.datasets.adapters.beaver import BeaverAdapter

adapter = BeaverAdapter("data/raw/beaver")   # or set EAA_BEAVER_DATA_ROOT
adapter.validate()                           # version + checksum + referential integrity
manifest = adapter.manifest()                # DatasetManifest with computed stats
schema = adapter.schema()                    # aggregate DatabaseSchema
schema_provider = adapter.schema_provider()  # per-warehouse schemas (Decision D2)
for task, gold, context in adapter.samples("dev"):
    ...
```

The zero-arg `plugin()` factory (entry point `beaver = "eaa.datasets.adapters.beaver:plugin"`)
returns an adapter over `EAA_BEAVER_DATA_ROOT` or `data/raw/beaver`; data access is lazy and
verified, so a plugin without data fails with setup guidance only when a data method is used.

## Status

Implemented in Phase 1 (M1.1). See [`docs/04_Phase_Roadmap.md`](../../../../docs/04_Phase_Roadmap.md).

## Conformance

`tests/conformance/adapters/beaver/` runs the generic adapter conformance suite plus
BEAVER-specific checks (manifest identity, version/checksum gates, entry-point wiring,
no payload-type leakage, core never imports the adapter). Run with `make test-conformance`.
