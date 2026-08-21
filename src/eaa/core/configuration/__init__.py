"""Typed, layered, validated configuration system.

Purpose: load/merge/validate/resolve configuration for runs and experiments.
Layer order (highest priority last): ``default.yaml`` -> ``datasets/<d>.yaml``
-> ``experiments/<e>.yaml`` -> CLI overrides -> env vars.
"""
from __future__ import annotations

from .loader import (
    ConfigurationError,
    apply_env_overrides,
    apply_overrides,
    deep_merge,
    load_config_chain,
    load_yaml,
    resolve_config,
)
from .schemas import (
    DatasetConfig,
    EvaluationConfig,
    ExperimentConfig,
    LLMConfig,
    LoggingConfig,
    ManifestConfig,
    PipelineConfig,
    ProjectConfig,
    RootConfig,
    RuntimeConfig,
    SchemaConfig,
    SecurityConfig,
)

__all__ = [
    "ConfigurationError",
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
    "apply_env_overrides",
    "apply_overrides",
    "deep_merge",
    "load_config_chain",
    "load_yaml",
    "resolve_config",
]
