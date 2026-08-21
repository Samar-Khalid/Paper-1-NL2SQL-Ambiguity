"""Data contracts for the framework (contract-first design).

The contracts package is the single source of truth for every object that
crosses a module boundary. Core modules, research modules, and dataset adapters
all exchange these types and nothing else.

Design rules (see architecture/adrs/ADR-001-dataset-independent-contract-design.md):

- Contracts are immutable and strict (``frozen=True``, ``extra="forbid"``) so
  misspelled fields fail loudly instead of silently corrupting research data.
- Task, Prediction, GoldReference and report sections are **envelopes**: they
  carry a ``type_key`` and an opaque typed ``payload``. Payload validation is
  delegated to the payload registry (``core.registry.payload_registry``), so the
  core never needs to know the concrete payload types of any dataset.
- Contracts import only the standard library and pydantic.
"""

from .ambiguity import (
    AmbiguityAnalysis,
    AmbiguitySpan,
    AmbiguityType,
    AmbiguityVerdict,
    AnswerabilityVerdict,
    Assumption,
    ClarifiedQuestion,
)
from .base import ContractModel, Envelope, Payload, Provenance
from .gold import (
    ChartSpecGoldReference,
    DecisionGoldReference,
    GenericGoldReference,
    GoldHeader,
    GoldReferenceEnvelope,
    SqlGoldReference,
)
from .llm import Completion, CompletionParams, Message, Usage
from .manifest import DatasetManifest
from .metrics import (
    EvaluationReportEnvelope,
    EvaluationReportHeader,
    EvaluationReportPayload,
    MetricResult,
    ReviewSummary,
)
from .prediction import (
    ChartSpecPrediction,
    DecisionPrediction,
    GenericPrediction,
    PredictionEnvelope,
    PredictionError,
    PredictionHeader,
    SqlPrediction,
)
from .query import QueryColumn, QueryResult
from .report import (
    AnalysisReportEnvelope,
    AnalysisReportPayload,
    ReportHeader,
    ReportSection,
    SectionHeader,
)
from .runtime import Budget, RuntimeContext, SessionState, Turn
from .schema import (
    ColumnSchema,
    ColumnSemantics,
    DatabaseSchema,
    EnrichedSchema,
    EnrichmentData,
    ForeignKeySpec,
    RelationshipSpec,
    TableSchema,
)
from .task import (
    DecisionTask,
    GenericTask,
    SqlGenerationTask,
    TaskEnvelope,
    TaskHeader,
    VisualizationTask,
)
from .visualization import ChartSpec, VisualizationPayload, VizIntent

__all__ = [
    "AmbiguityAnalysis",
    "AmbiguitySpan",
    "AmbiguityType",
    "AmbiguityVerdict",
    "AnalysisReportEnvelope",
    "AnalysisReportPayload",
    "AnswerabilityVerdict",
    "Assumption",
    "Budget",
    "ChartSpec",
    "ChartSpecGoldReference",
    "ChartSpecPrediction",
    "ClarifiedQuestion",
    "ColumnSchema",
    "ColumnSemantics",
    "Completion",
    "CompletionParams",
    "ContractModel",
    "DatabaseSchema",
    "DatasetManifest",
    "DecisionGoldReference",
    "DecisionPrediction",
    "DecisionTask",
    "EnrichedSchema",
    "EnrichmentData",
    "Envelope",
    "EvaluationReportEnvelope",
    "EvaluationReportHeader",
    "EvaluationReportPayload",
    "ForeignKeySpec",
    "GenericGoldReference",
    "GenericPrediction",
    "GenericTask",
    "GoldHeader",
    "GoldReferenceEnvelope",
    "Message",
    "MetricResult",
    "Payload",
    "PredictionEnvelope",
    "PredictionError",
    "PredictionHeader",
    "Provenance",
    "QueryColumn",
    "QueryResult",
    "ReportHeader",
    "ReportSection",
    "RelationshipSpec",
    "ReviewSummary",
    "RuntimeContext",
    "SectionHeader",
    "SessionState",
    "SqlGenerationTask",
    "SqlGoldReference",
    "SqlPrediction",
    "TableSchema",
    "TaskEnvelope",
    "TaskHeader",
    "Turn",
    "Usage",
    "VisualizationPayload",
    "VisualizationTask",
    "VizIntent",
]
