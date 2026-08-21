# `core/experiments/` — Experiments

## Purpose

Run identity, artifact layout, and tracking primitives so every research run is
reproducible and comparable (config resolved, metrics, predictions, traces).

## Responsibilities

- `run_id.py` — generate and parse ``RunId`` (short unique id + timestamp + optional dataset tag).
- `artifacts.py` — ``ArtifactStore`` enforcing the canonical layout:
  ``experiments/runs/<run_id>/config.resolved.yaml``, ``meta.json``,
  ``metrics.json``, ``predictions/``, ``artifacts/``, ``logs/``, ``traces.jsonl``.
- `tracker.py` — ``Tracker`` protocol + ``NullTracker`` (used by the evaluation
  harness and by pipeline stages to record metrics).

## Rules

- Nothing outside the experiments module may construct artifact paths by hand.
- Config snapshots are written once per run and never mutated afterwards.
