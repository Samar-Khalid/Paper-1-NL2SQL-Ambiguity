"""Candidate pool generation driver for the Surface B screening surface.

M1.5 — composes an existing dataset adapter, the dataset-independent candidate
signals (``eaa.ambiguity_resolution.candidates``), and the deterministic JSON
writer into a repeatable generator for the human screening pool::

    python -m eaa.experiments.surface_b_candidates [--config CONFIG]
        [--split dev] [--out data/annotations/surface_b/candidates.json]

The pool is gold-free by construction (ADR-009): candidate records carry only
the task question, database id, and signal evidence; they never reference SQL,
gold tables, join keys, column mappings, or any other label. The driver is
dataset-independent: the adapter is resolved by name from the ``eaa.datasets``
entry-point group (ADR-002), exactly like the baseline driver, so no dataset
name or logic appears here.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from eaa.ambiguity_resolution.candidates import (
    build_candidate_pool,
    write_candidates,
)
from eaa.core.configuration import resolve_config
from eaa.core.interfaces.dataset import BenchmarkAdapter

from .baseline import _collect_tasks, _load_adapter, _schema_provider_of
from .errors import ExperimentError

DEFAULT_OUT = Path("data/annotations/surface_b/candidates.json")


def build_candidate_artifact(
    adapter: BenchmarkAdapter,
    *,
    split: str | None = "dev",
    out_path: str | Path = DEFAULT_OUT,
    source: dict[str, Any] | None = None,
) -> Path:
    """Score one adapter split and write the candidate pool artifact.

    Parameters
    ----------
    adapter:
        A ``BenchmarkAdapter`` exposing ``manifest()``, ``schema_provider()``
        and an async ``task_stream(split)``.
    split:
        Split to screen (defaults to ``"dev"``).
    out_path:
        Target artifact path (defaults to ``DEFAULT_OUT``).
    source:
        Provenance metadata embedded in the artifact; defaults to the adapter
        ``DatasetManifest.extra`` (data root, checksum, databases, stats).

    Returns
    -------
    Path:
        The written artifact path.

    Raises
    ------
    ExperimentError:
        If the adapter exposes no ``schema_provider()`` or ``manifest()``.
    """
    manifest = adapter.manifest()
    provider = _schema_provider_of(adapter)
    tasks = asyncio.run(_collect_tasks(adapter, split))
    schemas: dict[str, Any] = {
        db_id: provider.get_schema(db_id) for db_id in manifest.extra.get("databases", [])
    }
    pool = build_candidate_pool(
        tasks,
        schemas,
        source=source if source is not None else manifest.extra,
    )
    return write_candidates(pool, Path(out_path))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m eaa.experiments.surface_b_candidates",
        description="Generate the gold-free Surface B candidate pool artifact.",
    )
    parser.add_argument(
        "--config",
        default=str(Path("configs/experiments/phase1_baseline.yaml")),
        help="experiment config (adapter is resolved by dataset.name)",
    )
    parser.add_argument("--config-root", default=None, help="base dir for defaults entries")
    parser.add_argument(
        "--split", default="dev", help="dataset split to screen (default: dev)"
    )
    parser.add_argument(
        "--out", default=str(DEFAULT_OUT), help="candidate artifact output path"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Generate the candidate pool artifact; return the process exit code."""
    args = _build_parser().parse_args(argv)
    try:
        config = resolve_config(args.config, config_root=args.config_root, overrides={})
        adapter = _load_adapter(config)
        out = build_candidate_artifact(adapter, split=args.split, out_path=args.out)
    except (ExperimentError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"candidate pool written to {out}")
    return 0


__all__ = ["DEFAULT_OUT", "build_candidate_artifact", "main"]
