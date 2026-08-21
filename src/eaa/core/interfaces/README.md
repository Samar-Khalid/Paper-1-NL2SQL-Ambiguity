# `core/interfaces/` — Core Interfaces (Protocols)

## Purpose

The contracts that decouple the core from implementations and from datasets. This is the dataset-independence boundary.

## Responsibilities

- Define protocols: `DatasetAdapter`, `BenchmarkAdapter`, `SchemaProvider`, `SchemaLinker`, `LLMBackend`, `QueryExecutor`, `Metric`, `Evaluator`, `VizEngine` (Phase 2), `Tracker`, and supporting data models (schema, task, prediction, gold, result).
- Define null/lightweight defaults so code runs without external services.
- Version the contracts; changes are documented (ADR + CHANGELOG).

## What must NOT be placed here

- Implementations (backends, executors, adapters, metrics).
- Dataset-specific types.
- Concrete pipeline stages.

## Rules

- Interfaces import only pydantic + stdlib.
- Everything else depends on these interfaces, never on each other's internals.
