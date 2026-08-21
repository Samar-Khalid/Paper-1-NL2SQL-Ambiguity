# `core/observability/` — Observability

## Purpose

Structured logging, event streaming, tracing spans, and redaction — the
observability layer for reproducible research runs (see ADR-003 for the session
context that these components carry).

## Responsibilities

- `config.py` — structlog-based structured logging (JSON or console).
- `events.py` — in-process event bus for lifecycle events (task started/finished,
  metrics computed, artifacts written).
- `tracing.py` — minimal trace/span helpers (parent-child spans keyed by
  `session_id`/`run_id`).
- `redaction.py` — redaction of secrets and PII at the boundary.

## Rules

- Never log raw LLM prompts or query results by default; always route through
  the redactor.
- Events must be dataclasses/simple records, not log strings.
