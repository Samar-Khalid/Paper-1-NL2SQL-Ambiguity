# Contributing to the Enterprise AI Analyst Framework

Thank you for considering contributing. This is a research repository: we value **scientific rigor, reproducibility, and clarity** as much as code.

Please read [docs/09_Coding_Standards.md](docs/09_Coding_Standards.md) and [docs/08_AI_Development_Guidelines.md](docs/08_AI_Development_Guidelines.md) before making changes.

## Code of Conduct

Be respectful and constructive. Harassment and demeaning behavior are not tolerated. (A formal CODE_OF_CONDUCT will be added before the first public release — see [docs/10_Open_Source_Strategy.md](docs/10_Open_Source_Strategy.md).)

## Ways to contribute

1. **Open an issue** — bug reports, benchmark/data questions, research discussions.
2. **Join a discussion** — architecture decisions, evaluation methodology, dataset strategy.
3. **Propose a design** — an issue or discussion first, then a design doc, then a PR.
4. **Submit a pull request** — code, tests, docs, conformance suites, dataset adapters.

## Workflow

### 1. Create an issue first (for non-trivial changes)

Non-trivial work must start with an issue so the design is agreed before code is written. Label your issue:

- `bug`, `enhancement`, `documentation`, `research`, `dataset`, `evaluation`, `architecture`, `ai-assisted`

### 2. Branch naming

```
feat/phase1-schema-linker          # new feature
fix/executor-timeout-handling      # bug fix
docs/06-experiment-conventions     # documentation
bench/beaver-ambiguity-suite       # benchmark/evaluation work
refactor/interfaces-schema         # refactor
```

Branches are short-lived. One branch = one coherent unit of work = one PR.

### 3. Commit conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body — explain the WHY, especially for research choices]
[optional footer: Ref #<issue>, BREAKING CHANGE, Signed-off-by ...]
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `bench`, `chore`, `style`, `perf`, `build`, `ci`, `revert`.

Examples:

```
feat(core): add typed pipeline stage ports
docs(eval): define metric registry contract (Ref #12)
bench(beaver): add ambiguity split generator
```

Rules:

- **Never commit run artifacts** (`experiments/**/runs/`, `results/artifacts/`, `*.jsonl`, model outputs).
- **Never commit secrets or raw data.**
- Write the commit message for a future researcher who knows nothing about the change.

### 4. Pull requests

- One PR references one issue (or explicitly says none exists).
- The PR description must include: **motivation**, **approach**, **verification**, and **research/design implications** (why this choice).
- All CI checks must pass: lint, typecheck, unit tests, and (where applicable) conformance.
- For any change touching core interfaces or evaluation: link the relevant docs sections and note any **backward-compatibility impact**.
- Code review checklist (from [docs/09_Coding_Standards.md](docs/09_Coding_Standards.md)):
  - [ ] Dataset-specific logic is *not* in the core (adapter boundary respected).
  - [ ] Public interfaces are typed and documented.
  - [ ] Tests added/updated for the change.
  - [ ] Config changes validated and documented.
  - [ ] Decisions recorded (ADRs / docs/08) where appropriate.
  - [ ] Generated code explained (see AGENTS.md / docs/08).

## Git workflow

### Branches and integration

```
main  (protected — always green, tagged releases)
 └── feat/*  fix/*  docs/*  bench/*  ...   (short-lived)
      └── merged via PR (squash merge, linear history)
```

- `main` is protected: no direct pushes; PRs only.
- Experimental research is done on branches; anything uncertain about a *design direction* should stay on a branch and be discussed, not merged speculatively.
- Releases are tagged on `main` with `vMAJOR.MINOR.PATCH` (see below).

### Versioning

[Semantic Versioning](https://semver.org/), relaxed for pre-1.0 research software:

| Version part | When it increments |
|---|---|
| `MAJOR` | Breaking change to public interfaces / contracts, or a new research phase |
| `MINOR` | New feature, new module, new dataset adapter, backward-compatible additions |
| `PATCH` | Bug fixes, documentation, refactors without behavior change |

Pre-1.0 convention: `0.x.y` — `MINOR` increments for new features (0.2.0, 0.3.0 …), `PATCH` for fixes (0.1.1). Breaking changes in `0.x` bump `MINOR` and are documented in `CHANGELOG.md`.

### Experiment tracking and git

- **Commit experiment *records*** (the markdown/YAML summaries) in `experiments/` — these are part of the scientific record and version-controlled.
- **Do NOT commit experiment *artifacts*** (runs/, predictions, model weights, heavy logs) — they are gitignored and live in the artifact store.
- Each experiment record must reference the exact **commit SHA** (or config hash) it ran on, so results can be traced to code.
- Results tables in `results/` are committed as *summaries* with a pointer to the run artifacts.

## Testing requirements

- Every change must keep the test suite green: `make check`.
- Adapter changes must pass the **conformance suites** (`make test-conformance`) — these enforce that adapters honor the core interfaces.
- New evaluation metrics require unit tests with synthetic predictions and gold references.

## Reviewing

- Reviews focus on: correctness, **dataset-independence**, interface stability, reproducibility, and documentation.
- Any reviewer may request an explicit explanation of *why* a design choice was made — research frameworks outlive their authors.

## Good first issues

Look for issues labeled `good-first-issue`. Documentation, templates, and conformance tests are great starting points.
