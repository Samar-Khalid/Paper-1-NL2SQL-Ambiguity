"""Typed internal representation of ``annotation-schema-v1`` annotations.

Models map one-to-one onto the labeled-question JSON defined in docs/13 §5.
They are immutable (frozen) and strict (``extra="forbid"``) so that malformed
labels fail loudly instead of silently corrupting research data.
"""
from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from eaa.core.contracts.ambiguity import AmbiguityType
from eaa.core.contracts.base import ContractModel

if TYPE_CHECKING:
    from .stats import AnnotationDatasetStats

_ReadingKey = Literal["sql_reading_A", "sql_reading_B"]


class AnswerabilityLabel(StrEnum):
    """Whether the labeled question is answerable on its own."""

    ANSWERABLE = "answerable"
    UNANSWERABLE = "unanswerable"


class AssumptionRisk(StrEnum):
    """Rough risk of the assumption needed to resolve the span."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ResolutionChannel(StrEnum):
    """How the span is meant to be resolved."""

    METADATA = "metadata"
    CLARIFICATION = "clarification"
    ASSUMPTION = "assumption"
    REFUSAL = "refusal"


class Answerability(ContractModel):
    """The answerability verdict recorded for one labeled question."""

    label: AnswerabilityLabel
    confidence: float = Field(ge=0.0, le=1.0)


class Interpretation(ContractModel):
    """One distinct, plausible SQL reading of the labeled question."""

    sql: str = Field(min_length=1)
    note: str | None = None


class AnnotationSpan(ContractModel):
    """One ambiguity annotation on a slice of the question text.

    ``start``/``end`` are half-open character offsets into ``question_text``
    (UTF-16 code units, i.e. Python ``len``), consistent with docs/13 §5.
    Overlapping spans are allowed (multi-label annotations).
    """

    span_id: str
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    ambiguity_type: AmbiguityType
    metadata_resolution: bool
    clarification_required: bool
    assumption_risk: AssumptionRisk
    resolution_channel: ResolutionChannel


class AnnotatedQuestion(ContractModel):
    """A labeled question: text, context, answerability, and ambiguity spans."""

    question_id: str
    question_text: str
    database_id: str
    answerability: Answerability
    spans: list[AnnotationSpan] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_spans(self) -> AnnotatedQuestion:
        seen: set[str] = set()
        text = self.question_text
        for span in self.spans:
            if span.span_id in seen:
                raise ValueError(
                    f"duplicate span_id {span.span_id!r} in question {self.question_id!r}"
                )
            seen.add(span.span_id)
            if span.end <= span.start:
                raise ValueError(
                    f"span {span.span_id!r} has non-positive length "
                    f"[{span.start}, {span.end})"
                )
            if span.end > len(text):
                raise ValueError(
                    f"span {span.span_id!r} end {span.end} exceeds question "
                    f"length {len(text)}"
                )
            actual = text[span.start : span.end]
            if actual != span.text:
                raise ValueError(
                    f"span {span.span_id!r} text does not match offsets: "
                    f"expected {actual!r}, got {span.text!r}"
                )
        return self


class AnnotationRecord(ContractModel):
    """One labeled question per the ``annotation-schema-v1`` schema.

    Interpretations are present only for strict-ambiguity questions (they carry
    the distinct SQL readings) and, when present, must include both
    ``sql_reading_A`` and ``sql_reading_B``.
    """

    schema_version: str
    question: AnnotatedQuestion
    interpretations: dict[_ReadingKey, Interpretation] | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_interpretations(self) -> AnnotationRecord:
        if self.interpretations is not None:
            expected = {"sql_reading_A", "sql_reading_B"}
            if set(self.interpretations) != expected:
                missing = expected - set(self.interpretations)
                raise ValueError(
                    f"interpretations must contain both readings, missing: "
                    f"{sorted(missing)}"
                )
        return self


class AnnotationDataset(ContractModel):
    """An immutable collection of labeled questions from one source."""

    schema_version: str
    records: tuple[AnnotationRecord, ...]

    @property
    def stats(self) -> AnnotationDatasetStats:
        """Read-only aggregate statistics for this dataset."""
        from .stats import compute_stats

        return compute_stats(self)


__all__ = [
    "AnnotatedQuestion",
    "AnnotationDataset",
    "AnnotationRecord",
    "AnnotationSpan",
    "Answerability",
    "AnswerabilityLabel",
    "AssumptionRisk",
    "Interpretation",
    "ResolutionChannel",
]
