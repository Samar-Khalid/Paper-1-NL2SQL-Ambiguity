# `src/` — Framework Source (`eaa.*` namespace)

The framework source tree. **This is a skeleton: no ML models or application code exist yet.**

## Purpose

- Home of the dataset-independent Enterprise AI Analyst framework under the
  `eaa.*` namespace (ADR-005): `eaa.core.*`, `eaa.datasets.*`, `eaa.llm`, …
- Import root during development (via editable install / PYTHONPATH).
- Split into three kinds of code: **core** (reusable engine), **research
  modules** (per-capability logic), and **dataset adapters** (benchmark-specific
  glue).

## Core sub-packages

| Package | Responsibility | ADR |
|---|---|---|
| `eaa.core.contracts` | Generic contracts (`Task`, `Prediction`, `GoldReference`, `RuntimeContext`, `AnalysisReport`) as envelope + typed payload | ADR-001 |
| `eaa.core.interfaces` | Structural protocols for adapters and module boundaries | ADR-001/002 |
| `eaa.core.registry` | Payload/type registries and entry-point plugin manager | ADR-002 |
| `eaa.core.pipeline` | Stage + pipeline + runner + budget | ADR-008 |
| `eaa.core.configuration` | Typed, layered config loading/validation | ADR-010 |
| `eaa.core.observability` | Structured logging, events, tracing, redaction | ADR-003 |
| `eaa.core.experiments` | RunId, artifact layout, tracking | — |

## Responsibilities

- Provide the architecture laid out in [`docs/03_System_Architecture.md`](../../docs/03_System_Architecture.md) and [`architecture/system_design.md`](../../architecture/system_design.md).
- Enforce dataset independence: the core never imports or references dataset adapters.
- Grow incrementally per the roadmap ([`docs/04_Phase_Roadmap.md`](../../docs/04_Phase_Roadmap.md)).

## What must NOT be placed here

- Dataset/benchmark **data files** (they live in a gitignored `data/` location).
- **Run artifacts** (predictions, logs, outputs) — they live in `experiments/*/runs/` (gitignored).
- **Notebooks** — they live in `notebooks/`.
- Third-party source code vendored into the tree.
- Dataset-specific logic outside `src/eaa/datasets/adapters/`.
