# `evaluation/` — Evaluation Subsystem

## Purpose

The measurement layer: metric registry, evaluation harness, statistical analysis, and reports. **Decoupled from prediction** so measurement never changes when modules change.

## Responsibilities

- `Metric` interface + registry of core metrics (EX, EM, valid-SQL rate, …).
- `Evaluator` harness: benchmark adapter + predictions + gold → `EvaluationReport`.
- Statistical tools: bootstrap CIs, paired significance tests, aggregation.
- Leakage checks (gold never reaches prediction paths).
- Human review queue for unjudgeable cases.
- Report serialization (JSON/markdown/HTML) and tracking integration.

## What must NOT be placed here

- Pipeline stages or models under test.
- Dataset-specific metric implementations (they register from adapters).
- Any prediction-time logic.

## Status

Skeleton in Phase 0 (M0.6); metric families grow per phase (see [`docs/07_Evaluation_Framework.md`](../../docs/07_Evaluation_Framework.md)).
