# AGENTS.md — Rules for AI Assistants Working in This Repository

This file defines how AI coding assistants (e.g. opencode, Copilot, Cursor, Claude Code) must behave when contributing to this repository. It is a **machine-readable companion** to [docs/08_AI_Development_Guidelines.md](docs/08_AI_Development_Guidelines.md). If the two ever conflict, **this file wins for automated agents**; the docs file wins for human contributors.

Read these rules before any change. Read the core docs before touching architecture.

## 0. Context every agent must load first

Before making any change, an agent should consult at least:

- `README.md`
- `docs/03_System_Architecture.md` (and `architecture/system_design.md`)
- `docs/09_Coding_Standards.md`
- `AGENTS.md` (this file)

## 1. Allowed tasks

An AI assistant MAY:

- Write, edit, and refactor documentation, templates, and repository structure.
- Scaffold new modules following existing conventions.
- Implement features described in an issue/design doc, keeping the change scoped to that issue.
- Write or update tests (unit, integration, conformance, security, determinism).
- Add dataset adapters, LLM backends, executors, or metrics **through the plugin/adapter mechanism** — never by modifying core.
- Review code and propose changes via PRs or suggestions.
- Fix bugs, with a test that reproduces the bug.
- Run the configured tools (`make lint`, `make typecheck`, `make test`, `make test-conformance`).
- Create experiment records and paper notes using the provided templates.

## 2. Forbidden behaviors

An assistant MUST NOT:

- Add **dataset-specific logic to the core framework** (`src/eaa/core/`, `src/eaa/schema_linking/`, `src/eaa/llm/`, etc.). BEAVER/NVBench-specific names, fields, or splits belong only in `src/eaa/datasets/adapters/`.
- Add a dependency without an explicit reason and without recording it in `pyproject.toml` **and** the change description. No speculative dependencies.
- Fabricate, estimate, or invent **research results, metrics, citations, or numbers**. Report only what was actually measured. Mark anything estimated as *estimated*.
- Commit secrets, credentials, raw datasets, run artifacts, or model outputs.
- Commit directly to `main`, or push without a PR (when a remote exists).
- Make silent breaking changes to public interfaces or evaluation methodology. Breaking changes require documentation and a CHANGELOG entry.
- Rewrite or restructure code unrelated to the task at hand ("drive-by" refactors).
- Bypass the adapter/plugin boundary to "make it work" for one dataset.
- Generate code that disables or weakens the security model (read-only SQL execution, redaction, guardrails) without an explicit, documented decision.

## 3. Requirement: explain generated code

Any non-trivial generated code must be explained in the change description or PR:

- **What** the code does (one or two sentences).
- **Why** this approach was chosen over alternatives.
- **How** it was verified (commands run, tests passed).
- **Research implications** if any (e.g., this affects reproducibility, metrics, or eval).

Trivial glue code (renames, formatting) needs no explanation, but the change summary must still state intent.

## 4. Requirement: document decisions

Any decision that could affect the architecture, evaluation, or research direction must be recorded before or with the change:

- Architecture decisions → ADR in `architecture/adrs/` (index:
  `architecture/adrs/README.md`), summarized in `architecture/system_design.md`
  and `docs/03_System_Architecture.md`.
- Evaluation/methodology decisions → `docs/07_Evaluation_Framework.md`.
- Dataset decisions → `docs/05_Dataset_Strategy.md`.
- Use the issue/PR description if a fuller doc is not yet warranted.

## 5. Operating rules

- **Prefer editing existing files** to creating new ones. Never create documentation purely "because it is nice to have"; only when it serves the project (templates, docs, tests).
- **Match existing conventions**: module layout, config style, naming, docstring style (numpy), typing.
- **Do not add comments unless they carry real information**; prefer expressive code and docstrings.
- **Run verification before declaring done**: `make check` (or the subset that applies) must pass.
- **Never commit unless explicitly asked.**
- If a task is ambiguous, ask the user rather than guessing at scope.
- Keep changes small and reviewable; one logical unit per commit.

## 6. Verification checklist for every change

Before finishing:

1. `make lint` clean.
2. `make typecheck` clean (when typing is enabled).
3. Relevant tests pass (`make test`, plus `make test-conformance` for adapters).
4. No dataset-specific logic leaked into core (grep for `beaver`/`nvbench` outside adapters is a good smell test). Contracts: core code switches on `type_key`, never on concrete payload classes (ADR-001).
5. `CHANGELOG.md` updated for user-facing changes.
6. Decision documentation updated if the change has research implications.
