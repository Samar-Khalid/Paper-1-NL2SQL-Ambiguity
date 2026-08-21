"""Experiment drivers: reproducible evaluation campaigns for framework pipelines.

The baseline driver (M1.3) wires the typed config, a dataset adapter, an LLM
backend, the baseline pipeline, the evaluation harness, and the artifact store
into a repeatable run that records the canonical artifact layout. Drivers live
outside ``core`` so they may compose adapters, LLM backends, and evaluation.
"""
from __future__ import annotations

from .baseline import (
    RUN_TAG,
    BaselineExperiment,
    BaselineRunSummary,
    build_baseline_experiment,
)
from .errors import ExperimentError
from .surface_b_candidates import DEFAULT_OUT, build_candidate_artifact

__all__ = [
    "RUN_TAG",
    "BaselineExperiment",
    "BaselineRunSummary",
    "ExperimentError",
    "DEFAULT_OUT",
    "build_baseline_experiment",
    "build_candidate_artifact",
]
