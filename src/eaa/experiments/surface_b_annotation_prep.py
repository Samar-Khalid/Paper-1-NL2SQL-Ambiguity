"""Surface B annotation-preparation driver (M1.5, docs/19).

Composes the gold-free candidate pool, the batch design constants, the
annotator workspace, the provenance skeleton, and the QC/freeze tooling into a
repeatable CLI for the human annotation workflow::

    # 1. deterministic gold-free screening manifest (default mode)
    python -m eaa.experiments.surface_b_annotation_prep --mode manifest

    # 2. annotator workspace once a human selection file exists
    python -m eaa.experiments.surface_b_annotation_prep --mode workspace --selection SELECTION.json

    # 3. third-label 10% sample (requires the pre-registered seed)
    python -m eaa.experiments.surface_b_annotation_prep --mode sample \
        --selection SELECTION.json --seed SEED

    # 4. validate a labeled batch without freezing
    python -m eaa.experiments.surface_b_annotation_prep --mode validate --out BATCH_ROOT

    # 5. freeze a complete, adjudicated batch (hash + lock)
    python -m eaa.experiments.surface_b_annotation_prep --mode freeze \
        --out BATCH_ROOT --data-root data/raw/beaver

The driver never fabricates selection, labels, provenance, or enrichment; a
missing frozen seed or a missing legitimate enrichment snapshot blocks the
corresponding step with a clear error (docs/19 §8, §11).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from eaa.ambiguity_resolution.annotations import (
    AnnotationPrepError,
    build_annotation_workspace,
    build_screening_manifest,
    freeze_batch,
    select_third_label_sample,
    write_lock,
)
from eaa.ambiguity_resolution.candidates import load_candidates
from eaa.core.interfaces.dataset import BenchmarkAdapter

from .baseline import _load_adapter, _schema_provider_of
from .errors import ExperimentError

DEFAULT_CANDIDATES = Path("data/annotations/surface_b/candidates.json")
DEFAULT_BATCH_ROOT = Path("data/annotations/surface_b/batch-1")
DEFAULT_SCREENING = DEFAULT_BATCH_ROOT / "screening-manifest.json"
DEFAULT_CONFIG = Path("configs/experiments/phase1_baseline.yaml")
DEFAULT_LOCK = Path("data/annotations/surface_b/surface_b.v1.lock")


def _resolve_adapter(
    config_path: str, config_root: str | None
) -> tuple[BenchmarkAdapter, dict[str, Any]]:
    """Resolve the dataset adapter and per-database schemas from the config."""
    from eaa.core.configuration import resolve_config

    config = resolve_config(config_path, config_root=config_root, overrides={})
    adapter = _load_adapter(config)
    provider = _schema_provider_of(adapter)
    databases = adapter.manifest().extra.get("databases", [])
    schemas: dict[str, Any] = {
        db_id: provider.get_schema(db_id) for db_id in databases
    }
    return adapter, schemas


def _read_selection(path: str | Path) -> list[str]:
    """Read a selection file: a JSON list of ids or a completed manifest."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [str(item) for item in payload]
    if isinstance(payload, dict):
        candidates = payload.get("candidates")
        if isinstance(candidates, list):
            return [
                str(entry["question_id"])
                for entry in candidates
                if isinstance(entry, dict)
                and entry.get("selection_status") == "selected"
            ]
    raise AnnotationPrepError(
        f"{path} is not a selection list or a completed screening manifest"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m eaa.experiments.surface_b_annotation_prep",
        description="Generate the Surface B screening manifest, annotator "
        "workspace, and QC/freeze tooling (docs/19).",
    )
    parser.add_argument(
        "--mode",
        choices=["manifest", "workspace", "sample", "validate", "freeze"],
        default="manifest",
        help="preparation step to run (default: manifest)",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="experiment config (adapter is resolved by dataset.name)",
    )
    parser.add_argument("--config-root", default=None, help="base dir for defaults entries")
    parser.add_argument(
        "--candidates",
        default=str(DEFAULT_CANDIDATES),
        help="candidate pool artifact path",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_BATCH_ROOT),
        help="manifest/workspace/batch output path (per mode)",
    )
    parser.add_argument(
        "--selection",
        default=None,
        help="selection file: JSON list of question ids or a completed manifest",
    )
    parser.add_argument(
        "--seed",
        default=None,
        help="pre-registered seed for the third-label 10% sample (required)",
    )
    parser.add_argument(
        "--data-root",
        default=None,
        help="raw BEAVER data root used to verify the enrichment snapshot",
    )
    parser.add_argument(
        "--annotators",
        default="annotator-a,annotator-b",
        help="comma-separated annotator workspace names",
    )
    parser.add_argument(
        "--lock",
        default=str(DEFAULT_LOCK),
        help="freeze lock output path",
    )
    return parser


def _run_manifest(args: argparse.Namespace) -> int:
    pool = load_candidates(Path(args.candidates))
    try:
        _, schemas = _resolve_adapter(args.config, args.config_root)
    except ExperimentError as exc:
        print(f"warning: cannot resolve adapter schemas: {exc}", file=sys.stderr)
        schemas = {}
    manifest = build_screening_manifest(pool, schemas)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(
        f"screening manifest written to {out} "
        f"({manifest['pool']['total']} candidates; selection left to humans)"
    )
    return 0


def _run_workspace(args: argparse.Namespace) -> int:
    if not args.selection:
        print("error: --selection is required for --mode workspace", file=sys.stderr)
        return 1
    pool = load_candidates(Path(args.candidates))
    _, schemas = _resolve_adapter(args.config, args.config_root)
    selection = _read_selection(args.selection)
    root = build_annotation_workspace(
        pool,
        schemas,
        selection,
        out_root=Path(args.out),
        annotators=[name.strip() for name in args.annotators.split(",") if name.strip()],
    )
    print(f"annotation workspace written to {root} ({len(selection)} questions)")
    return 0


def _run_sample(args: argparse.Namespace) -> int:
    if not args.selection:
        print("error: --selection is required for --mode sample", file=sys.stderr)
        return 1
    if not args.seed:
        print(
            "error: the 10% third-label sample has no pre-registered seed "
            "(docs/13 §7 fixes only the fraction); a seed must be fixed by the "
            "researcher before this step can run",
            file=sys.stderr,
        )
        return 1
    selection = _read_selection(args.selection)
    try:
        seed: int | str = (
            int(args.seed) if args.seed.isdigit() else args.seed
        )
    except ValueError:
        seed = args.seed
    sample = select_third_label_sample(selection, seed=seed)
    print(
        f"third-label sample ({len(sample)} of {len(selection)}): "
        + ", ".join(sample)
    )
    return 0


def _run_validate(args: argparse.Namespace) -> int:
    from eaa.ambiguity_resolution.annotations import load_batch

    dataset, problems = load_batch(Path(args.out))
    if problems:
        for problem in problems:
            print(f"problem: {problem}", file=sys.stderr)
        print(f"batch INVALID ({len(problems)} problems)", file=sys.stderr)
        return 1
    print(f"batch VALID ({len(dataset.records)} questions)")
    return 0


def _run_freeze(args: argparse.Namespace) -> int:
    record = freeze_batch(
        Path(args.out), data_root=args.data_root
    )
    lock_path = write_lock(record, Path(args.lock))
    print(f"freeze OK: sha256={record['sha256']}")
    print(f"lock written to {lock_path} ({len(record['files'])} files hashed)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested preparation step; return the process exit code."""
    args = _build_parser().parse_args(argv)
    try:
        if args.mode == "manifest":
            return _run_manifest(args)
        if args.mode == "workspace":
            return _run_workspace(args)
        if args.mode == "sample":
            return _run_sample(args)
        if args.mode == "validate":
            return _run_validate(args)
        if args.mode == "freeze":
            return _run_freeze(args)
        raise AnnotationPrepError(f"unknown mode {args.mode!r}")
    except (AnnotationPrepError, ExperimentError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


__all__ = [
    "DEFAULT_BATCH_ROOT",
    "DEFAULT_CANDIDATES",
    "DEFAULT_CONFIG",
    "DEFAULT_LOCK",
    "DEFAULT_SCREENING",
    "main",
]

if __name__ == "__main__":
    raise SystemExit(main())
