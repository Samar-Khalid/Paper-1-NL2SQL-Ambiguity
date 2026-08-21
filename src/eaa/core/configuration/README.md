# `core/configuration/` — Configuration

## Purpose

Typed, layered, validated configuration for runs, models, datasets, and experiments.

## Responsibilities

- Define pydantic models for config sections (defaults, dataset, model, experiment, eval, logging, security).
- Load and merge layered sources: defaults → config files → CLI overrides → env vars.
- Validate cross-section consistency (e.g., an evaluator requires a benchmark adapter).
- Serialize the fully resolved config for reproducibility (recorded with every run).

## What must NOT be placed here

- Hardcoded dataset/model specifics (they belong in `configs/` templates and adapter manifests).
- Secret values (env vars / secret store only).
- Config *files* — templates live in [`configs/`](../../configs/).
