"""Baseline evaluation driver: reproducible floor measurement for NL2SQL.

M1.3 — composes existing components (typed config, dataset adapter, LLM backend,
baseline pipeline, evaluation harness, artifact store) into a repeatable
baseline run and records the canonical artifact layout::

    runs/<run_id>/
        config.resolved.json   # immutable merged config snapshot
        meta.json              # dataset manifest, split, prompt version, model
        metrics.json           # run-level aggregates (via the tracker)
        predictions/           # per-instance prediction/gold pairs
        artifacts/evaluation_report.json  # full EvaluationReportEnvelope

The driver is dataset-independent: the adapter is resolved by name from the
``eaa.datasets`` entry-point group (ADR-002), so the same driver runs any
adapter that yields ``TaskEnvelope(nl2sql)`` tasks plus a per-database
``SchemaProvider`` (Decision D2). No dataset name or logic appears here.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from eaa.core.configuration import RuntimeConfig, resolve_config
from eaa.core.contracts.gold import GoldReferenceEnvelope
from eaa.core.contracts.metrics import EvaluationReportPayload
from eaa.core.contracts.prediction import PredictionEnvelope
from eaa.core.contracts.runtime import Budget, SessionState
from eaa.core.contracts.task import TaskEnvelope
from eaa.core.experiments import (
    ArtifactStore,
    ArtifactStoreTracker,
    RunId,
    Tracker,
    generate_run_id,
)
from eaa.core.interfaces.dataset import BenchmarkAdapter
from eaa.core.interfaces.llm import LLMBackend
from eaa.core.pipeline import OUTPUT_KEY
from eaa.core.pipeline.pipeline import build_baseline_pipeline
from eaa.core.registry import plugin_registry
from eaa.evaluation import EvaluationHarness
from eaa.llm import backend_from_config

from .errors import ExperimentError

RUN_TAG = "baseline"


@dataclass(frozen=True)
class BaselineRunSummary:
    """Structured outcome of one baseline evaluation run."""

    run_id: str
    dataset_id: str | None
    split: str | None
    num_tasks: int
    num_predictions: int
    num_failed: int
    metrics: dict[str, float]
    run_dir: Path
    report_path: Path | None = None


class BaselineExperiment:
    """Runs the baseline NL2SQL evaluation over one dataset split.

    The generation pipeline (prompt_builder -> llm_generation -> validation) is
    run per task; predictions are evaluated offline in one batch over the whole
    split (ADR-009), so metrics aggregate across all tasks.
    """

    def __init__(
        self,
        *,
        config: RuntimeConfig,
        adapter: BenchmarkAdapter,
        schema_provider: Any,
        llm: LLMBackend,
        run_id: str,
        tracker: Tracker | None = None,
        store: ArtifactStore | None = None,
        harness: EvaluationHarness | None = None,
        dataset_id: str | None = None,
    ) -> None:
        RunId.parse(run_id)
        self._config = config
        self._adapter = adapter
        self._llm = llm
        self._run_id = run_id
        self._dataset_id = dataset_id or getattr(adapter, "name", None)
        self._store = store if store is not None else ArtifactStore()
        self._tracker = tracker if tracker is not None else ArtifactStoreTracker(store=self._store)
        self._harness = harness if harness is not None else EvaluationHarness(tracker=self._tracker)
        self._generation = build_baseline_pipeline(
            llm=llm,
            schema_provider=schema_provider,
            prompt_version=config.root.pipeline.prompt_version,
            budget=_budget_from(config),
        )

    def run(self, split: str | None = None, *, limit: int | None = None) -> BaselineRunSummary:
        """Generate predictions for the split and evaluate them offline.

        Parameters
        ----------
        split:
            Split to evaluate (defaults to the adapter default).
        limit:
            Optional cap on the number of tasks (dry runs).

        Returns
        -------
        BaselineRunSummary
            Structured run outcome; artifacts are written to the run dir.
        """
        adapter = self._adapter
        tasks = asyncio.run(_collect_tasks(adapter, split))
        if limit is not None:
            tasks = tasks[: max(0, limit)]

        self._tracker.start_run(self._run_id, meta=self._meta(split=split, adapter=adapter))

        pairs: list[tuple[PredictionEnvelope, GoldReferenceEnvelope]] = []
        num_failed = 0
        for task in tasks:
            result = self._generation.run(
                task, session=SessionState(session_id=self._run_id)
            )
            if not result.ok:
                num_failed += 1
                continue
            prediction = PredictionEnvelope.model_validate(result.state[OUTPUT_KEY])
            pairs.append((prediction, adapter.gold_for(task.header.task_id)))

        report = self._harness.evaluate_pairs(
            run_id=self._run_id,
            dataset_id=self._dataset_id,
            split=split,
            pairs=pairs,
            metric_names=_metrics_from(self._config),
            metadata=self._report_metadata(),
        )
        report_path = self._write_report(report)
        self._tracker.finish_run(self._run_id)

        payload = cast(EvaluationReportPayload, report.payload)
        return BaselineRunSummary(
            run_id=self._run_id,
            dataset_id=self._dataset_id,
            split=split,
            num_tasks=len(tasks),
            num_predictions=len(pairs),
            num_failed=num_failed,
            metrics={
                metric.metric_name: metric.value for metric in payload.summary.metrics
            }
            if payload.summary
            else {},
            run_dir=self._store.run_dir(RunId.parse(self._run_id)),
            report_path=report_path,
        )

    def _meta(self, *, split: str | None, adapter: BenchmarkAdapter) -> dict[str, Any]:
        """Build the run meta record (config snapshot + reproducibility keys)."""
        return {
            "config_resolved": self._config.resolved,
            "experiment_id": self._config.root.experiment.id,
            "dataset_id": self._dataset_id,
            "split": split,
            "dataset_manifest": adapter.manifest().model_dump(mode="json"),
            "prompt_version": self._config.root.pipeline.prompt_version,
            "metadata_enriched": self._config.root.schema_config.enriched,
            "model_id": getattr(self._llm, "model_id", None),
        }

    def _report_metadata(self) -> dict[str, Any]:
        """Reproducibility metadata attached to the evaluation report."""
        return {
            "experiment_id": self._config.root.experiment.id,
            "prompt_version": self._config.root.pipeline.prompt_version,
            "metadata_enriched": self._config.root.schema_config.enriched,
            "model_id": getattr(self._llm, "model_id", None),
        }

    def _write_report(self, report: Any) -> Path:
        """Persist the evaluation report envelope under the run's artifacts dir."""
        run_dir = self._store.run_dir(RunId.parse(self._run_id))
        report_path = run_dir / "artifacts" / "evaluation_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return report_path


def build_baseline_experiment(
    config_path: str | Path,
    *,
    config_root: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
    adapter: BenchmarkAdapter | None = None,
    llm: LLMBackend | None = None,
    tracker: Tracker | None = None,
    artifact_root: str | Path | None = None,
    run_id: str | None = None,
    dataset_id: str | None = None,
) -> BaselineExperiment:
    """Resolve config and collaborators into a ready-to-run baseline experiment.

    Parameters
    ----------
    config_path:
        Experiment config file (defaults chain resolved first).
    config_root:
        Base directory for relative ``defaults:`` entries.
    overrides:
        CLI-style overrides (nested dicts or dotted keys), applied before env.
    adapter:
        Optional adapter instance; when omitted, loaded from the ``eaa.datasets``
        entry-point group by ``dataset.name``.
    llm:
        Optional backend; when omitted, built from ``config.root.llm`` via
        ``backend_from_config``.
    tracker:
        Optional tracker; defaults to an ``ArtifactStoreTracker``.
    artifact_root:
        Artifact root override (defaults to ``experiments/runs`` or
        ``EAA_ARTIFACT_ROOT``).
    run_id:
        Optional run id (must match the ``RunId`` format); a tagged id is
        generated otherwise.
    dataset_id:
        Optional report dataset id (defaults to the adapter name).

    Raises
    ------
        ExperimentError: if the adapter cannot be resolved or exposes no
            ``schema_provider()``.
    """
    config = resolve_config(config_path, config_root=config_root, overrides=overrides)
    adapter = adapter if adapter is not None else _load_adapter(config)
    schema_provider = _maybe_enrich(config, adapter, _schema_provider_of(adapter))
    llm = llm if llm is not None else backend_from_config(config.root.llm)
    run_id = run_id or str(generate_run_id(RUN_TAG))
    store = ArtifactStore(root=Path(artifact_root) if artifact_root else None)
    tracker = tracker if tracker is not None else ArtifactStoreTracker(store=store)
    harness = EvaluationHarness(tracker=tracker)
    return BaselineExperiment(
        config=config,
        adapter=adapter,
        schema_provider=schema_provider,
        llm=llm,
        run_id=run_id,
        tracker=tracker,
        store=store,
        harness=harness,
        dataset_id=dataset_id,
    )


def _load_adapter(config: RuntimeConfig) -> BenchmarkAdapter:
    """Resolve a dataset adapter by name from the entry-point group."""
    name = config.root.dataset.name
    if not name:
        raise ExperimentError(
            "no dataset adapter configured: set dataset.name in the experiment config"
        )
    factory = plugin_registry.discover().get(name)
    if factory is None:
        raise ExperimentError(
            f"no dataset adapter plugin named {name!r} in entry-point group 'eaa.datasets'"
        )
    data_root = config.root.dataset.data_root
    if data_root and _accepts_root(factory):
        return cast(BenchmarkAdapter, cast(Any, factory)(root=data_root))
    return cast(BenchmarkAdapter, factory())


def _accepts_root(factory: Any) -> bool:
    """Return whether ``factory`` can be called with a ``root`` keyword."""
    try:
        params = inspect.signature(factory).parameters
    except (TypeError, ValueError):
        return False
    return "root" in params or any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
    )


def _schema_provider_of(adapter: BenchmarkAdapter) -> Any:
    """Return the per-database ``SchemaProvider`` from the adapter (Decision D2)."""
    factory = getattr(adapter, "schema_provider", None)
    if not callable(factory):
        raise ExperimentError(
            "adapter must expose schema_provider() returning a SchemaProvider (Decision D2)"
        )
    return factory()


def _metadata_provider_of(adapter: BenchmarkAdapter) -> Any:
    """Return the adapter's ``MetadataProvider``, or None when not exposed.

    Adapters publish enrichment as data (ADR-015) through a ``metadata()``
    factory, mirroring ``schema_provider()``.
    """
    factory = getattr(adapter, "metadata", None)
    if not callable(factory):
        return None
    return factory()


def _maybe_enrich(config: RuntimeConfig, adapter: BenchmarkAdapter, provider: Any) -> Any:
    """Wrap the schema provider with enrichment when the toggle is on.

    The metadata OFF/ON experiment is a provider swap: OFF injects the base
    ``SchemaProvider`` (byte-identical baseline prompts), ON injects an
    ``EnrichedSchemaProvider`` that merges the adapter's metadata sidecar. An
    ON run over an adapter with no ``metadata()`` fails loudly rather than
    silently degrading to a baseline run (the config said enrichment was
    required, so recording a baseline would corrupt the comparison).
    """
    if not config.root.schema_config.enriched:
        return provider
    metadata = _metadata_provider_of(adapter)
    if metadata is None:
        raise ExperimentError(
            "schema.enriched is true but the adapter exposes no metadata() "
            "source; the metadata-ON arm needs an enrichment sidecar (ADR-015)"
        )
    from eaa.metadata import EnrichedSchemaProvider  # type: ignore[import-untyped]

    return EnrichedSchemaProvider(base=provider, metadata=metadata)


def _budget_from(config: RuntimeConfig) -> Budget:
    """Build the per-task budget from pipeline config (baseline: one call)."""
    max_calls = config.root.pipeline.max_llm_calls
    return Budget(max_llm_calls=max_calls) if max_calls is not None else Budget()


def _metrics_from(config: RuntimeConfig) -> list[str] | None:
    """Return the configured metric names, or None to use all registered."""
    metrics = config.root.evaluation.metrics
    return list(metrics) if metrics else None


async def _collect_tasks(adapter: BenchmarkAdapter, split: str | None) -> list[TaskEnvelope]:
    """Drain the (async) task stream into a list, optionally filtered by split."""
    return [task async for task in adapter.task_stream(split)]


__all__ = [
    "BaselineExperiment",
    "BaselineRunSummary",
    "RUN_TAG",
    "build_baseline_experiment",
]
