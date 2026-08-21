# `core/contracts/` — Data Contracts (Contract-First)

## Purpose

The single source of truth for every object that crosses a module boundary. The **contract-first** core of the framework (ADR-001).

## Responsibilities

- Define the generic contracts: `Task`, `Prediction`, `GoldReference`, `RuntimeContext`, `AnalysisReport`.
- Define supporting contracts: schema, query result, metrics, manifests, LLM messages/completions, chart specs, intents.
- Enforce the **envelope + typed payload** design: envelopes carry a `type_key` and an opaque typed `payload`; payload validation is delegated to `core/registry/payload_registry.py`.
- Provide the built-in (dataset-independent) payload types for NL2SQL, NL2VIS, and decision tasks.

## What must NOT be placed here

- Protocol definitions (they live in `core/interfaces/`).
- Any dataset/benchmark-specific logic or names (they stay in `datasets/adapters/`).
- Payload *registration* (lives in `core/registry/`).
- Algorithms, I/O, or side effects — contracts are pure data.

## Rules

- Contracts import only the standard library and pydantic.
- Contracts are immutable and strict (`frozen`, `extra="forbid"`).
- New payload types are registered in the payload registry, never hardcoded into core control flow.
