# 11. Phase 1 Design — Enterprise NL2SQL (BEAVER)

- **Status:** Partial implementation. M1.1 (adapter, §3.6) and M1.2 (baseline pipeline, §3.7) are landed; the remaining milestones are pre-implementation.
- **Version:** 0.2
- **Date:** 2026-08-03
- **Author:** Phase 1 design review
- **Relates to:** RQ1.1–RQ1.4 (docs/02), ADR-001/002/003/004/008/009/011/012, docs/04 (M1.1–M1.11), docs/05, docs/06, docs/07
- **Primary artifact:** this document. ADR-013 is finalized; the remaining proposed ADR texts are flagged for finalization at implementation kickoff (Section 15).

---

## 1. Purpose and Scope

Phase 1 delivers a **robust, enterprise-aware NL2SQL engine** and a **reliability
evaluation campaign** on the BEAVER benchmark, running on the Phase 0 contract-first
foundation (`src/eaa/core/`). This document fixes the design **before** code:

1. How BEAVER connects through the dataset-adapter boundary.
2. The Phase 1 pipeline architecture (stages, runner, budget, settings).
3. The end-to-end data flow with contracts at every boundary.
4. The core contracts consumed and the new generic contracts Phase 1 introduces.
5. The new modules, their responsibilities, and their interfaces.
6. A pre-registered experiment plan, a baseline, and the evaluation metric set.
7. The research-contribution agenda for ambiguity, metadata, schema linking, and SQL reliability.

Out of scope: implementation, Phase 2+ capabilities, dataset code in core.

---

## 2. BEAVER Benchmark Facts and the Version Decision

### 2.1 What BEAVER actually is (Chen et al., 2024/2025)

BEAVER is an **enterprise text-to-SQL benchmark** derived from real, private data
warehouses (paper: *BEAVER: An Enterprise Benchmark for Text-to-SQL*, Chen et al., 2024;
project + leaderboard at beaverbench.github.io):

- 9,128 question-SQL pairs, 812 tables, 19 domains, collected from real query logs;
  ~7,978 queries publicly released, the remainder held out as a private test set.
- Two anonymized warehouses: **DW** (facilities/physical plant, ~99 tables, 1,544
  columns) and **NW** (networking/virtual machines). MySQL dialect (DW queries
  translated from Oracle to MySQL).
- Queries are harder than public benchmarks (avg ~4.25 joins, ~4.67 aggregations,
  nesting depth ~1.95 vs Spider/BIRD ~0.5/1.1); average ~105 tables per database.
- **Five subtask annotations:** multi-table retrieval, join-key detection, column
  mapping, domain-knowledge extraction, query decomposition.
- **Three query categories:** complex without domain knowledge; domain-specific with
  minimal complexity; domain-specific complex.
- **Two official settings:** *retrieval-free* (gold tables provided; isolates SQL
  generation) and *retrieval* (top-k retrieved tables; adds table retrieval).
- Reported failure analysis: table-retrieval recall failure dominates (~89% of
  retrieval errors); generation errors largely stem from database-specific rules /
  custom functions (~41.5%) and unfamiliar enterprise schemas.

These numbers are cited for motivation; the adapter must verify them against the
**pinned dataset version** at download and record them in the manifest.

### 2.2 A conflation in the current repo (Decision D1, resolved)

`docs/01_Research_Gap.md`, `docs/05_Dataset_Strategy.md`, and
`configs/datasets/beaver.yaml` previously described BEAVER as "Du et al., 2023 — imprecise
questions + answerability", and `configs/experiments/phase1_beaver_eval.yaml` listed
`answerability_accuracy`. That description matches a **different** dataset (a Microsoft
BEAVER probing imprecise questions and answerability), not the Chen et al. benchmark
whose schema/tables this project's adapter path targets.

**Decision D1 (resolved by ADR-013):** the Phase 1 target is the Chen et al. BEAVER
enterprise text-to-SQL benchmark (aligns with "Enterprise NL2SQL" and with
`src/eaa/datasets/adapters/beaver/`). Consequence: the official metric set is
**execution accuracy under the retrieval and retrieval-free settings** plus the five
subtask annotations, not `answerability_accuracy`. Answerability (RQ1.4) is retained
as a **research metric** (Section 13.4) measured on a self-constructed, labeled subset,
because Chen et al. BEAVER does not ship unanswerable-question labels.

**Follow-up (done):** `docs/01`, `docs/05`, `docs/02`, and `configs/` wording
corrected and recorded as ADR-013 (`architecture/adrs/ADR-013-beaver-benchmark-identity.md`).

### 2.3 Data governance

- Raw data: `data/raw/beaver/` (gitignored), downloaded via adapter instructions;
  checksum recorded in `DatasetManifest`.
- License: **confirm** at download (the public GitHub distribution is MIT; the
  leaderboard/website distribution may differ). The manifest is authoritative; the
  repo redistributes no data.
- Dialect/executor: MySQL (DW in MySQL dialect). See Section 7.9.

---

## 3. BEAVER Adapter Design and Integration (Point 1)

### 3.1 Location and boundary

Everything BEAVER-specific lives in `src/eaa/datasets/adapters/beaver/`. Core modules
never import it (ADR-002/006). The adapter is discovered via the entry-point group
`eaa.datasets`:

```text
[project.entry-points."eaa.datasets"]
beaver = "eaa.datasets.adapters.beaver:plugin"
```

where `plugin()` is a zero-arg factory returning a `BeaverAdapter` instance that
satisfies `DatasetAdapter` + `BenchmarkAdapter`.

### 3.2 What the adapter provides

| Adapter responsibility | Interface | Phase 1 content |
|---|---|---|
| Identity + governance | `DatasetAdapter.manifest()` | `DatasetManifest`: name, version, license, citation, `type_keys=["nl2sql"]`, splits `["dev","test"]`, checksum, entry points |
| Schema | `DatasetAdapter.schema()` | Primary/aggregate `DatabaseSchema` for BEAVER (satisfies the interface; see 3.3) |
| Per-database schema | `SchemaProvider` (new `schema_provider()` hook, see 3.3) | One `DatabaseSchema` per warehouse: `beaver_dw`, `beaver_nw` |
| Metadata sidecar (data only) | adapter data files / `metadata/` reader | Synonyms, business terms, unit/domain values per column; **authored as data**, merged by `metadata/` into `EnrichedSchema` |
| Tasks | `BenchmarkAdapter.task_stream(split)` | Yields `TaskEnvelope(nl2sql)` — question, `database_id`, `dataset_id`, dialect, tags |
| Gold | `BenchmarkAdapter.gold_for(task_id)` | `GoldReferenceEnvelope(gold.nl2sql)` with `SqlGoldReference(sql)`; used only by the evaluation harness (ADR-009) |
| Splits | `BenchmarkAdapter.splits()` | `["dev","test"]`; official splits honored; private set handled as "unavailable locally" |
| Metrics | adapter registers via the metrics registry (`<owner>:<name>`) | Execution accuracy (retrieval + retrieval-free), table-retrieval recall@k, subtask scores, query-category breakdown |
| Executor | adapter registers `QueryExecutor` | Read-only MySQL executor for BEAVER (Section 7.9) |

### 3.3 Interface refinements the adapter needs (Decision D2)

- `DatasetAdapter` currently exposes one `schema()`. BEAVER has two warehouses.
  Proposal: add an optional `schema_provider() -> SchemaProvider` to the adapter
  boundary so a dataset can expose per-`database_id` schemas (the
  `SchemaProvider.get_schema(database_id)` contract already exists). `schema()` keeps
  returning an aggregate for conformance simplicity.
- The adapter may publish a **metadata sidecar** (raw synonyms/terms) without new core
  types: reuse `ColumnSemantics` and `table_descriptions` from the contracts; the
  `metadata/` module owns merge logic. No dataset name enters core.

### 3.4 Conformance

`tests/conformance/adapters/beaver/` runs the generic adapter conformance suite:
contract shapes, split determinism, gold never reachable from prediction paths,
manifest integrity, and the R1/R2 import guard (no `beaver` in core). Green conformance
is the M1.1 exit criterion.

### 3.5 Configuration

`configs/datasets/beaver.yaml` extended (template only): pinned version, dialect,
data paths, linking setting (`retrieval_free` | `retrieval`), table budget `k`, and
which metric groups to load. All options typed by the Phase 0 configuration module.

### 3.6 M1.1 status

The adapter is **implemented** (`src/eaa/datasets/adapters/beaver/`):

- `format.py` parses the raw record shapes of both known BEAVER distributions;
- `manifest.py` pins the data-contract version (`1.0`) and verifies the adapter-local
  `manifest.json` (version + deterministic sha256 checksum, docs/05 §5);
- `loader.py` converts raw files into `DatabaseSchema`, `TaskEnvelope(nl2sql)` and
  `GoldReferenceEnvelope(gold.nl2sql)` **via the payload registry only** (ADR-001/002),
  and builds per-sample `RuntimeContext`; gold tables/join keys/column mappings and the
  five-subtask annotations ride in the gold envelope `metadata` (eval-only, ADR-009);
- `adapter.py` implements `DatasetAdapter` + `BenchmarkAdapter` plus `schema_provider()`
  (Decision D2) and `samples()` (task, gold, context) triples; `splits()` reports the
  locally downloaded splits while `DatasetManifest.splits` keeps the benchmark identity
  `["dev","test"]`;
- the `beaver` entry point (`eaa.datasets` group) is registered in `pyproject.toml`;
- `configs/datasets/beaver.yaml` is extended with generic typed options
  (`dialect`, `data_root`, `linking_mode`, `table_budget`, `metric_groups`) — the only
  core change is the generic `DatasetConfig` schema; no dataset name entered core.

Conformance: `tests/conformance/adapters/beaver/` runs the generic adapter conformance
suite (contract shapes, split determinism, gold unreachable from task paths, manifest
integrity, R1/R2 import guard) plus BEAVER-specific identity/integrity checks; the suite
is green. A dataset addition made no change to `src/eaa/core/` interfaces, pipeline, or
evaluation modules.

### 3.7 M1.2 status — dataset-independent baseline pipeline

The generic baseline stages and their composition are **implemented** under
`src/eaa/core/pipeline/stages/` (dataset-independent, ADR-002/006). The factory
`build_baseline_pipeline(llm, schema_provider, *, gold_for, harness, run_id,
prompt_version, budget)` in `core/pipeline/pipeline.py` wraps
`BaselinePipelineBuilder` (`core/pipeline/builder.py`) and wires four stages:

- `prompt_builder` — renders a versioned prompt (`PROMPT_VERSION = "baseline-v1"`,
  ADR-004) from the task question and the `SchemaProvider` schema; stores it under
  `core:pipeline:prompt`.
- `llm_generation` — calls `LLMBackend.complete` (ADR-012), extracts fenced/plain SQL
  via `extract_sql`, and emits `PredictionEnvelope(prediction.nl2sql)` with provenance;
  malformed output becomes `PredictionError(error_type="sql_parse_failure")` inside the
  envelope (never an exception at the boundary), and usage is charged to the
  `BudgetLedger` (ADR-003).
- `validation` — `validate_sql` runs the baseline checks (non-empty, single-statement,
  read-only, tables-exist) and stores the verdict under `core:pipeline:validation` and
  in prediction metadata.
- `evaluation` — offline (ADR-009), appended only when a `gold_for` callable is
  injected; produces `EvaluationReportEnvelope` under `core:pipeline:report` through
  `EvaluationHarness` (default `run_id` = session id).

New reserved state keys live in `core/pipeline/stage.py`
(`core:pipeline:prompt|generation|validation|report`). No dataset name, schema, or
logic entered core; stage code switches on `type_key` only (ADR-001). This is the
generation path of the §4.1 graph (schema → generic prompt → LLM → validation →
offline evaluation); ambiguity, metadata, linking, self-correction, and security
stages arrive in M1.4–M1.9.

Coverage: unit tests per stage (`tests/unit/core/pipeline/stages/`) and
`tests/unit/core/pipeline/test_baseline_builder.py`; the end-to-end test
`tests/e2e/test_baseline_nl2sql_pipeline.py` runs the recorded pipeline against the
M1.1 adapter and asserts tracked artifacts (`config.resolved.json`, `metrics.json`,
`predictions/*.json`). Full suite green (297 tests), `mypy` clean (78 source files),
`ruff` clean.

### 3.8 M1.3 status — baseline evaluation setup

The M1.2 pipeline and the M1.1 adapter are wired into a reproducible evaluation
campaign without touching core. `src/eaa/experiments/` provides the run driver
(`BaselineExperiment.run(split=, limit=)`, `build_baseline_experiment`) and the
`eaa-run-baseline` CLI. The flow is:

```
configs/experiments/phase1_baseline.yaml
  -> resolve_config (default.yaml + datasets/beaver.yaml + overrides/env)
  -> adapter (entry-point plugin, optional dataset.data_root) + LLM backend
  -> build_baseline_pipeline (prompt_builder -> llm_generation -> validation)
  -> EvaluationHarness (offline, exact_match + clean_prediction_rate)
  -> ArtifactStore (experiments/runs/<run_id>/...)
```

`phase1_baseline.yaml` pins the whole protocol — `prompt_version: baseline-v1`,
`max_llm_calls: 1` (no self-correction), echo provider by default, dev split,
`[exact_match, clean_prediction_rate]`. Every run snapshots the resolved config
(`config.resolved.json`), writes `meta.json` (dataset manifest version, split,
prompt version, model id), per-task `predictions/*.json`, and an offline
`evaluation_report.json` under `artifacts/`; `metrics.json` holds the run-level
aggregates (ADR-009: evaluation at the run, not the stage, for campaign metrics).

The driver composes only existing pieces (core pipeline, harness, artifact store,
tracker, registry); no dataset name or heavy dependency entered core. Coverage:
`tests/unit/experiments/test_baseline_{config,driver}.py` and
`tests/e2e/test_baseline_evaluation.py` (synthetic BEAVER root, question→gold
mapping, full artifact tree asserted). Full suite green (311 tests), `mypy` clean
(82 source files), `ruff` clean, `eaa-run-baseline` verified against synthetic data.

### 3.9 M1.4 status — metadata model + schema enrichment

The generic metadata layer (ADR-015) ships without touching the dataset
boundary:

- **Enrichment model.** `EnrichedSchema` *extends* `DatabaseSchema`
  (composition over a parallel model); `EnrichmentData` is the generic source
  document (`database_id`, `table_descriptions`, `column_semantics` per
  table/column, `relationships` with `foreign_key`/`semantic` kinds).
  `EnrichedSchema.has_enrichment` distinguishes a contentful enriched schema
  from an empty one (which renders byte-identical to the base).
- **Boundary.** Adapters publish enrichment as *data* via a `metadata()`
  factory (mirroring `schema_provider()`, Decision D2) returning a
  `MetadataProvider` (`metadata(database_id) -> EnrichmentData | None`).
  `eaa.metadata` owns the merge (`enrich_schema` with reference validation →
  `MetadataError`) and composes base + metadata through
  `EnrichedSchemaProvider`. Core defines only the `MetadataProvider` protocol.
- **Controlled OFF/ON experiment.** `schema.enriched` (generic `SchemaConfig`
  toggle) selects the arm: OFF injects the base `SchemaProvider`
  (`phase1_baseline.yaml`), ON injects `EnrichedSchemaProvider`
  (`phase1_metadata.yaml`). The prompt builder detects a contentful enriched
  schema and renders the versioned `enriched-v1` prompt (baseline-v1 stays
  byte-identical); prediction provenance records the effective version.
  Enabling the toggle over an adapter with no metadata source fails loudly
  rather than silently degrading to a baseline run.
- **BEAVER sidecar.** The adapter reads an optional per-database
  `enrichment.json` in the generic `EnrichmentData` shape
  (`src/eaa/datasets/adapters/beaver/metadata.py`); a database without a
  sidecar degrades to the base schema.

Coverage: `tests/unit/metadata/test_enrichment.py`,
`tests/unit/datasets/adapters/beaver/test_metadata.py`, enriched prompt/stage
tests, driver toggle tests, and `tests/e2e/test_metadata_evaluation.py` (both
arms on one synthetic root; ON records `enriched-v1` with the glossary actually
fed to the LLM, OFF records `baseline-v1`). Full suite green (349 tests),
`mypy` clean (87 source files), `ruff` clean, both arms verified end-to-end via
`eaa-run-baseline`.

---

## 4. Phase 1 Pipeline Architecture (Point 2)

### 4.1 Stage graph

Built on the ADR-008 engine (typed `Stage` with `input_contract` / `output_contract`,
`PipelineBuilder`, budget-enforcing `Runner`). Phase 1 graph:

```text
TaskEnvelope(nl2sql)
   │
   ▼
[ ambiguity_resolution ]  ── branch when answerable=false/needs-assumption ──┐
   │  (detect -> formalize -> resolve; may emit assumptions)                │
   ▼                                                                        │
[ schema_representation ]  (select representation: full | enriched | top-k) │
   │                                                                        │
   ▼                                                                        │
[ schema_linking ]  (heuristic | llm | metadata-aware) -> LinkedSchema      │
   │                                                                        │
   ▼                                                                        │
[ sql_generation ]  ──────┐                                                 │
   │                      │  bounded self-correction loop (budget:          │
   ▼                      │  max_llm_calls, max_rounds)                     │
[ sql_validation ]        │  ┌──────────────────────────────────┐          │
   │  (syntax/semantic/   └──┤ sql_correction (LLM, feedback)  │          │
   │   execution, security)   └──────────────────────────────────┘          │
   ▼                                                                        │
[ execution ]  (QueryExecutor, read-only) -> QueryResult                    │
   │                                                                        │
   ▼                                                                        │
PredictionEnvelope(nl2sql) + answerability verdict + artifacts              │
   │                                                                        │
   ▼ (offline, ADR-009)                                                     │
[ evaluation ]  GoldReferenceEnvelope + PredictionEnvelope -> metrics       │
               -> EvaluationReportEnvelope -> metrics.json -> results/      │
```

**M1.2 baseline subset (implemented, §3.7):** the generic dataset-independent stages
realize only the generation path — schema → prompt (generic, versioned) → LLM →
validation → offline evaluation. The ambiguity branch, metadata-aware linking, and the
self-correction loop arrive with their milestones (M1.4–M1.9).

### 4.2 Two official settings mirrored by config

| Setting | Linking stage | Measures | Used for |
|---|---|---|---|
| `retrieval_free` | bypass/ground truth tables from adapter (eval-only) | SQL generation quality | RQ1.3, model comparison |
| `retrieval` | `schema_linking` selects top-k tables | retrieval + generation | RQ1.1/RQ1.2/RQ1.4, ablations |

The runner configures `linking_mode`; the two settings share the same downstream
stages, keeping measurements comparable (docs/06 §8).

### 4.3 Budgets and safety

`RuntimeContext.budget` (`Budget` contract) is honored by the runner: `max_llm_calls`
bounds the self-correction loop, `max_elapsed_seconds` bounds execution; a
`BudgetExceededError` fails the run safely and is recorded (not crashed). All LLM
calls count against budget; validation and execution respect timeouts and result-size
caps (ADR-011).

### 4.4 Artifacts and traceability

Each stage writes artifacts (linked schema, prompt text, candidate SQL, validation
results) into `RuntimeContext.state` (keyspaced `<owner>:<subkey>`) and to the run
artifact store (docs/06). `Provenance` records `stage`, `model_id`, `prompt_version`
per envelope. This is the raw evidence for error analysis and ablations.

---

## 5. Data Flow (Point 3)

Step-by-step, with the contract at each boundary.

### 5.1 Natural Language Question

`TaskEnvelope(nl2sql)` — `TaskHeader(task_id, question, dataset_id, dialect, tags)` +
`SqlGenerationTask(question, database_id, ...)`. Question and task metadata are the
only things that cross from the adapter into the pipeline.

### 5.2 Enterprise Context

`RuntimeContext` (`SessionState`, `Budget`, `evaluation_mode`, keyspaced `state`)
plus the enterprise knowledge assembled by `metadata/`:

- `EnrichedSchema` (extends `DatabaseSchema`) for `database_id`,
- business glossary / synonyms / units (`ColumnSemantics`, `table_descriptions`),
- dialect and database identity.

The context is *attached to the run*, not baked into the question, so the same
question can be re-run against different enrichment levels (ablation control).

### 5.3 Schema Representation

`schema_representation` stage picks the representation: raw `DatabaseSchema`,
`EnrichedSchema`, or `schema_linking` output `LinkedSchema`. The representation is
**serialized into the prompt by the owner of the format** (ADR-004): adapter-provided
format hooks for BEAVER phrasing; core stages provide generic SQL-writing
instructions. Nothing dataset-named enters generic prompts.

### 5.4 LLM

`LLMBackend.complete(messages, CompletionParams)` returns `Completion` (`Message`,
`Usage`, `model_id`, `finish_reason`). The backend is provider-agnostic (ADR-012);
Phase 1 ships one API-compatible and one local backend. Every completion records
`prompt_version` + `model_id` in provenance; usage is logged and charged to budget.

### 5.5 SQL Prediction

The generation stage emits `PredictionEnvelope(prediction.nl2sql)` with
`SqlPrediction(sql)`, `PredictionHeader(prediction_id, task_id, model_id)` and
metadata (latency, tokens). LLM failure or malformed output becomes `PredictionError`
inside the envelope — never an exception at the stage boundary.

### 5.6 Validation and Self-Correction

`sql_validation` classifies the candidate: syntax (parser), semantics (catalog:
tables/columns/joins exist and are linked), execution-based (read-only run on the
warehouse or a sample), and security (read-only whitelist, ADR-011). On failure the
bounded loop feeds `SqlValidationResult` back to `sql_correction`, up to
`budget.max_llm_calls` / configured rounds. The final envelope carries the validation
verdict as metadata.

### 5.7 Evaluation (offline)

`PredictionStore` holds validated predictions; `GoldStore` (adapter) holds gold.
`evaluation/` combines them per (task, prediction, gold) via `Metric.compute` ->
`MetricResult`; aggregates into `EvaluationReportEnvelope`
(`run_id`, `dataset_id`, `split`, `metric_results`, `summary`, bootstrap CI), writes
`metrics.json`, and summarizes into `results/` (ADR-009, docs/07).

---

## 6. Core Contracts Used and New Contracts (Point 4)

### 6.1 Existing core contracts consumed as-is

| Contract | Use |
|---|---|
| `TaskEnvelope` / `TaskHeader` / `SqlGenerationTask` (`nl2sql`) | Pipeline input |
| `PredictionEnvelope` / `PredictionHeader` / `SqlPrediction` / `PredictionError` | Pipeline output |
| `GoldReferenceEnvelope` / `GoldHeader` / `SqlGoldReference` (`gold.nl2sql`) | Eval gold |
| `RuntimeContext` / `SessionState` / `Budget` / `Turn` | Per-run context, budgets |
| `DatabaseSchema` / `TableSchema` / `ColumnSchema` / `ForeignKeySpec` | Base schema |
| `EnrichedSchema` / `ColumnSemantics` | Enterprise metadata (ADR-001 composition) |
| `QueryResult` / `QueryColumn` | Execution output |
| `MetricResult` / `ReviewSummary` / `EvaluationReportEnvelope` / `EvaluationReportPayload` / `EvaluationReportHeader` | Eval results |
| `DatasetManifest` | Adapter self-description |
| `Message` / `Completion` / `CompletionParams` / `Usage` | LLM boundary |
| `Provenance` | stage/model/prompt traceability |
| `Envelope` / `Payload` / registry helpers (`envelope_for`, `payload`) | Building envelopes |
| `EAAError` taxonomy (`RegistryError`, `PipelineError`, `BudgetExceededError`, `AdapterError`, `ExecutionError`) | Typed failures |

### 6.2 New generic (dataset-independent) contracts to register in Phase 1

Registered as payloads/models in core `contracts/` — **not** in any adapter, because
they describe generic pipeline facts:

| New contract | Purpose | Carried in |
|---|---|---|
| `LinkedSchema` (tables, columns, join edges, per-item confidence) | Output of `schema_linking` | stage artifact + `RuntimeContext.state` |
| `AmbiguityAnalysis` (verdict: unambiguous / ambiguous / underdetermined / unanswerable; assumptions; confidence) | Output of `ambiguity_resolution` | stage artifact |
| `ClarifiedQuestion` (question text + formalized assumptions) | Input to generation after resolution | stage artifact |
| `SqlValidationResult` (valid/error classes, executed flag, safety flag) | Output of `sql_validation`; input to correction | stage artifact + prediction metadata |
| `AnswerabilityVerdict` (answerable + confidence) | RQ1.4 output | prediction metadata |

Rule maintained from ADR-001: core switches on `type_key`, never on concrete payload
classes; these new types are all dataset-independent and live in core contracts.

---

## 7. New Phase 1 Modules (Point 5)

Existing skeletons under `src/eaa/` are filled in; new sub-packages are created only
where a module needs internal structure.

| Module | Responsibility (from docs/03 + system_design) | Phase 1 additions |
|---|---|---|
| `core/pipeline/` | Stage/Pipeline/Runner/budget | Generic baseline stages + `NL2SQLPipeline` builder (M1.2 done); correction-loop wiring; artifact hooks |
| `core/configuration/` | Typed layered config | Phase 1 schema: linking mode, correction rounds, metric groups |
| `datasets/adapters/beaver/` | All BEAVER logic | Section 3; MySQL executor plugin; metric registration |
| `metadata/` | Enriched schema, glossary, synonyms, business terms | `MetadataProvider` implementation; enrichment merge; metadata file readers |
| `ambiguity_resolution/` | Detect/formalize/resolve | Heuristic + LLM detectors; assumption formalization; verdict model |
| `schema_linking/` | Prune/link schema to question | Table retriever (lexical, then LLM); column linking; join-key detection; metadata-aware variant; `LinkedSchema` |
| `llm/` | LLM abstraction, prompts, caching, guardrails | OpenAI-compatible + local backends; response parsing (SQL extraction); cache; prompt infra (ADR-004) |
| `sql_generation/` | Candidate SQL from linked schema | Prompt assembly; few-shot; candidate sampling; `sql_correction` stage |
| `sql_validation/` | Syntax/semantic/execution validation | Validators + error taxonomy + safe sample execution |
| `security/` | Read-only enforcement, redaction, injection defenses | Statement whitelist; executor enforcement hooks; prompt-injection guards (E2E tests) |
| `evaluation/` | Metric registry, harness, statistics, reports | Execution-accuracy metric; validity/robustness/honesty/safety family; bootstrap CI + McNemar; report writers |

Dependencies follow R3/R4 (docs/03): modules depend on core + metadata; they do not
depend on each other directly — composition happens in the pipeline. Adapters may
import only core interfaces + contracts + configuration helpers (R2).

---

## 8. Module Interfaces (Point 6)

Existing protocols are reused unchanged where possible:
`BenchmarkAdapter`, `DatasetAdapter`, `SchemaProvider`, `SchemaLinker`, `LLMBackend`,
`QueryExecutor`, `Metric`, `Evaluator`, `Tracker`, `ComponentRegistry`.

New Phase 1 protocols (conceptual signatures, to be finalized in
`src/eaa/core/interfaces/`):

```python
class MetadataProvider(Protocol):        # implemented by adapters (ADR-015)
    def metadata(self, database_id: str) -> EnrichmentData | None: ...

class AmbiguityResolver(Protocol):       # ambiguity_resolution/
    def analyze(self, task: TaskEnvelope, ctx: RuntimeContext) -> AmbiguityAnalysis: ...
    def resolve(self, analysis: AmbiguityAnalysis, ctx: RuntimeContext) -> ClarifiedQuestion: ...

class SqlValidator(Protocol):            # sql_validation/
    def validate(self, sql: str, schema: DatabaseSchema, ctx: RuntimeContext) -> SqlValidationResult: ...

class SqlCorrector(Protocol):            # sql_generation/ (self-correction)
    def correct(self, prediction: SqlPrediction, validation: SqlValidationResult,
                ctx: RuntimeContext) -> SqlPrediction | None: ...

class AnswerabilityJudger(Protocol):     # ambiguity_resolution/ (RQ1.4)
    def judge(self, task: TaskEnvelope, analysis: AmbiguityAnalysis | None,
              ctx: RuntimeContext) -> AnswerabilityVerdict: ...
```

`MetadataProvider` (accepted in ADR-015) returns the generic enrichment *source*
document; `metadata/` merges it into an `EnrichedSchema` via
`EnrichedSchemaProvider`, which implements the existing `SchemaProvider`
(`get_schema` / `get_enriched_schema`) so downstream stages need no metadata
awareness. Business-term lookup for the metadata-aware linking variant (M1.6)
reads `EnrichedSchema.column_semantics[*][*].business_term`.

Registration: stages and metrics are looked up through `ComponentRegistry` /
`PayloadRegistry` (`<owner>:<name>` keyspace, ADR-002). New payload contracts are
registered via the `payload` decorator + `register_payload`; BEAVER metrics via the
metrics registry (e.g., `beaver:execution_accuracy`).

---

## 9. Configuration and Experiment Layout (Point 7 support)

- Config layers (ADR-010): `configs/default.yaml` -> `configs/datasets/beaver.yaml`
  -> `configs/models/<m>.yaml` -> `configs/experiments/phase1_*.yaml` -> CLI/env.
- Each run dumps the fully resolved config (`config.resolved.json`) with artifacts.
- Runs: `experiments/phase1_nl2sql/runs/<run_id>/` (gitignored).
- Records: `experiments/phase1_nl2sql/` per `_TEMPLATE_experiment_record.md`
  (`phase1-<date>-<seq>` ids). Summaries: `results/`.

---

## 10. Experiment Plan (Point 7)

Pre-registered, per docs/06 (record hypotheses and metric sets before running; tune on
dev only; report intervals).

### 10.1 Campaign structure

| Campaign | Purpose | Configuration axes | RQ |
|---|---|---|---|
| E1 Baseline | Floor measurement; reproduce "off-the-shelf LLM" finding in-repo | linking_mode, model, few-shot, temperature | — |
| E2 Ambiguity on/off | Cost of not resolving; resolution benefit | ambiguity_resolution {on, off}; ambiguity-aware prompt | RQ1.1 |
| E3 Metadata on/off | Enrichment effect on linking + SQL | metadata {none, synonyms+terms}; linking variant | RQ1.2 |
| E4 Linking ablations | Retrieval vs generation decomposition | linking {heuristic, llm, metadata-aware}, top-k | RQ1.2 |
| E5 Validation + self-correction | Reliability under budget | correction rounds {0,1,2}, validators {syntax, exec, both} | RQ1.3 |
| E6 Answerability | Honest refusal | answerability {on, off}; labeled subset | RQ1.4 |

### 10.2 Ablation and sweep policy

- Each module toggled on/off with identical harness version and splits (docs/06 §8).
- Sweeps: temperature, `top_k`, few-shot count, correction rounds — each sweep point
  is its own run id.
- Determinism: seeds recorded; stochastic LLM runs repeated across seeds; report seed
  sensitivity (docs/07 §9).

### 10.3 Statistical plan

- Bootstrap 95% CI (>= 1000 resamples) for headline metrics.
- Paired comparisons: McNemar on per-task correctness for binary metrics.
- Significance level alpha = 0.05 fixed before running.

---

## 11. Baseline Approach (Point 8)

The baseline is the **least-common-denominator system** that isolates BEAVER's
difficulty and provides ablation controls:

1. **E1a — retrieval-free zero-shot:** full schema (adapter-supplied gold tables are
   not used in prediction; in `retrieval_free` mode the *public* schema for the task's
   database is given) + one generic prompt + `temperature=0.0` -> execute -> EX.
2. **E1b — retrieval zero-shot:** a simple lexical table retriever (token overlap /
   BM25 over table names + column names + descriptions) selects top-k tables; same
   generation prompt -> execute -> EX. Mirrors the BEAVER "retrieval" setting.
3. **E1c — few-shot:** E1b + 2–5 in-domain few-shot exemplars (from dev, never test).

The baseline has **no** ambiguity resolution, no metadata, no validation loop, and no
answerability judgment — so any gain from those modules is attributable. Published
BEAVER numbers are context only; all comparisons run in-repo on identical harness
versions (docs/06 §8).

---

## 12. Evaluation Metrics (Point 9)

### 12.1 Core metrics (dataset-independent, `evaluation/`)

| Metric | Definition | Reliability dimension |
|---|---|---|
| Execution Accuracy (EX) | Fraction whose predicted SQL executes to the same result as gold (order-insensitive row/col comparison) | Correctness |
| Valid-SQL Rate | Fraction executing successfully (valid syntax + semantics + no timeout) | Validity |
| Exact Match (EM) | Fraction of exact SQL-text matches (secondary) | Correctness |
| Efficiency (VES-style) | Valid + efficient executions (secondary) | Efficiency |
| Safety Blocking Rate | Fraction of destructive/unauthorized statements blocked | Safety |
| Refusal Correctness | Correct answerable/unanswerable classification on the labeled subset | Honesty |
| Robustness (research) | EX change under paraphrase/ambiguity perturbation of a dev sample | Robustness |

### 12.2 Adapter-provided metrics (BEAVER-specific, registered by the adapter)

- EX under `retrieval` and `retrieval_free` settings.
- Table-retrieval recall@k and "%Q with perfect recall@k".
- Subtask annotation scores: multi-table retrieval, join-key detection, column
  mapping, domain-knowledge extraction, query decomposition.
- Breakdowns by the three query categories.

### 12.3 Reporting

`EvaluationReportEnvelope` with `metric_results` + `summary`; per-instance detail for
error analysis; leak-check pass recorded (docs/07 §6); reliability dimensions reported
alongside the headline EX (docs/07 §5).

---

## 13. Research Contribution Opportunities (Point 10)

### 13.1 Ambiguity resolution (RQ1.1)

- Build an **ambiguity typology for enterprise NL2SQL** (term/scope/join/semantic
  ambiguity) on a **self-constructed, human-labeled subset** of enterprise-style
  questions. Per ADR-013, ambiguity is **not** a property of the Chen et al. BEAVER
  benchmark (which ships no imprecision/answerability labels); it is a contribution of
  our own experimental framework.
- Contribution: a detector + formalizer that turns underspecification into explicit
  assumptions; evaluation of the **cost of not resolving** (E2) and of the 
  assumption-accuracy of resolution (human-labeled subset); answerability judgment /
  honest refusal (E6, RQ1.4) on the same labeled subset.
- Expected publication angle: "quantifying and resolving enterprise ambiguity in
  text-to-SQL" — largely absent from the literature.

### 13.2 Enterprise metadata (RQ1.2)

- Treat metadata as **data**: `metadata/` consumes adapter sidecars (synonyms,
  business terms, units, hierarchies) and composes `EnrichedSchema` (ADR-001).
- Contribution: controlled study of enrichment effect on linking recall and EX (E3),
  plus a reusable `ColumnSemantics`/glossary pipeline; evidence for when metadata
  helps vs is noise.

#### M1.4 experiment design — metadata OFF/ON (implemented)

The controlled study is pre-wired as a two-arm comparison over the same dataset,
split, seed, LLM, and metric set — differing only in the schema served to the
prompt builder (ADR-015):

| Arm | Config | Schema provider | Prompt | Records |
|---|---|---|---|---|
| OFF (baseline) | `phase1_baseline.yaml` (`schema.enriched: false`) | base `SchemaProvider` | `baseline-v1` (byte-identical) | `meta.metadata_enriched=false`, provenance `baseline-v1` |
| ON (enriched) | `phase1_metadata.yaml` (`schema.enriched: true`) | `EnrichedSchemaProvider` (base + `EnrichmentData` sidecar) | `enriched-v1` | `meta.metadata_enriched=true`, provenance `enriched-v1` |

Controls: identical adapter/root (sidecar presence is *not* the factor — OFF
ignores an on-disk sidecar), identical split/seed/LLM/metrics, and
`enriched-v1` is a distinct versioned prompt so no other prompt drift is
possible (ADR-004). The analysis contrasts run-level metrics (exact match,
clean prediction rate, then BEAVER groups in M1.10) with a paired,
per-task design where the two arms share task ids — a natural McNemar/bootstrap
comparison (docs/07). This is the E3 contribution: **when metadata helps vs is
noise** for enterprise questions. The same sidecar feeds the metadata-aware
schema-linking variant in M1.6.

### 13.3 Schema linking (RQ1.2, benchmark-decomposed)

- Enterprise schemas are large (avg ~105 tables/db); table retrieval is the dominant
  BEAVER failure mode.
- Contribution: joint table + column + join-key linking with metadata awareness;
  **retrieval vs generation decomposition** that mirrors BEAVER's two settings and
  lets the project attribute errors precisely (E4); error-analysis infrastructure
  (subtask annotations).

### 13.4 SQL reliability (RQ1.3, RQ1.4)

- Validation + bounded self-correction tuned against `RuntimeContext` budgets
  (RQ1.3); study of valid-but-wrong SQL (validity vs correctness gap).
- Honest refusal / answerability judgment (RQ1.4) as a first-class pipeline output.
- Contribution: a **reliability-first evaluation methodology** (docs/07 §5) applied to
  an enterprise benchmark — validity, honesty, safety, efficiency reported beside
  accuracy; a defensible answerability benchmark slice **self-constructed on top of
  BEAVER-style enterprise schemas** (labeled subset; per ADR-013, the benchmark itself
  ships no answerability labels).

### 13.5 Cross-cutting

- Reproducible two-setting harness, typed contracts at every boundary, and a
  pre-registered ablation campaign — a reusable template for later phases.

---

## 14. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| BEAVER version/license ambiguity | Decision D1; pin version + license in manifest before experiments; correct docs/01, docs/05, configs |
| MySQL dialect / warehouse import complexity | Adapter-owned executor; read-only MySQL user; SQLite/DuckDB test executor for unit tests; schema-only mode for dry runs |
| Retrieval dominates accuracy (89% recall failures) | Two-setting design isolates generation from retrieval; explicit retrieval metrics |
| LLM cost / nondeterminism | Budget enforcement (ADR-003/008); caching; seed sensitivity reporting; local backend option |
| Dataset-format logic leaking into core | Conformance suite + dependency guard (ADR-006); ADR-004 prompt ownership |
| Two-BEAVER metrics confusion | ADR-013 pins the metric set; answerability kept as a research metric on a labeled subset |

---

## 15. Decision Register

| ADR | Status | Decision |
|---|---|---|
| ADR-013 | **Accepted** | Pin BEAVER (Chen et al., 2024/2025) as Phase 1 target; official metric set; ambiguity NOT a benchmark property; answerability as research metric on a self-labeled subset; doc/config corrections |
| ADR-014 | Proposed | New generic contracts: `LinkedSchema`, `AmbiguityAnalysis`, `ClarifiedQuestion`, `SqlValidationResult`, `AnswerabilityVerdict` in core contracts |
| ADR-015 | **Accepted** | Metadata enrichment (M1.4): `EnrichedSchema` extends `DatabaseSchema`; adapters publish an `EnrichmentData` sidecar via `metadata()`; `metadata/` owns the merge (`enrich_schema` + `EnrichedSchemaProvider`); `schema.enriched` toggles the OFF/ON provider swap with versioned `enriched-v1` prompts |
| ADR-016 | Proposed | Bounded self-correction loop governed by `RuntimeContext.budget` |
| ADR-017 | Proposed | Two evaluation settings (retrieval-free/retrieval) + reliability metric family |
| ADR-018 | Proposed | Read-only MySQL executor owned by the adapter; lightweight executors for tests |

---

## 16. Milestone Mapping and Exit Criteria

Design section -> docs/04 milestone:

| Design section | Milestone |
|---|---|
| 3 (adapter) | M1.1 BEAVER adapter + conformance |
| 3.7, 5.3–5.5, 7 (`core/pipeline`) | M1.2 baseline NL2SQL pipeline |
| 10, 12.3, `experiments/` driver | M1.3 baseline evaluation setup |
| 3.5, 6.2, 7 (metadata) | M1.4 metadata model + enrichment |
| 5.2, 6.2, 8, 13.1 | M1.5 ambiguity resolution |
| 4.2, 8, 13.3 | M1.6 schema linking |
| 5.4, 7, 8 | M1.7 SQL generation |
| 5.6, 8, 13.4 | M1.8 SQL validation |
| 7, 12.1 | M1.9 security layer |
| 10, 12 | M1.10 reliability evaluation campaign |
| 10.2 | M1.11 ablations + significance |
| 10, 12.3, 13 | M1.12 paper-ready results |

**Exit criteria:** reproducible BEAVER evaluation (retrieval + retrieval-free) with
CI, adapter conformance green, at least one module ablation with significant effect,
and a paper-ready results bundle under `results/`.

**Phase 0 dependency:** M0.4 (pipeline engine), M0.5 (LLM backends), M0.6 (evaluation
skeleton), M0.7 (conformance), and M0.8 (tracking) are complete (docs/04) and verified by
the hello-world end-to-end test and conformance suite.

---

## 17. References

- Chen et al. (2024). *BEAVER: An Enterprise Benchmark for Text-to-SQL.* arXiv:2409.02038.
- Project/leaderboard: beaverbench.github.io (05/2026 release: ~8,000 queries).
- Repo design context: docs/01, docs/02, docs/03, docs/04, docs/05, docs/06, docs/07;
  architecture/system_design.md; ADR-001, ADR-002, ADR-003, ADR-004, ADR-008,
  ADR-009, ADR-011, ADR-012.
