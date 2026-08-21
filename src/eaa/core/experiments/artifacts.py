"""Canonical artifact layout and storage for research runs."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .run_id import RunId


def default_artifact_root() -> Path:
    """Return the artifact root, overridable via ``EAA_ARTIFACT_ROOT``."""
    env = os.environ.get("EAA_ARTIFACT_ROOT")
    return Path(env) if env else Path("experiments", "runs")


class ArtifactStore:
    """Enforces the canonical per-run artifact layout.

    Layout::

        experiments/runs/<run_id>/
            config.resolved.json  # immutable config snapshot
            meta.json             # run metadata (dataset, split, env summary)
            metrics.json          # aggregated metrics
            predictions/          # per-instance prediction/gold pairs
            artifacts/            # plots, dumps
            logs/                 # structured logs
            traces.jsonl          # trace/span records
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_artifact_root()).resolve()

    def run_dir(self, run_id: RunId) -> Path:
        """Return the run directory path for ``run_id``."""
        return self.root / run_id.path_segment

    def create_run(
        self,
        run_id: RunId,
        *,
        config_snapshot: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Path:
        """Create the canonical directory skeleton for a run."""
        run_dir = self.run_dir(run_id)
        for sub in ("predictions", "artifacts", "logs"):
            (run_dir / sub).mkdir(parents=True, exist_ok=True)
        if config_snapshot is not None:
            self.write_config(run_dir, config_snapshot)
        if meta is not None:
            self.write_meta(run_dir, meta)
        return run_dir

    def write_config(self, run_dir: Path, config: dict[str, Any]) -> None:
        """Write the immutable config snapshot for a run."""
        _write_json(run_dir / "config.resolved.json", config)

    def write_meta(self, run_dir: Path, meta: dict[str, Any]) -> None:
        """Write the run metadata file."""
        _write_json(run_dir / "meta.json", meta)

    def write_metrics(self, run_dir: Path, metrics: dict[str, Any]) -> None:
        """Write the aggregated metrics file for a run."""
        _write_json(run_dir / "metrics.json", metrics)

    def write_trace(self, run_dir: Path, record: dict[str, Any]) -> None:
        """Append one trace record to the run's traces.jsonl."""
        with (run_dir / "traces.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    def prediction_path(self, run_dir: Path, instance_id: str) -> Path:
        """Return the prediction file path for an instance."""
        return run_dir / "predictions" / f"{instance_id}.json"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` as pretty JSON with sorted keys."""
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
