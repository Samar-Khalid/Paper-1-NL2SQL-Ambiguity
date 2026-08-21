# Paper 1 — Live Ambiguity-Analysis Demo (`eaa-ambiguity-demo`)

> **STATUS: research tooling only — NOT a benchmark.**
> This demo is the interactive front-end of the completed/frozen Paper 1 work
> (docs/20). It runs the frozen detectors over an arbitrary question + schema
> and prints a human-readable `AmbiguityAnalysis`. It produces **no research
> evidence**: it reads no gold, writes no labels, touches no frozen artifact,
> and fabricates no enrichment or annotation. See the DISCLAIMER section below.

## 1. What it does

You type an enterprise question against one of the BEAVER warehouses and the
demo answers: *is the question ambiguous? where? which taxonomy family? does it
need clarification?*. Concretely it composes the existing frozen machinery:

- the deterministic baseline — `SignalAnnotator` (Annotator A) over the
  gold-free candidate signals (`candidates.signals.evaluate_question`), which
  emits a strict span per fired reasoning-grounded signal whose evidence phrase
  occurs in the question;
- optionally, the `ReasoningBasedDetector` (persistent-ambiguity judgment) when
  a real LLM backend is configured;
- the fired *screening signals* are shown separately and are labelled **hints,
  not labels** (docs/19): the pool screens suspicious questions only.

The demo never executes SQL, never calls NL2SQL, and never resolves a question
(the resolver is a later M1.5 slice).

## 2. Interface

The clean, thesis-facing API is in `src/eaa/ambiguity_resolution/demo.py`:

```python
from eaa.ambiguity_resolution.demo import analyze_question
from eaa.ambiguity_resolution.demo import analyze_demo, render_analysis

# Pipeline-facing: deterministic baseline only, returns the standard contract.
analysis: AmbiguityAnalysis = analyze_question(question, database_schema, optional_metadata)

# UI-facing: rich human-readable view (baseline + optional reasoning leg).
demo = analyze_demo(question, database_schema, optional_metadata, mode="baseline")
print(render_analysis(demo))
```

- `analyze_question(question, database_schema, optional_metadata) ->
  AmbiguityAnalysis` — always runs the deterministic baseline; spans carry no
  confidence claim (`0.0`). This is the function a future thesis pipeline stage
  consumes (detection → resolver → NL2SQL).
- `analyze_demo(...)` — the report generator used by the CLI. It adds family
  names, per-span metadata/clarification/channel status, detector source, LLM
  and metadata status, warnings, and a heuristic display confidence (clearly
  labelled, never calibrated).
- `optional_metadata` is accepted for interface compatibility but is **not used**
  by the deterministic baseline (metadata-grounded detection is deferred,
  ADR-015, matching the frozen batch). Passing a content-bearing
  `EnrichedSchema` updates the reported metadata status only.

## 3. Launch

From the repository root:

```
# interactive REPL (database dw, deterministic baseline)
eaa-ambiguity-demo

# pick a warehouse / one-shot question
eaa-ambiguity-demo --database neutron
eaa-ambiguity-demo --question "Show the subject code where the department is Mathematics."
eaa-ambiguity-demo --database dw --mode combined --question "List all departments that have no students enrolled this year."

# curated tour over real, gold-free BEAVER dev questions (docs/22 §6)
eaa-ambiguity-demo --examples

# list the available warehouses
eaa-ambiguity-demo --list-databases
```

Equivalent module invocation: `python -m eaa.experiments.ambiguity_demo ...`.

Options: `--config` (default `configs/experiments/phase1_beaver_eval.yaml`),
`--database` (default `dw`), `--mode {baseline,reasoning,combined}`,
`--question`, `--examples`, `--list-databases`, `--candidates` (default
`data/annotations/surface_b/candidates.json`), `--session-id`.

The schemas come from the BEAVER adapter (entry-point `eaa.datasets`) against
the raw data root (`dataset.data_root` or `EAA_BEAVER_DATA_ROOT`); a missing
raw root raises setup guidance rather than failing silently.

## 4. Modes and the LLM/metadata status lines

- **`baseline`** (default) — deterministic only. Always works, always
  reproducible.
- **`reasoning`** — runs `ReasoningBasedDetector` via a real backend. Without
  one the demo **reports the leg as unavailable and falls back to the baseline
  with an explicit warning** — it never silently fakes a model judgment, and
  `EchoBackend` is test-only and never used for demo results.
- **`combined`** — baseline + reasoning (when available), unioned by
  `(code, start, end)`; overlapping spans with different codes across detectors
  are reported as conflicts, never silently resolved.
- The **metadata** leg is N/A in every current mode: no legitimate enrichment
  exists (ADR-015), so no metadata-grounded prediction is manufactured. The
  status line states this explicitly.
- Every displayed confidence for baseline spans is the labelled heuristic
  constant (`BASELINE_DISPLAY_CONFIDENCE`); the deterministic baseline is not
  confidence-bearing (docs/15 §4.4 N/A).

### Environment for the reasoning leg

The reasoning leg needs, in `configs/datasets/*` or an experiment config:

```
llm.provider: openai | openai-compatible | vllm | ollama
llm.model: <model id>
llm.api_key_env: OPENAI_API_KEY        # or another credential env var
```

and that environment variable set in the shell. Missing pieces yield the
"unavailable" status line, never a fake result.

## 5. What the report shows

Sections: question/database/mode/detector, **overall verdict** (ambiguous /
not ambiguous), **detected ambiguity spans** (code, family + family name,
character offsets, snippet, confidence, metadata-resolution status,
clarification-required, assumption risk, resolution channel, detector source,
explanation), **screening signals (hints, not labels)**, **status**
(reasoning/LLM, metadata, clarification), **possible interpretations** (none
produced by the deterministic baseline — interpretations require a reasoning
judgment or a human annotator), **recommendation** (thesis integration point),
**warnings**, and the **disclaimer**. The report is ASCII-only so it renders
cleanly on Windows consoles.

## 6. Curated examples (`--examples`)

The tour runs real, gold-free BEAVER dev questions selected from
`data/annotations/surface_b/candidates.json` by signal target:

1. scope/constraint (quantifier scope, S1),
2. table-selection risk (R1 screening hint),
3. join path (R2),
4. aggregation/metric (C1),
5. relative temporal (T1),
6. entity/value (V1 screening hint),
7. a **control** question (`Show the department names.`) demonstrating the
   unambiguous path.

Important documented finding: **every** dev question in the candidate pool fires
at least one reasoning-grounded screening signal, so the deterministic baseline
reports ambiguity on every candidate (the pool is a screening surface of
*suspicious* questions, docs/19). The control question exists precisely so the
tool's unambiguous path is demonstrable without mislabelling a benchmark
question. This is consistent with the frozen docs/20 status (baseline existence
F1 0.4952, `AI_GOLD_PILOT`).

## 7. Verification

- 17 new unit tests (`tests/unit/ambiguity_resolution/test_demo.py`): contract
  validity, determinism, span offsets, unavailable-leg reporting, backend merge
  and conflict paths, input validation, ASCII-only rendering, example curation,
  and a structural guard that `demo.py` never references gold fields.
- Full suite: `pytest tests -q` (592 + 17 = **609 passed**).
- `ruff`, `mypy` (strict), and `compileall` clean.
- Frozen artifacts untouched: `data/annotations/surface_b/surface_b.v1.lock`
  sha256 `e215880a439656dfce29d0d9e4f466193fb78f60bf3b894aef9734bc0d469db7`
  unchanged; no gold field is read anywhere in the demo path.

## 8. Disclaimer

Research demonstration only — not a benchmark evaluation. Demo output is
computed by the frozen Paper 1 detectors; it is not research evidence, contains
no gold, and neither enrichment nor human annotation is fabricated.
