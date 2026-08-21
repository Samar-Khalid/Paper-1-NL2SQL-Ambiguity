# =============================================================================
# Enterprise AI Analyst Framework — development recipes
#
# The framework is currently in its FOUNDATION phase: these targets reference
# tooling that is scaffolded along with the first code module (Phase 0) and
# will be executable once `make setup` completes. They are kept here so the
# project contract (lint / format / typecheck / test / conformance / docs) is
# stable from day one.
#
# NOTE: these recipes assume a POSIX shell (Git Bash, WSL, or CI on Linux).
# On native Windows PowerShell, run the underlying commands directly, e.g.:
#   python -m pytest tests -m unit        (instead of make test-unit)
# =============================================================================

PYTHON     ?= python
PIP        ?= pip
UV         ?= uv
SRC        := src
TEST_DIRS  := tests

.PHONY: help setup lint format typecheck test test-unit test-integration \
        test-conformance coverage docs clean check

help:
	@echo "EAAF development recipes"
	@echo "  make setup              create venv + install package (editable) and dev deps"
	@echo "  make lint               run ruff linter"
	@echo "  make format             auto-format with ruff format"
	@echo "  make typecheck          run mypy (strict)"
	@echo "  make test               run the full test suite"
	@echo "  make test-unit          run only unit tests"
	@echo "  make test-integration   run only integration tests"
	@echo "  make test-conformance   run adapter conformance suites"
	@echo "  make coverage           run tests with coverage report"
	@echo "  make docs               build documentation site"
	@echo "  make check              lint + typecheck + test (CI entry point)"
	@echo "  make clean              remove caches and build artifacts"

setup:
	$(UV) venv
	$(UV) pip install -e ".[dev]"
	$(UV) run pre-commit install

lint:
	ruff check $(SRC) $(TEST_DIRS)

format:
	ruff format $(SRC) $(TEST_DIRS)
	ruff check --fix $(SRC) $(TEST_DIRS)

typecheck:
	mypy $(SRC)

test:
	pytest $(TEST_DIRS)

test-unit:
	pytest -m unit $(TEST_DIRS)

test-integration:
	pytest -m integration $(TEST_DIRS)

test-conformance:
	pytest -m conformance $(TEST_DIRS)

coverage:
	pytest --cov=$(SRC) --cov-report=term-missing $(TEST_DIRS)

docs:
	mkdocs build

check: lint typecheck test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
