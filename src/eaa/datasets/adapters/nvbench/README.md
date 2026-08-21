# `nvbench/` — NVBench 2.0 Dataset Adapter

> NVBench 2.0: a natural-language-to-visualization benchmark with hierarchical intents and gold chart specifications (Phase 2 — NL2VIS).

## Purpose

Connect the NVBench 2.0 benchmark to the framework as a `BenchmarkAdapter`, keeping all NVBench-specific knowledge out of the core.

## Responsibilities

- Load NVBench 2.0 tasks (intent hierarchy, queries, gold chart specs) into core contracts.
- Map the NVBench intent hierarchy onto the core visualization-intent model.
- Provide deterministic splits.
- Register NVBench-specific metrics (chart accuracy, completeness, consistency).
- Manifest: version, license, download instructions, checksum, citation.

## What must NOT be placed here

- Any logic the core or research modules should rely on at import time.
- Chart-rendering engines (belong in `visualization/` behind the `VizEngine` interface).
- Raw data files (gitignored).

## Status

Planned — implemented in Phase 2 (M2.1). See [`docs/04_Phase_Roadmap.md`](../../../../docs/04_Phase_Roadmap.md).

## Conformance

Must pass `tests/conformance/` (generic adapter conformance suite) before merge.
