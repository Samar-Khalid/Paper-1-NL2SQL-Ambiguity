"""Ambiguity-resolution protocols: the module boundary (ADR-014).

``AmbiguityResolver`` turns an unresolved task question into an
``AmbiguityAnalysis`` and, where needed, a ``ClarifiedQuestion``;
``AnswerabilityJudger`` decides whether the (possibly clarified) question is
answerable at all (RQ1.4). Implementations live in ``ambiguity_resolution/``;
core defines only the boundary, so detectors and judgers are swappable
experiment factors (docs/12).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..contracts.ambiguity import (
    AmbiguityAnalysis,
    AnswerabilityVerdict,
    ClarifiedQuestion,
)
from ..contracts.runtime import RuntimeContext
from ..contracts.task import TaskEnvelope


@runtime_checkable
class AmbiguityResolver(Protocol):
    """Detects and resolves ambiguity for one task question.

    Structural protocol: any object with ``analyze`` and ``resolve`` methods
    satisfies it. ``resolve`` is called only when ``analysis.verdict`` is not
    ``unambiguous``; a config of ``resolution: off`` injects a no-op stage so
    the baseline path never constructs these contracts.
    """

    def analyze(
        self, task: TaskEnvelope, context: RuntimeContext
    ) -> AmbiguityAnalysis:
        """Return the ambiguity analysis for ``task``'s question."""
        ...

    def resolve(
        self,
        analysis: AmbiguityAnalysis,
        task: TaskEnvelope,
        context: RuntimeContext,
    ) -> ClarifiedQuestion:
        """Return the clarified question resolving ``analysis``."""
        ...


@runtime_checkable
class AnswerabilityJudger(Protocol):
    """Judges whether a question is answerable from the available data.

    Called for every task; ``analysis`` may be None when ambiguity detection is
    disabled, in which case the judge relies on the question and schema alone.
    """

    def judge(
        self,
        task: TaskEnvelope,
        analysis: AmbiguityAnalysis | None,
        context: RuntimeContext,
    ) -> AnswerabilityVerdict:
        """Return the answerability verdict for ``task``."""
        ...


__all__ = ["AmbiguityResolver", "AnswerabilityJudger"]
