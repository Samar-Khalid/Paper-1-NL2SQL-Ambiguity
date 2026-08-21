# `datasets/adapters/` — Concrete Dataset Adapters

## Purpose

One adapter package per dataset/benchmark. This is the **only** place where dataset-specific names (BEAVER, NVBench 2.0, …) may appear.

## Responsibilities

- Implement the core interfaces for each dataset.
- Translate raw dataset files into core contracts (schema, tasks, gold references, splits).
- Register dataset-specific metrics with the evaluation subsystem.
- Maintain a manifest per dataset: version, license, download instructions, checksum, canonical citation.

## What must NOT be placed here

- Anything reusable across datasets (that belongs in core or a shared helper).
- Dataset data files (gitignored `data/`).
- Changes to core or research modules "to make a dataset work" — if an adapter needs it, the **interface** is the thing to fix (via ADR), not the adapter.

## Conformance requirement

Each adapter ships a conformance test in `tests/conformance/` and must pass `make test-conformance`.
