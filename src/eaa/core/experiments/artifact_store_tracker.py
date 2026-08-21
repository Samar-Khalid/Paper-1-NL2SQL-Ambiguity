"""Persistence tracker: records runs into the canonical artifact layout."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..contracts.metrics import MetricResult
from .artifacts import ArtifactStore
from .run_id import RunId


class ArtifactStoreTracker:
    """A ``Tracker`` that persists to ``experiments/runs/<run_id>/``.

    ``start_run`` creates the canonical skeleton (config + meta), ``log_instance``
    writes per-instance prediction/gold pairs, and ``finish_run`` writes the
    aggregated ``metrics.json``. Use ``NullTracker`` to discard instead.
    """

    def __init__(self, store: ArtifactStore | None = None) -> None:
        self._store = store if store is not None else ArtifactStore()
        self._metrics: dict[str, list[MetricResult]] = {}

    def start_run(
        self,
        run_id: str,
        *,
        meta: dict[str, Any] | None = None,
    ) -> None:
        """Create the run skeleton; ``meta`` may carry ``config_resolved``."""
        run = RunId.parse(str(run_id))
        meta = dict(meta) if meta else {}
        config_snapshot = meta.pop("config_resolved", None)
        self._store.create_run(
            run,
            config_snapshot=config_snapshot if isinstance(config_snapshot, dict) else None,
            meta=meta,
        )
        self._metrics[str(run)] = []

    def log_metric(self, run_id: str, metric: MetricResult) -> None:
        """Buffer one metric result for ``run_id``."""
        self._metrics.setdefault(str(run_id), []).append(metric)

    def log_instance(
        self,
        run_id: str,
        instance_id: str,
        prediction: dict[str, Any],
        gold: dict[str, Any] | None = None,
    ) -> None:
        """Write one (prediction, gold) pair to the run's predictions dir."""
        run = RunId.parse(str(run_id))
        run_dir = self._store.run_dir(run)
        record: dict[str, Any] = {"prediction": prediction, "gold": gold}
        path = _instance_path(run_dir, instance_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record, indent=2, sort_keys=True, default=_json_default),
            encoding="utf-8",
        )

    def finish_run(self, run_id: str) -> None:
        """Write the aggregated metrics file for ``run_id``."""
        run = RunId.parse(str(run_id))
        run_dir = self._store.run_dir(run)
        run_dir.mkdir(parents=True, exist_ok=True)
        metrics = self._metrics.get(str(run), [])
        aggregated = {
            "metrics": [metric.model_dump() for metric in metrics],
            "num_instances": _count_instances(run_dir),
        }
        self._store.write_metrics(run_dir, aggregated)


def _instance_path(run_dir: Path, instance_id: str) -> Path:
    """Build a filesystem-safe path for ``instance_id``.

    Instance ids come from task ids and may contain characters that are
    invalid in filenames on Windows, so the stem is sanitized; when the name
    changes, a short digest is appended to keep records unique.
    """
    stem = "".join(
        ch for ch in instance_id if ch.isalnum() or ch in " ._-"
    ).strip(" .")
    if stem != instance_id or not stem:
        digest = hashlib.sha1(instance_id.encode("utf-8")).hexdigest()[:8]  # noqa: S324
        stem = f"{stem or 'instance'}-{digest}"
    return run_dir / "predictions" / f"{stem}.json"


def _count_instances(run_dir: Path) -> int:
    """Count per-instance prediction files in the run's predictions dir."""
    predictions = run_dir / "predictions"
    if not predictions.is_dir():
        return 0
    return len([path for path in predictions.iterdir() if path.suffix == ".json"])


def _json_default(value: Any) -> Any:
    """Fallback serializer for non-JSON-safe values."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return repr(value)


__all__ = ["ArtifactStoreTracker"]
