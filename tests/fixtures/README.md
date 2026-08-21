# `tests/fixtures/` — Test Fixtures

Tiny, deterministic data used by tests:

- Minimal relational schemas (JSON/YAML descriptions).
- Sample SQLite/CSV datasets (kept small; committed).
- Sample predictions + gold references for metric unit tests.

Conventions: no real/private data; no large files (see `.gitignore` + pre-commit size check). Files under `tests/fixtures/` are the *only* committed data in this repo.
