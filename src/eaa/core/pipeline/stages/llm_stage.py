"""LLM stage: call the backend, parse SQL from its output, emit a prediction.

The stage isolates the LLM boundary: it counts the call against the run budget
(ADR-003), records provenance (``prompt_version``, ``model_id``, ADR-004), and
maps malformed/non-SQL output to a structured ``PredictionError`` inside the
envelope instead of raising (docs/11 §5.5). It never raises for bad model
output.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from ...contracts.llm import Completion, Message
from ...contracts.prediction import PredictionEnvelope
from ...contracts.runtime import RuntimeContext
from ...contracts.task import TaskEnvelope
from ...interfaces.llm import LLMBackend
from ...registry import envelope_for
from ..stage import (
    GENERATION_KEY,
    OUTPUT_KEY,
    PROMPT_KEY,
    get_budget_ledger,
    get_state,
    set_state,
)
from .prompt_builder import PROMPT_VERSION

_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_SQL_LEAD = re.compile(r"^\s*(?:SELECT|WITH)\b", re.DOTALL | re.IGNORECASE)
_FALLBACK_SYSTEM = (
    "Translate the user's question into a single read-only SQL query. "
    "Return only the SQL query."
)


def extract_sql(text: str) -> str | None:
    """Extract the SQL query from an LLM response, or ``None`` when absent.

    Accepts a fenced ```sql`` block or plain output whose first keyword is
    ``SELECT``/``WITH``. The candidate is returned verbatim (metrics define
    matching); no semicolons are stripped.
    """
    fence = _FENCE.search(text)
    if fence is not None:
        return fence.group(1).strip()
    stripped = text.strip()
    if _SQL_LEAD.match(stripped) is not None:
        return stripped
    return None


def _messages(context: RuntimeContext, task: TaskEnvelope) -> list[Message]:
    """Return the prompt-stage messages, falling back to a minimal prompt."""
    prompt = get_state(context, PROMPT_KEY)
    raw = prompt.get("messages") if isinstance(prompt, dict) else None
    if isinstance(raw, list) and raw:
        return [Message(**item) for item in raw]
    return [
        Message(role="system", content=_FALLBACK_SYSTEM),
        Message(role="user", content=task.header.question),
    ]


def _effective_prompt_version(context: RuntimeContext, configured: str) -> str:
    """Return the prompt version the prompt builder actually used.

    The prompt builder records the effective version (``baseline-v1`` or
    ``enriched-v1``) in the prompt state; provenance must match it exactly so
    recorded runs stay reproducible (ADR-004).
    """
    prompt = get_state(context, PROMPT_KEY)
    version = prompt.get("prompt_version") if isinstance(prompt, dict) else None
    if isinstance(version, str) and version:
        return version
    return configured


class LlmGenerationStage:
    """Stage 2: run the LLM and publish a ``PredictionEnvelope``."""

    name = "llm_generation"

    def __init__(
        self,
        llm: LLMBackend,
        *,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self.llm = llm
        self.prompt_version = prompt_version

    def run(self, context: RuntimeContext, task: TaskEnvelope) -> TaskEnvelope:
        """Complete the prompt, parse SQL, and store the prediction output."""
        ledger = get_budget_ledger(context)
        ledger.spend_llm_calls(1)
        completion = self.llm.complete(_messages(context, task))
        if completion.usage.total_tokens:
            ledger.spend_llm_tokens(completion.usage.total_tokens)
        prompt_version = _effective_prompt_version(context, self.prompt_version)
        prediction = self._prediction(task, completion, prompt_version)
        set_state(context, OUTPUT_KEY, prediction)
        set_state(
            context,
            GENERATION_KEY,
            {
                "model_id": completion.model_id,
                "sql": extract_sql(completion.message.content),
                "total_tokens": completion.usage.total_tokens,
                "finish_reason": completion.finish_reason,
            },
        )
        return task

    def _prediction(
        self,
        task: TaskEnvelope,
        completion: Completion,
        prompt_version: str,
    ) -> PredictionEnvelope:
        """Build the prediction envelope, mapping bad output to an error."""
        sql = extract_sql(completion.message.content)
        base: dict[str, Any] = {
            "header": {
                "prediction_id": f"{task.header.task_id}:pred",
                "task_id": task.header.task_id,
                "created_at": datetime.now(UTC).isoformat(),
                "model_id": completion.model_id,
            },
            "provenance": {
                "stage": self.name,
                "model_id": completion.model_id,
                "prompt_version": prompt_version,
            },
        }
        if sql is None:
            base["payload"] = {"sql": ""}
            base["error"] = {
                "error_type": "sql_parse_failure",
                "message": "LLM output did not contain a single SELECT/WITH query",
                "details": {"raw_output": completion.message.content},
            }
        else:
            base["payload"] = {"sql": sql}
        return envelope_for(PredictionEnvelope, "prediction.nl2sql", base)
