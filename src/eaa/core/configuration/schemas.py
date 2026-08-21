"""Typed configuration models for the framework.

Config files are validated against these frozen models so misspelled or unknown
keys fail loudly instead of silently changing a run. All models reuse
``ContractModel`` semantics (frozen, ``extra="forbid"``).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

from ..contracts.base import ContractModel


class ProjectConfig(ContractModel):
    """Project-level metadata recorded with every run."""

    name: str = "Enterprise-AI-Analyst-Framework"
    phase: int | None = None


class LoggingConfig(ContractModel):
    """Logging settings."""

    level: str = "INFO"
    format: Literal["structured", "console"] = "structured"
    redaction: bool = True


class SecurityConfig(ContractModel):
    """Security model: read-only execution, timeouts, caps."""

    read_only_execution: bool = True
    default_timeout_seconds: int = 30
    max_query_timeout_seconds: int = 120


class LLMConfig(ContractModel):
    """LLM provider/backend settings (transport only)."""

    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: float = 0.0
    max_retries: int = 3
    timeout_seconds: int = 60


class EvaluationConfig(ContractModel):
    """Evaluation methodology settings (versioned; see docs/07)."""

    schema_version: str = "eval-schema-v1"
    confidence_intervals: bool = True
    bootstrap_resamples: int = 1000
    alpha: float = 0.05
    human_review: bool = False
    metrics: list[str] = Field(default_factory=list)


class ExperimentConfig(ContractModel):
    """Experiment identity and reproducibility settings."""

    id: str | None = None
    seed: int = 0
    record_artifacts: bool = True


class PipelineConfig(ContractModel):
    """Pipeline composition: ordered stage names, prompt version, and budget.

    ``prompt_version`` pins the prompt used for a run (ADR-004) so the same
    config reproduces the same prompt; ``max_llm_calls`` caps the per-task LLM
    budget (a baseline run uses exactly one generation call).
    """

    stages: list[str] = Field(default_factory=list)
    prompt_version: str = "baseline-v1"
    max_llm_calls: int | None = None
    self_correction_rounds: int = 0


class ManifestConfig(ContractModel):
    """Dataset manifest metadata carried in config."""

    version: str | None = None
    checksum: str | None = None
    license: str | None = None
    citation: str | None = None


class DatasetConfig(ContractModel):
    """Per-dataset settings.

    ``dialect``, ``data_root``, ``linking_mode``, ``table_budget`` and
    ``metric_groups`` are generic (dataset-independent) knobs used by adapters
    and the pipeline; adapters never extend this model with dataset names.
    """

    name: str | None = None
    phase: int | None = None
    split: str | None = None
    dialect: str | None = None
    data_root: str | None = None
    linking_mode: Literal["retrieval", "retrieval_free"] | None = None
    table_budget: int | None = None
    metric_groups: list[str] = Field(default_factory=list)
    manifest: ManifestConfig = Field(default_factory=ManifestConfig)


class SchemaConfig(ContractModel):
    """Schema-representation settings."""

    enriched: bool = False


class AmbiguityConfig(ContractModel):
    """Ambiguity-resolution settings (M1.5; the E2 experiment factor).

    ``resolution`` defaults to ``off`` so the M1.2–M1.4 behavior is preserved
    byte-for-byte: no analysis is produced and the original question flows to
    the prompt builder unchanged. ``heuristic`` and ``llm`` select the detector
    engine; ``max_assumptions`` bounds how many formalized assumptions a
    clarification may carry; ``interactive`` gates human-in-the-loop
    clarification (offline harnesses keep it False).
    """

    resolution: Literal["off", "heuristic", "llm"] = "off"
    max_assumptions: int = Field(default=1, ge=1)
    interactive: bool = False


class RootConfig(ContractModel):
    """The fully typed configuration for a run/experiment.

    ``schema_config`` maps the ``schema:`` YAML key (avoids shadowing pydantic's
    ``BaseModel.schema``); ``populate_by_name`` keeps both spellings accepted.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    experiment: ExperimentConfig = Field(default_factory=ExperimentConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    dataset: DatasetConfig = Field(default_factory=DatasetConfig)
    schema_config: SchemaConfig = Field(default_factory=SchemaConfig, alias="schema")
    ambiguity: AmbiguityConfig = Field(default_factory=AmbiguityConfig)


class RuntimeConfig(ContractModel):
    """Resolved configuration plus the immutable JSON snapshot.

    ``resolved`` is the exact merged dict (defaults -> dataset -> experiment ->
    CLI overrides -> env vars) and is written verbatim to
    ``config.resolved.json`` in each run's artifact directory, so the snapshot
    is the single source of truth for what actually ran.
    """

    root: RootConfig
    resolved: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AmbiguityConfig",
    "DatasetConfig",
    "EvaluationConfig",
    "ExperimentConfig",
    "LLMConfig",
    "LoggingConfig",
    "ManifestConfig",
    "PipelineConfig",
    "ProjectConfig",
    "RootConfig",
    "RuntimeConfig",
    "SchemaConfig",
    "SecurityConfig",
]
