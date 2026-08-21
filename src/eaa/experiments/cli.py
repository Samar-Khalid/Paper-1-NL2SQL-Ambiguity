"""Command-line entry point for baseline evaluation runs.

Usage::

    eaa-run-baseline --config configs/experiments/phase1_baseline.yaml \
        [--split dev] [--limit 10] [--artifact-root experiments/runs] \
        [--run-id ab12cd34-...-baseline] \
        [--override llm.provider=openai] [--override llm.model=gpt-4o]

The fully resolved config is snapshotted into every run
(``config.resolved.json``); overrides are applied before env vars, matching
``resolve_config`` semantics.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .baseline import build_baseline_experiment
from .errors import ExperimentError


def main(argv: Sequence[str] | None = None) -> int:
    """Run a baseline evaluation; return the process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        experiment = build_baseline_experiment(
            args.config,
            config_root=args.config_root,
            overrides=_parse_overrides(args.override),
            artifact_root=args.artifact_root,
            run_id=args.run_id,
        )
        summary = experiment.run(split=args.split, limit=args.limit)
    except (ExperimentError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"run_id:    {summary.run_id}")
    print(f"dataset:   {summary.dataset_id}")
    print(f"split:     {summary.split}")
    print(f"tasks:     {summary.num_tasks}  (predictions: {summary.num_predictions}, "
          f"failed: {summary.num_failed})")
    print(f"run_dir:   {summary.run_dir}")
    for name in sorted(summary.metrics):
        print(f"metric {name:<22} {summary.metrics[name]:.6f}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eaa-run-baseline",
        description="Run a reproducible baseline NL2SQL evaluation.",
    )
    parser.add_argument(
        "--config",
        default=str(Path("configs/experiments/phase1_baseline.yaml")),
        help="experiment config file (defaults chain resolved first)",
    )
    parser.add_argument("--config-root", default=None, help="base dir for defaults entries")
    parser.add_argument("--split", default=None, help="dataset split (dev/test)")
    parser.add_argument("--limit", type=int, default=None, help="cap on tasks (dry runs)")
    parser.add_argument("--artifact-root", default=None, help="artifact root override")
    parser.add_argument("--run-id", default=None, help="run id (RunId format)")
    parser.add_argument(
        "--override",
        action="append",
        default=[],
        help="dotted-key override, e.g. llm.provider=openai (repeatable)",
    )
    return parser


def _parse_overrides(raw: list[str]) -> dict[str, Any]:
    """Parse ``key=value`` CLI overrides into a dotted-key dict."""
    overrides: dict[str, Any] = {}
    for item in raw:
        if "=" not in item:
            raise ExperimentError(f"invalid override (expected key=value): {item!r}")
        key, value = item.split("=", 1)
        overrides[key] = _coerce(value.strip())
    return overrides


def _coerce(value: str) -> Any:
    """Coerce an override string to a primitive (matches env coercion rules)."""
    lowered = value.lower()
    if lowered in ("true", "yes", "1", "on"):
        return True
    if lowered in ("false", "no", "0", "off"):
        return False
    if lowered in ("null", "none", ""):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


__all__ = ["main"]
