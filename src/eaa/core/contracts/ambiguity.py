"""Ambiguity-resolution data contracts (dataset-independent).

Enterprise questions are frequently under-specified: vague business terms,
missing constraints, or several plausible readings of the same text. The types
in this module are the boundary objects of ``ambiguity_resolution`` (ADR-014):
detection writes an ``AmbiguityAnalysis`` into
``RuntimeContext.state[AMBIGUITY_KEY]``; resolution turns it into a
``ClarifiedQuestion`` for prompt construction; unanswerable questions produce
an ``AnswerabilityVerdict`` (RQ1.4) instead of a guess.

None of these types names a dataset, a detector, or an engine: they are the
*outputs* of detection and the *inputs* to resolution, so the pipeline switches
on the verdict without knowing how it was computed (ADR-001). The taxonomy
enums reference the type catalogue in docs/12.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from .base import ContractModel


class AmbiguityType(StrEnum):
    """Taxonomy of ambiguity classes a question can exhibit (RQ1.1).

    Values are the stable type codes from the M1.5 taxonomy; the semantic
    member names and their definitions follow the canonical vocabulary in
    docs/13 §2: Lexical (L), Structural (S), Schema reference (R), Semantic
    value (V), Computational (C), Temporal (T), Knowledge (K), Intent (I),
    and the unanswerability branch (U).
    """

    LEXICAL_OVER_GENERALITY = "L1"
    SYNONYM_COLLISION = "L2"
    QUANTIFIER_SCOPE = "S1"
    ATTACHMENT = "S2"
    TABLE_SELECTION = "R1"
    JOIN_PATH = "R2"
    VALUE_ENTITY_LITERAL = "V1"
    UNIT_SCALE_CURRENCY = "V2"
    GRANULARITY = "V3"
    AGGREGATION_METRIC = "C1"
    TOP_N_RANKING = "C2"
    EXISTENCE_NEGATION = "C3"
    CONSTRAINT_BOUNDARY = "C4"
    RELATIVE_TEMPORAL = "T1"
    CALENDAR_FISCAL = "T2"
    EXTERNAL_KNOWLEDGE = "K1"
    BUSINESS_RULE = "K2"
    ANSWER_SHAPE = "I1"
    CHANNEL_ENCODING = "I2"
    CHART_TYPE = "I3"
    DATA_ABSENCE = "U1"
    FALSE_PREMISE = "U2"
    CONTRADICTION = "U3"
    OUT_OF_SCOPE = "U4"


class AmbiguityVerdict(StrEnum):
    """Overall verdict of one question analysis."""

    UNAMBIGUOUS = "unambiguous"
    AMBIGUOUS = "ambiguous"
    UNDERDETERMINED = "underdetermined"
    UNANSWERABLE = "unanswerable"


class AmbiguitySpan(ContractModel):
    """A character span of the question that exhibits one ambiguity type."""

    type: AmbiguityType
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    snippet: str | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_bounds(self) -> AmbiguitySpan:
        if self.end < self.start:
            raise ValueError("end must be >= start")
        return self


class Assumption(ContractModel):
    """One formalized interpretation adopted to make a question answerable.

    Resolution channels resolve an ambiguity to a metadata lookup, a
    clarification, or an assumption (docs/12). An assumption records the
    interpretation taken and the span it resolves, so a final query can be
    audited back to the ambiguity it disambiguated.
    """

    text: str
    span: AmbiguitySpan | None = None
    note: str | None = None


class AmbiguityAnalysis(ContractModel):
    """Output of ambiguity detection for one task (stage artifact, ADR-014).

    Carried in ``RuntimeContext.state[AMBIGUITY_KEY]`` and, when the pipeline
    records artifacts, as a serialized stage artifact. ``database_id`` ties the
    analysis to the schema the detector consulted; detectors run on the task
    question against injected schema/metadata providers, never on dataset
    internals.
    """

    database_id: str
    verdict: AmbiguityVerdict
    detected_types: list[AmbiguityType] = Field(default_factory=list)
    ambiguous_spans: list[AmbiguitySpan] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    assumptions: list[Assumption] = Field(default_factory=list)


class ClarifiedQuestion(ContractModel):
    """The re-phrased question that downstream stages consume after resolution.

    ``clarified_question`` is the text that replaces the original question for
    prompt construction; ``assumptions`` make the re-phrase auditable. When
    resolution is configured ``off`` no ``ClarifiedQuestion`` is produced and
    the original question is used unchanged.
    """

    original_question: str
    clarified_question: str
    assumptions: list[Assumption] = Field(default_factory=list)


class AnswerabilityVerdict(ContractModel):
    """RQ1.4 judgment of whether a question is answerable from the available data.

    Produced for every task, independent of detected ambiguity: a question can
    be perfectly precise and still unanswerable (missing data, false premise).
    ``confidence`` lets downstream policy (refuse vs answer-with-hedge)
    threshold without re-parsing.
    """

    answerable: bool
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reason: str | None = None


__all__ = [
    "AmbiguityAnalysis",
    "AmbiguitySpan",
    "AmbiguityType",
    "AmbiguityVerdict",
    "AnswerabilityVerdict",
    "Assumption",
    "ClarifiedQuestion",
]
