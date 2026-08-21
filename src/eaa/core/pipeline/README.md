# `core/pipeline/` — Pipeline Engine + Baseline Stages

## Purpose

The unit of composition for research steps. Stages with typed inputs/outputs compose
into a pipeline (a directed acyclic graph) executed by a runner. Alongside the engine,
generic **dataset-independent** baseline stages (M1.2) live in `stages/`.

## Responsibilities

- Define `Stage` (name, version, input/output contracts, `run`).
- Define `Pipeline` + `PipelineBuilder` (DAG construction with named ports).
- Runner: contract validation at each port, stage-level artifact recording, budget
  enforcement (time/tokens/retries), typed error routing.
- `RuntimeContext`: shared state (db id, resolved schema, metadata, budget, run id,
  event sink).
- Baseline stages (`stages/`): prompt building, LLM generation via `LLMBackend`,
  baseline SQL validation, and offline evaluation. These are dataset-independent
  (ADR-002/006): collaborators are injected via interfaces (`LLMBackend`,
  `SchemaProvider`) and callables (`gold_for`), and stage logic switches on `type_key`
  only (ADR-001). `build_baseline_pipeline(...)` in `pipeline.py` wires them as
  prompt_builder → llm_generation → validation (+ evaluation when `gold_for` is
  injected).

## What must NOT be placed here

- Dataset-specific logic or stages (they belong in the dataset adapter). Research-heavy
  stages — ambiguity resolution, schema linking, SQL self-correction, security —
  live in their own module directories.
- Direct provider SDK calls: LLM access goes through the `LLMBackend` interface only.
- SQL execution.
- Any dataset-specific logic or dataset names.

## Notes

- Stage implementations are registered (strategy), so pipelines are configurable
  without code changes.
- A null/lightweight default runner should support dry runs without external services.
- Reserved state keys for the baseline (`core:pipeline:prompt|generation|validation|report`)
  are defined in `stage.py`; the runner snapshots them as JSON-safe artifacts.
