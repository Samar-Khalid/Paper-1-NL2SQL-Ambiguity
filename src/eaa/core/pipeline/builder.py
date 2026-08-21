"""Baseline NL2SQL pipeline builder: compose the generic stages into a Pipeline.

Dataset-independent (ADR-002/006): collaborators are injected via interfaces
(``LLMBackend``, ``SchemaProvider``) and callables (``gold_for``), so the same
composition runs against any dataset adapter that yields ``TaskEnvelope``
objects. No dataset name appears here.
"""
from __future__ import annotations

from collections.abc import Callable

from eaa.evaluation.harness import EvaluationHarness

from ..contracts.gold import GoldReferenceEnvelope
from ..contracts.runtime import Budget
from ..interfaces.llm import LLMBackend
from ..interfaces.schema import SchemaProvider
from .runner import Pipeline
from .stage import Stage
from .stages.evaluation_stage import EvaluationStage
from .stages.llm_stage import LlmGenerationStage
from .stages.prompt_builder import PROMPT_VERSION, PromptBuilderStage
from .stages.validation_stage import ValidationStage


class BaselinePipelineBuilder:
    """Build the baseline prompt -> LLM -> validate -> evaluate pipeline.

    The evaluation stage is included only when ``gold_for`` is provided
    (offline evaluation, ADR-009); prediction paths never need gold.
    """

    def __init__(
        self,
        *,
        llm: LLMBackend,
        schema_provider: SchemaProvider,
        gold_for: Callable[[str], GoldReferenceEnvelope] | None = None,
        harness: EvaluationHarness | None = None,
        run_id: str | None = None,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self._llm = llm
        self._schema_provider = schema_provider
        self._gold_for = gold_for
        self._harness = harness
        self._run_id = run_id
        self.prompt_version = prompt_version

    def build(self, *, budget: Budget | None = None) -> Pipeline:
        """Return a runnable ``Pipeline`` with unique, ordered stage names."""
        stages: list[Stage] = [
            PromptBuilderStage(
                self._schema_provider, prompt_version=self.prompt_version
            ),
            LlmGenerationStage(self._llm, prompt_version=self.prompt_version),
            ValidationStage(),
        ]
        if self._gold_for is not None:
            stages.append(
                EvaluationStage(
                    self._gold_for,
                    harness=self._harness,
                    run_id=self._run_id,
                )
            )
        return Pipeline(stages, budget=budget)
