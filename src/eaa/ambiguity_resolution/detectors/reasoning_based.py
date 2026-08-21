"""Reasoning-based ambiguity detector (docs/14 §4B, M1.5 slice 2.9).

This is the second evidence family of the ambiguity detector: it establishes,
with model-based judgment over the question against the schema and its
enrichment, the **persistent-ambiguity band** — spans where at least two
schema-consistent readings with different results survive after the enterprise
metadata is applied (docs/13 §4, Step 3). Unlike the metadata-grounded family
(docs/14 §4A), whose claims are verifiable lookups, this family's claims are
defeasible judgments: they rest on the weight of the alternative readings, not
on a lookup, and where a defensible second reading cannot be established the
detector stays silent (conservative non-detection).

The detector emits exactly the ten taxonomy types that metadata cannot close:
``QUANTIFIER_SCOPE`` (S1), ``ATTACHMENT`` (S2), ``JOIN_PATH`` (R2),
``AGGREGATION_METRIC`` (C1), ``TOP_N_RANKING`` (C2), ``EXISTENCE_NEGATION``
(C3), ``RELATIVE_TEMPORAL`` (T1), ``EXTERNAL_KNOWLEDGE`` (K1),
``CHANNEL_ENCODING`` (I2), and ``CHART_TYPE`` (I3). It never emits the
metadata-grounded types (L2/R1/V1/V2/V3/T2/K2) — those belong to
``MetadataGroundedDetector`` — and it performs no resolution, clarification,
or answerability judgment (docs/14 §5).

The judgment is obtained through the existing ``LLMBackend`` protocol
(``core/interfaces/llm.py``): the detector builds a dataset-independent prompt
(question + compact schema + enrichment context) that asks for a structured
JSON judgment, which is strictly parsed into the existing ``AmbiguityAnalysis``
contract. Every call and its tokens are reported through the run's
``BudgetLedger`` (``core/pipeline/stage.py``), found in ``context.state`` under
``BUDGET_LEDGER_KEY``; running outside a pipeline raises ``PipelineError``.

The analysis verdict is ``ambiguous`` when at least one valid persistent span
survives parsing, otherwise ``unambiguous`` (invalid or out-of-scope spans are
dropped rather than guessed at). ``confidence`` is the model's own uncalibrated
signal, clamped to [0, 1] and recorded verbatim in the contract — no
calibration claim is made (docs/15 §4.4 evaluates calibration separately).
"""
from __future__ import annotations

import json
import re
from typing import Any

from eaa.core.contracts.ambiguity import (
    AmbiguityAnalysis,
    AmbiguitySpan,
    AmbiguityType,
    AmbiguityVerdict,
    ClarifiedQuestion,
)
from eaa.core.contracts.llm import Message
from eaa.core.contracts.runtime import RuntimeContext
from eaa.core.contracts.schema import ColumnSchema, DatabaseSchema, EnrichedSchema
from eaa.core.contracts.task import TaskEnvelope
from eaa.core.interfaces.llm import LLMBackend
from eaa.core.pipeline.stage import get_budget_ledger

from ..errors import AmbiguityResolutionError

REASONING_TYPES: tuple[AmbiguityType, ...] = (
    AmbiguityType.QUANTIFIER_SCOPE,  # S1
    AmbiguityType.ATTACHMENT,  # S2
    AmbiguityType.JOIN_PATH,  # R2
    AmbiguityType.AGGREGATION_METRIC,  # C1
    AmbiguityType.TOP_N_RANKING,  # C2
    AmbiguityType.EXISTENCE_NEGATION,  # C3
    AmbiguityType.RELATIVE_TEMPORAL,  # T1
    AmbiguityType.EXTERNAL_KNOWLEDGE,  # K1
    AmbiguityType.CHANNEL_ENCODING,  # I2
    AmbiguityType.CHART_TYPE,  # I3
)

REASONING_TYPE_BY_CODE: dict[str, AmbiguityType] = {
    type_.value: type_ for type_ in REASONING_TYPES
}

SYSTEM_PROMPT = """You are a conservative ambiguity detector for enterprise analytics questions
over a relational database.

You answer one question: does the question, AFTER the enterprise metadata is
applied, still admit more than one operational SQL interpretation that is (a)
consistent with the question text and the schema and (b) returns a different
result set (not a paraphrase)? Only such *persistent* ambiguity is reported.

Rules:
- Do not report underspecification that the metadata pins to a single reading
  (that is a metadata-closable item, not persistent ambiguity).
- Do not report vagueness unless it admits two distinct operationalizations.
- If no defensible second reading can be established, report no ambiguity
  (be conservative).
- Only these ambiguity types are in scope, with their canonical meanings:
  S1 quantifier scope: the scope of a quantifier or negation admits two readings.
  S2 attachment: a modifier can attach to more than one referent.
  R2 join path: the schema admits more than one path between the required tables.
  C1 aggregation/metric: the aggregation or metric to compute is not pinned.
  C2 top-N/ranking: "top"/"best"/"leading" ranking or tie handling is undefined.
  C3 existence/negation: the boundary of a negative or existence filter on a
  join is undefined.
  T1 relative temporal: a relative time reference ("last quarter", "this week")
  has no pinned convention.
  K1 external-knowledge gap: the question assumes external-world knowledge the
  schema does not carry.
  I2 channel/encoding: the output channel or encoding (table vs text, unit,
  currency) is ambiguous.
  I3 chart type: the intended visualization/chart type is ambiguous.
- Do NOT report types outside this list (L2, R1, V1-V3, T2, K2, I1, C4, and the
  U branch are out of scope here).

Answer in JSON only, with this exact shape:
{"verdict": "ambiguous" | "unambiguous", "confidence": <number 0.0-1.0>, "spans":
[{"type": "<code>", "start": <int>, "end": <int>, "reasoning": "<brief why>"}]}
- start/end are half-open character offsets into the question (0-based).
- "spans" must be empty when verdict is "unambiguous".
"""

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _strip_code_fence(content: str) -> str:
    """Strip an optional markdown JSON fence wrapping ``content``."""
    match = _FENCE_RE.search(content)
    return match.group(1).strip() if match else content.strip()


def _clamp_confidence(value: Any) -> float:
    """Clamp a raw confidence signal into [0.0, 1.0], non-numeric to 0.0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return min(1.0, max(0.0, float(value)))


def _parse_judgment(
    content: str,
) -> tuple[AmbiguityVerdict, list[dict[str, Any]], float]:
    """Parse a structured model response into (verdict, raw spans, confidence).

    Raises
    ------
    AmbiguityResolutionError:
        If the content is not a JSON object, the verdict is unknown, an
        ``ambiguous`` verdict carries no spans, or an ``unambiguous`` verdict
        carries spans.
    """
    try:
        payload = json.loads(_strip_code_fence(content))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise AmbiguityResolutionError(
            "reasoning detector: model response is not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise AmbiguityResolutionError(
            "reasoning detector: model response is not a JSON object"
        )
    verdict_raw = payload.get("verdict")
    if verdict_raw == "unambiguous":
        spans_raw = payload.get("spans")
        if spans_raw:
            raise AmbiguityResolutionError(
                "reasoning detector: unambiguous verdict with non-empty spans"
            )
        return AmbiguityVerdict.UNAMBIGUOUS, [], 0.0
    if verdict_raw != "ambiguous":
        raise AmbiguityResolutionError(
            f"reasoning detector: unknown verdict {verdict_raw!r}"
        )
    spans_raw = payload.get("spans")
    if not isinstance(spans_raw, list) or not spans_raw:
        raise AmbiguityResolutionError(
            "reasoning detector: ambiguous verdict without spans"
        )
    return (
        AmbiguityVerdict.AMBIGUOUS,
        [span for span in spans_raw if isinstance(span, dict)],
        _clamp_confidence(payload.get("confidence")),
    )


def _parse_spans(
    content: str, question: str
) -> tuple[AmbiguityVerdict, list[AmbiguitySpan], float]:
    """Parse and validate the model's spans against the question text.

    Out-of-scope types and spans with invalid offsets are dropped; if nothing
    valid survives the analysis degrades to ``unambiguous`` (conservative
    non-detection).
    """
    verdict, raw_spans, overall = _parse_judgment(content)
    if verdict == AmbiguityVerdict.UNAMBIGUOUS:
        return verdict, [], 0.0
    spans: list[AmbiguitySpan] = []
    for raw in raw_spans:
        code = raw.get("type")
        if not isinstance(code, str):
            continue
        span_type = REASONING_TYPE_BY_CODE.get(code)
        if span_type is None:
            continue
        start = raw.get("start")
        end = raw.get("end")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or isinstance(start, bool)
            or isinstance(end, bool)
        ):
            continue
        if start < 0 or end <= start or end > len(question):
            continue
        conf_raw = raw.get("confidence")
        if isinstance(conf_raw, (int, float)) and not isinstance(conf_raw, bool):
            span_confidence = _clamp_confidence(conf_raw)
        else:
            span_confidence = overall
        span = AmbiguitySpan(
            type=span_type,
            start=start,
            end=end,
            snippet=question[start:end],
            confidence=span_confidence,
        )
        if any(
            existing.type == span.type
            and existing.start == span.start
            and existing.end == span.end
            for existing in spans
        ):
            continue
        spans.append(span)
    if not spans:
        return AmbiguityVerdict.UNAMBIGUOUS, [], 0.0
    return AmbiguityVerdict.AMBIGUOUS, spans, overall


def _column_label(column: ColumnSchema) -> str:
    """Render one column with its key and foreign-key annotations."""
    label = column.name
    if column.primary_key:
        label += " PK"
    if column.foreign_key is not None:
        fk = column.foreign_key
        label += f" FK->{fk.references_table}.{fk.references_column}"
    return label


def _schema_summary(schema: DatabaseSchema) -> str:
    """Render a compact, dataset-independent summary of ``schema``."""
    lines = [f"Schema (database id: {schema.database_id}):"]
    for table in schema.tables:
        columns = ", ".join(_column_label(column) for column in table.columns)
        lines.append(f"TABLE {table.name} ({columns})")
    return "\n".join(lines)


def _enrichment_summary(schema: EnrichedSchema) -> str:
    """Render the enrichment (business terms, units, values, relationships)."""
    lines = ["Enterprise metadata:"]
    for table_name, description in schema.table_descriptions.items():
        lines.append(f"- table {table_name}: {description}")
    for table_name, columns in schema.column_semantics.items():
        for column_name, semantics in columns.items():
            parts: list[str] = []
            if semantics.business_term:
                parts.append(f'business term "{semantics.business_term}"')
            if semantics.synonyms:
                joined = ", ".join(f'"{synonym}"' for synonym in semantics.synonyms)
                parts.append(f"synonyms {joined}")
            if semantics.unit:
                parts.append(f'unit "{semantics.unit}"')
            if semantics.domain_values:
                joined = ", ".join(f'"{value}"' for value in semantics.domain_values)
                parts.append(f"domain values {joined}")
            if semantics.description:
                parts.append(f'description "{semantics.description}"')
            if parts:
                lines.append(f"- {table_name}.{column_name}: " + "; ".join(parts))
    for rel in schema.relationships:
        lines.append(
            f"- relationship {rel.from_table}.{rel.from_column} -> "
            f"{rel.to_table}.{rel.to_column} ({rel.kind})"
        )
    return "\n".join(lines)


def _user_prompt(question: str, schema: DatabaseSchema) -> str:
    """Render the question plus the schema and, when present, enrichment."""
    parts = [f"Question: {question}", _schema_summary(schema)]
    if isinstance(schema, EnrichedSchema) and schema.has_enrichment:
        parts.append(_enrichment_summary(schema))
    return "\n\n".join(parts)


class ReasoningBasedDetector:
    """Model-based reasoning ambiguity detector (docs/14 §4B, M1.5 slice 2.9).

    Establishes the persistent-ambiguity band: spans where at least two
    schema-consistent readings with different results survive after the
    enterprise metadata is applied (docs/13 §4, Step 3). The judgment is a
    defeasible claim over the question against the schema, obtained through
    the existing ``LLMBackend`` protocol rather than a lookup; where no
    defensible second reading can be established the detector stays silent.

    Parameters
    ----------
    schema:
        The resolved schema for the database being analyzed. An
        ``EnrichedSchema`` with content contributes its enrichment to the
        judgment context so the model can apply the metadata-persistence rule.
    backend:
        The ``LLMBackend`` used for the judgment. Backends never hold business
        logic; the detector builds the dataset-independent prompt and strictly
        parses the structured response.
    """

    def __init__(self, schema: DatabaseSchema, backend: LLMBackend) -> None:
        self._schema = schema
        self._backend = backend

    def analyze(
        self, task: TaskEnvelope, context: RuntimeContext
    ) -> AmbiguityAnalysis:
        """Detect persistent ambiguity in the task question.

        Parameters
        ----------
        task:
            The task whose payload carries the question to analyze.
        context:
            Runtime state; the run's ``BudgetLedger`` is read from
            ``context.state[BUDGET_LEDGER_KEY]`` and charged for the call and
            its tokens.

        Returns
        -------
        AmbiguityAnalysis:
            ``ambiguous`` with the validated persistent spans when at least
            one survives parsing, otherwise ``unambiguous``.

        Raises
        ------
        AmbiguityResolutionError:
            If the payload carries no question, or the model response is not a
            well-formed JSON judgment.
        PipelineError:
            If no budget ledger is present, i.e. the detector ran outside a
            pipeline (``eaa.core.pipeline.get_budget_ledger``).
        """
        question = getattr(task.payload, "question", None)
        if not isinstance(question, str) or not question.strip():
            raise AmbiguityResolutionError(
                "reasoning detection requires a question in the task payload"
            )
        messages = [
            Message(role="system", content=SYSTEM_PROMPT),
            Message(role="user", content=_user_prompt(question, self._schema)),
        ]
        ledger = get_budget_ledger(context)
        completion = self._backend.complete(messages)
        ledger.spend_llm_calls(1)
        total_tokens = completion.usage.total_tokens
        if total_tokens is not None:
            ledger.spend_llm_tokens(total_tokens)
        verdict, spans, confidence = _parse_spans(
            completion.message.content, question
        )
        if verdict == AmbiguityVerdict.UNAMBIGUOUS:
            return AmbiguityAnalysis(
                database_id=self._schema.database_id,
                verdict=AmbiguityVerdict.UNAMBIGUOUS,
                confidence=0.0,
            )
        detected_types: list[AmbiguityType] = []
        for span in spans:
            if span.type not in detected_types:
                detected_types.append(span.type)
        return AmbiguityAnalysis(
            database_id=self._schema.database_id,
            verdict=AmbiguityVerdict.AMBIGUOUS,
            detected_types=detected_types,
            ambiguous_spans=spans,
            confidence=confidence,
        )

    def resolve(
        self,
        analysis: AmbiguityAnalysis,
        task: TaskEnvelope,
        context: RuntimeContext,
    ) -> ClarifiedQuestion:
        """Not implemented: resolution is a later M1.5 slice.

        The detector slice establishes detection evidence only (docs/14 §5);
        turning it into a clarified question is the resolver's job.
        """
        raise NotImplementedError(
            "resolution is out of scope for the reasoning-based detector "
            "slice; ReasoningBasedDetector implements detection (analyze) only"
        )


__all__ = [
    "REASONING_TYPES",
    "ReasoningBasedDetector",
    "SYSTEM_PROMPT",
]
