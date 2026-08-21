# `experiments/` — Evaluation Run Drivers

## Purpose

Reproducible evaluation drivers that compose core pipelines, dataset adapters,
LLM backends, the offline harness, and the artifact store. This package lives
outside `core/` on purpose: it owns no contracts and adds no dataset logic.

## Responsibilities

- `baseline.py` — `BaselineExperiment.run(split=, limit=)` and
  `build_baseline_experiment(...)`. Loads the config, resolves the adapter (via
  the `eaa.datasets` entry-point group, optionally pointed at
  `dataset.data_root`), builds the LLM backend, runs the M1.2 baseline pipeline,
  evaluates offline through `EvaluationHarness`, and records the run with
  `ArtifactStore` + `ArtifactStoreTracker`.
- `cli.py` — `eaa-run-baseline` entry point; `--config`, `--split`, `--limit`,
  `--artifact-root`, `--run-id`, repeatable `--override key=value`.
- `errors.py` — `ExperimentError` (subclass of the core `EAAError`).

## Run flow

```
configs/experiments/phase1_baseline.yaml
  -> resolve_config (default.yaml + datasets/<d>.yaml + overrides/env)
  -> adapter + LLM backend
  -> build_baseline_pipeline (prompt_builder -> llm_generation -> validation)
  -> EvaluationHarness (exact_match, clean_prediction_rate)
  -> ArtifactStore (experiments/runs/<run_id>/...)
```

Every run writes the canonical artifact layout (see `core/experiments/README.md`):
`config.resolved.json`, `meta.json`, `metrics.json`, `predictions/*.json`, and an
offline `artifacts/evaluation_report.json`.

## Rules

- Drivers compose existing pieces; they never reimplement pipeline stages or
  evaluation logic.
- Run-level evaluation happens in the harness, not the per-task pipeline stage
  (ADR-009).
- Configs live in `configs/experiments/`; no dataset name or heavy dependency
  enters core (enforced by the conformance import guard).
