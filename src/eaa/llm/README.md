# `llm/` — LLM Abstraction Layer

## Purpose

Provider-agnostic access to LLMs with prompt management, caching, guardrails, and cost accounting. The framework must not be tied to one provider or local/API.

## Responsibilities

- Define/implement the `LLMBackend` interface (chat/completion, optional tool use).
- Prompt management: versioned templates, registry, serialization of the exact prompt used (prompt provenance).
- Completion caching (hash of normalized prompt + model + params).
- Guardrail hook points (prompt-injection defense, output filtering) — see `security/`.
- Token and cost accounting per call and per run.

## What must NOT be placed here

- Task logic (SQL generation, narratives) — this layer is transport only.
- Dataset-specific prompts (they belong with adapters or a prompts module).
- Model weights or API keys.

## Status

Backends in Phase 0 (M0.5); prompt management from Phase 1.
