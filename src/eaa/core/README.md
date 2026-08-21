# `core/` — Framework Core

## Purpose

The dataset-independent engine: interfaces, pipeline, and configuration. This is the layer everything else builds on, and the layer that must stay cleanest.

## Responsibilities

- `interfaces/` — Protocols defining module and adapter boundaries.
- `pipeline/` — Stage/pipeline/runner abstractions and budget enforcement.
- `configuration/` — Typed, layered, validated configuration.

## What must NOT be placed here

- Any dataset/benchmark-specific logic (no BEAVER/NVBench names or imports).
- Concrete model implementations (they live in the research modules).
- Adapter implementations (LLM backends, executors, dataset loaders).
- Application/CLI code.

## Rules

- Core depends only on the standard library, pydantic, and other core modules.
- Core never imports `datasets/` or any adapter. Enforced by conformance tests + CI dependency guard.
