# `experiments/` — Experiments

The scientific log of this research program.

## Purpose

Record **what was tested, why, how, and what happened** for every experiment — in a form that is reproducible and citable.

## Layout

```
experiments/
├── _TEMPLATE_experiment_record.md   # required record format
├── phase1_nl2sql/                   # Phase 1 experiment records
│   ├── README.md
│   └── runs/                        # gitignored — run artifacts
└── phase2_nl2vis/                   # Phase 2 experiment records
    └── README.md
```

## Rules

| Content | Location | In git? |
|---|---|---|
| Experiment records (markdown) | `experiments/<phase>/` | ✔ committed |
| Templates | `_TEMPLATE_experiment_record.md` | ✔ committed |
| Run artifacts (predictions, logs, config dumps, metrics) | `experiments/*/runs/<run_id>/` | ✘ gitignored |

- One record per experiment, named `<phase>-<YYYYMMDD>-<seq>.md`.
- Records follow the [template](_TEMPLATE_experiment_record.md) exactly.
- Every record includes its reproducibility block (config hash, dataset manifest, commit SHA, seed).
- Compare experiments with identical evaluation harness version (see [`docs/07_Evaluation_Framework.md`](../docs/07_Evaluation_Framework.md)).

## Full methodology

See [`docs/06_Experiment_Strategy.md`](../docs/06_Experiment_Strategy.md).
