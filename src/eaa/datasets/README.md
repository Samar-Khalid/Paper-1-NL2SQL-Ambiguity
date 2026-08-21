# `datasets/` — Datasets & Benchmark Adapters

## Purpose

The dataset-independence seam. This package holds **interfaces for datasets** and the **concrete adapters** for specific datasets/benchmarks.

## Responsibilities

- `adapters/<name>/` — one package per dataset/benchmark (BEAVER, NVBench 2.0, future: Spider, BIRD, custom).
- Each adapter implements the core interfaces: schema provider, task loader, splits, gold references, dataset-specific metrics, and a manifest (version, license, checksum, citation).
- Provide reusable loader helpers where datasets share formats (base_utils).

## What must NOT be placed here

- Anything the core needs at import time: the core must never import this package.
- Dataset **data files** (gitignored `data/`).
- Dataset-specific logic outside `adapters/`.

## Conformance

Every adapter must pass `tests/conformance/` before it is considered complete — this is how dataset independence is enforced.
