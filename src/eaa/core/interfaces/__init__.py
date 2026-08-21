"""Core interfaces: protocols defining module and adapter boundaries.

This is the dataset-independence boundary (ADR-001, ADR-002). Interfaces only —
no implementations. Concrete implementations are provided by the registry
package and by dataset adapters / LLM backends / executors / metrics.
"""
from __future__ import annotations

from .ambiguity import AmbiguityResolver, AnswerabilityJudger
from .dataset import BenchmarkAdapter, DatasetAdapter
from .evaluation import Evaluator
from .execution import QueryExecutor
from .linking import SchemaLinker
from .llm import LLMBackend
from .metadata import MetadataProvider
from .metrics import Metric
from .registry import ComponentRegistry
from .schema import SchemaProvider
from .tracking import Tracker
from .viz import VizEngine

__all__ = [
    "AmbiguityResolver",
    "AnswerabilityJudger",
    "BenchmarkAdapter",
    "ComponentRegistry",
    "DatasetAdapter",
    "Evaluator",
    "LLMBackend",
    "MetadataProvider",
    "Metric",
    "QueryExecutor",
    "SchemaLinker",
    "SchemaProvider",
    "Tracker",
    "VizEngine",
]
