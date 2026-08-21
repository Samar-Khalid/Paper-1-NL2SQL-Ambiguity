# Paper 1 — Human Gold Annotation Workflow (Surface B, single annotator)

> **STATUS: tooling ready, task list written, NO labels yet.**
> This document defines how the researcher produces the genuine **Human Gold**
> reference set for the 45 usable Surface B questions — fully separated from the
> frozen AI pilot (`batch-1` / `surface_b.v1.lock`, docs/19). The human gold is a
> **single-annotator** set: no second annotator, no adjudication, and no
> fabricated enrichment. The workflow stops at the task list until the researcher
> labels the questions by hand in the local browser UI.

## 1. Purpose

The frozen AI pilot (docs/19, docs/20) supplies AI-produced labels for Surface B.
Those labels are *AI gold / internal consistency only* — they cannot validate the
pipeline. The Human Gold set is the independent, human-authored reference the
detector evaluation (docs/13, docs/15) will be measured against.

Scope is the recomputed usable set, derived from the frozen label files (never
hardcoded):

| Stratum | Count |
|---|---|
| usable — persistent ambiguity | 30 |
| usable — unambiguous | 15 |
| **usable total** | **45** |
| excluded — metadata-deferred | 15 |
| excluded — unanswerable | 0 |

The 15 deferred ids are `dw_1013, dw_1017, dw_1019, dw_1020, dw_1021, dw_1023,
dw_1024, dw_1026, dw_1027, dw_1028, dw_1029, dw_1032, dw_1034, dw_1035,
dw_1036`. These were deferred in the frozen pilot because no legitimate
enrichment source exists (docs/19 §11); they are **refusable** by the human and
stay out of the gold set. Measured on the real batch: `--mode list` reports
`45 (persistent_ambiguity=30, unambiguous=15); excluded metadata_deferred=15,
excluded unanswerable=0`.

## 2. Hard separation from the AI pilot

- The AI pilot lives at `data/annotations/surface_b/batch-1/` and is frozen by
  `data/annotations/surface_b/surface_b.v1.lock` (sha256 `e215880a...`). It is
  **never written to** by the Human Gold workflow.
- The Human Gold set lives in its own tree,
  `data/annotations/surface_b/human-gold/`, and freezes to its own
  `human-gold.v1.lock`.
- `--mode status` recomputes the AI-pilot lock digest from the exact file list
  recorded in `surface_b.v1.lock` (never the lock file itself) and refuses to
  proceed on any mismatch.
- The freeze of Human Gold hashes **only** the derived annotation files plus
  `provenance-v1.json` under `human-gold/`. A freeze that would leak any
  gold-field key is refused.
- The annotation UI payload is gold-free: it carries only `question_id`,
  `database_id`, `question`, and the screening `signals`, and it strips the
  operational `frozen_stratum` so the researcher is not anchored to the pilot's
  stratum judgment.

## 3. Rules the annotator follows

1. Do not read the frozen AI labels, the batch-1 tree, or `surface_b.v1.lock`.
2. Do not read any gold field (the UI cannot show one; the API and freeze both
   guard against leaks).
3. For every task decide:
   - answerability (`answerable` / `unanswerable`);
   - each strict-ambiguity span: code (`S1`…`S3`, `C1`…`C3`), phrase (an exact
     question substring), assumption risk, resolution channel, clarification
     required, metadata resolution;
   - the two SQL readings `sql_reading_A` / `sql_reading_B` for strict spans.
4. A metadata-grounded label (`resolution_channel=metadata`,
   `metadata_resolution=True`) is **refused** by the validator unless a
   legitimate enrichment snapshot exists — none exists in this repo, so such
   labels cannot be saved (docs/19 §8, docs/23 §5).
5. Unanswerable records must carry no spans and no interpretations.

## 4. Provenance — honest single-annotator sidecar

`provenance-v1.json` records, per question, that the set is `human_gold`, the
annotator is the researcher, and:

> single human annotator (the researcher); a second independent annotator was
> not available, so inter-annotator agreement is not applicable

IAA is recorded as `available: false` in every entry. No κ, no second annotator,
and no adjudication are ever fabricated. The freeze refuses to run for any
annotator id that does not match the sidecar.

## 5. Workflow

```
# 1. write the task list artifact (already done for the real batch)
python -m eaa.experiments.surface_b_human_annotation --mode list

# 2. launch the local annotation UI and label by hand in the browser
python -m eaa.experiments.surface_b_human_annotation --mode launch --annotator <researcher-id>
#   open http://127.0.0.1:8765 , annotate all 45 tasks, then Ctrl+C

# 3. validate the workspace against the task list
python -m eaa.experiments.surface_b_human_annotation --mode validate --annotator <researcher-id>

# 4. freeze the Human Gold set to its own lock
python -m eaa.experiments.surface_b_human_annotation --mode freeze --annotator <researcher-id>

# 5. status / integrity check at any point
python -m eaa.experiments.surface_b_human_annotation --mode status
```

All modes accept `--config`, `--candidates`, `--batch-root`, `--human-root`,
`--data-root`, `--annotator`, `--lock`, `--ai-lock`, and `launch` additionally
accepts `--host`/`--port` (default `127.0.0.1:8765`).

## 6. Artifact layout

```
data/annotations/surface_b/human-gold/
├── tasks.json            # task list (45 tasks, excluded list, totals)  — written
├── meta/                 # researcher's raw decisions (source of truth) — NOT yet created
├── annotations/          # derived annotation records (from meta/)      — NOT yet created
├── provenance-v1.json    # single-annotator sidecar                     — written at launch
└── human-gold.v1.lock    # freeze lock (separate from the AI pilot)     — written at freeze
```

The `meta/` decisions are the source of truth; `annotations/` is re-derived from
them (the UI's "regenerate" route and `regenerate_human_records`).

## 7. Current status

- `--mode list` ran: `tasks.json` written, 45 usable (30 persistent + 15
  unambiguous), 15 metadata-deferred excluded, 0 unanswerable.
- `--mode status`: AI-pilot lock `OK (sha256=e215880a...)`; annotated `0/45`.
- Frozen pilot untouched (60 labels, 63 files, `surface_b.v1.lock` mtime
  unchanged).
- **The workflow deliberately stops here. No labels have been generated.** The
  next step is a human, in the browser, via `--mode launch`.
