# `ambiguity_resolution/` — Ambiguity Resolution (Phase 1)

## Purpose

Detect, formalize, and resolve ambiguous or imprecise enterprise questions **before** SQL generation — the core research novelty of Phase 1 (RQ1.1).

## Responsibilities

- Detect ambiguity signals in a question (vague business terms, missing constraints, multiple plausible readings).
- Formalize ambiguity into candidate interpretations (structured question hypotheses).
- Resolve by clarifying interaction, metadata lookup, or ranking interpretations.
- Decide when a question is unanswerable and should be refused (answerability, RQ1.4, evaluated on the project's self-labeled subset per ADR-013 — the BEAVER benchmark itself ships no answerability labels).

## What must NOT be placed here

- Schema linking (consumes the clarified question; lives in `schema_linking/`).
- SQL generation or validation.
- Dataset-specific logic.

## Status

Slice 1 (M1.5) — the module boundary is in place and dataset-independent
(ADR-014/006):

- `core/contracts/ambiguity.py` — `AmbiguityType` (taxonomy, docs/12),
  `AmbiguityVerdict`, `AmbiguitySpan`, `Assumption`, `AmbiguityAnalysis`,
  `ClarifiedQuestion`, `AnswerabilityVerdict`.
- `core/interfaces/ambiguity.py` — `AmbiguityResolver` and
  `AnswerabilityJudger` protocols.
- `errors.py` — `AmbiguityResolutionError`.

Slice 2 (M1.5) — annotation loading foundation:

- `annotations/models.py` — immutable typed representation of the
  `annotation-schema-v1` labels (docs/13 §5): `Answerability`,
  `Interpretation`, `AnnotationSpan`, `AnnotatedQuestion`, `AnnotationRecord`,
  `AnnotationDataset`. Strict (unknown fields rejected) and frozen.
- `annotations/loader.py` — `AnnotationDatasetLoader`: loads a single object,
  an array, or a directory of `.json` label files; validates schema version,
  required fields, ambiguity codes, span bounds/text integrity, interpretation
  pairs, and dataset-wide `question_id` uniqueness.
- `annotations/stats.py` — `compute_stats` / `AnnotationDatasetStats`:
  read-only aggregate counts (questions, span count per ambiguity family,
  distinct ambiguity types, answerability split, interpretation count).
- `annotations/errors.py` — `AnnotationLoadError` and
  `AnnotationValidationError` (carrying `question_id` in `context`).

Slice 3 (M1.5) — ambiguity detectors (both evidence families, slices 2.8 + 2.9):

- `detectors/text_matching.py` — deterministic tokenization, phrase/span
  lookup, and plural normalization (docs/13 §5 half-open offsets).
- `detectors/schema_index.py` — `SchemaIndex`: normalized lookups over an
  `EnrichedSchema` (column aliases from business terms/synonyms, units, domain
  values, table descriptions, rule definitions, fiscal conventions, hierarchy
  columns); empty when no enrichment exists.
- `detectors/metadata_grounded.py` — `MetadataGroundedDetector` implements
  `AmbiguityResolver.analyze` (docs/14 §4A) and emits the metadata-closable
  band for exactly the seven enrichment-resolvable taxonomy types (L2, R1, V1,
  V2, V3, T2, K2) with fixed deterministic confidence per evidence kind. Reads
  only the task question and the injected schema/enrichment; against a plain
  `DatabaseSchema` it always reports `unambiguous`. Verdict is
  `underdetermined` when spans are found (metadata-closable underspecification,
  docs/15 §3.1). `resolve` is intentionally unimplemented (later slice).
- `detectors/reasoning_based.py` — `ReasoningBasedDetector` implements
  `AmbiguityResolver.analyze` for the second evidence family (docs/14 §4B):
  model-based, defeasible judgments over the question against the schema and
  its enrichment that establish the persistent-ambiguity band for exactly the
  ten taxonomy types metadata cannot close (S1, S2, R2, C1, C2, C3, T1, K1,
  I2, I3). It calls the existing `LLMBackend` protocol with a
  dataset-independent prompt (question + compact schema + enrichment context)
  and strictly parses the structured JSON judgment into the existing
  `AmbiguityAnalysis` contract; invalid or out-of-scope spans are dropped
  (conservative non-detection). Every call and its tokens are reported through
  the run's `BudgetLedger` (`context.state[BUDGET_LEDGER_KEY]`); running
  outside a pipeline raises `PipelineError`. Verdict is `ambiguous` when at
  least one persistent span survives, otherwise `unambiguous`. `resolve` is
  intentionally unimplemented (later slice).

Still absent: the formalizer, resolver, answerability judge, and the pipeline
stage. The stage graph and `configs` `pipeline.stages` already reserve the
insertion point (docs/11 §4.1), and `AmbiguityConfig` defaults to
`resolution: off`, so no pipeline behavior changes until a stage is wired.
