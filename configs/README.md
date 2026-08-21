# `configs/` — Configuration Templates

## Purpose

Version-controlled YAML templates for datasets, models, experiments, and global defaults. **Templates, not secrets.**

## Layout

```
configs/
├── default.yaml                      # global defaults (logging, security, eval)
├── datasets/                         # one file per dataset adapter
│   ├── beaver.yaml
│   └── nvbench.yaml
├── experiments/                      # one file per evaluation campaign
│   ├── phase1_beaver_eval.yaml
│   ├── phase1_baseline.yaml          # M1.3 reproducible baseline run (metadata OFF)
│   ├── phase1_metadata.yaml          # M1.4 metadata-ON arm (schema.enriched: true)
│   └── phase2_nvbench_eval.yaml
└── models/                           # (Phase 0+) one file per LLM setup
```

## Rules

- Every config file is validated against the typed models in `src/eaa/core/configuration/`.
- Layer order: `default.yaml` → `datasets/<d>.yaml` → `experiments/<e>.yaml` → CLI overrides → env vars.
- **No secrets** in these files — use env vars / secret store (see `src/eaa/security/`).
- The fully resolved config is dumped with every run (`config.resolved.yaml`) and is the only truth (see [`docs/06_Experiment_Strategy.md`](../docs/06_Experiment_Strategy.md)).
