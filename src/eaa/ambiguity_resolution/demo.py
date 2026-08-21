"""Paper 1 live demo: analyze an arbitrary question with the frozen detectors.

This module is the interactive front-end of the completed/frozen Paper 1
work (docs/20). It composes the existing, frozen detection machinery — the
deterministic ``SignalAnnotator`` over the gold-free candidate signals
(``candidates.signals.evaluate_question``) and, when a real LLM backend is
provided, the ``ReasoningBasedDetector`` — behind a small, dataset-independent
API and renders the result as a human-readable report.

Research boundaries (docs/20, docs/15 §7):

- The demo is NOT a benchmark evaluation. It reads no gold, writes no labels,
  and touches no frozen artifact (the batch lock SHA ``e215880a...`` must stay
  unchanged). No enrichment and no annotation are fabricated.
- ``analyze_question`` is the deterministic pipeline interface: it always runs
  the baseline and returns the standard ``AmbiguityAnalysis`` contract.
  ``optional_metadata`` is accepted for interface compatibility but is not used
  by the deterministic baseline (metadata-grounded detection is deferred,
  ADR-015, matching the frozen batch).
- The reasoning leg runs ``ReasoningBasedDetector`` only when a real
  ``LLMBackend`` is injected; without one the demo reports the leg as
  unavailable (``EchoBackend`` is test-only and is never used for demo
  results). The metadata leg is reported N/A unless a content-bearing
  ``EnrichedSchema`` is supplied.
- The baseline is not confidence-bearing (docs/15 §4.4 N/A); every displayed
  confidence is a clearly-labelled heuristic, never a calibrated number.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from eaa.core.contracts.ambiguity import (
    AmbiguityAnalysis,
    AmbiguitySpan,
    AmbiguityType,
    AmbiguityVerdict,
)
from eaa.core.contracts.errors import PipelineError
from eaa.core.contracts.runtime import Budget, RuntimeContext, SessionState
from eaa.core.contracts.schema import DatabaseSchema, EnrichedSchema
from eaa.core.contracts.task import TaskEnvelope
from eaa.core.pipeline import BUDGET_LEDGER_KEY, BudgetLedger
from eaa.core.registry import envelope_for
from eaa.llm import LLMError

from .annotations.ai_annotation import METADATA_SIGNALS, SIGNAL_TO_CODE, SignalAnnotator
from .candidates.signals import SIGNALS_BY_ID, evaluate_question
from .detectors import ReasoningBasedDetector
from .errors import AmbiguityResolutionError
from .evaluation.metrics import family_of

DEMO_VERSION = "paper1-demo-v1"

#: Human-readable family names (docs/13 §2 families), display only.
FAMILY_NAMES: dict[str, str] = {
    "L": "Lexical",
    "S": "Structural",
    "R": "Schema reference",
    "V": "Semantic value",
    "C": "Computational",
    "T": "Temporal",
    "K": "Knowledge",
    "I": "Intent",
    "U": "Unanswerability",
}

BASELINE_SOURCE = "deterministic SignalAnnotator"
REASONING_SOURCE = "ReasoningBasedDetector"

#: Heuristic display confidence for deterministic baseline spans. The baseline
#: is not confidence-bearing (docs/15 §4.4 N/A); this value is a labelled
#: display constant, never a calibrated probability.
BASELINE_DISPLAY_CONFIDENCE = 0.7

REASONING_UNAVAILABLE = (
    "unavailable - no real LLM backend configured (EchoBackend is test-only "
    "and is never used for demo results)"
)

METADATA_STATUS_BASE = (
    "N/A - no legitimate enrichment provided; metadata-grounded detection is "
    "deferred (ADR-015), matching the frozen batch"
)

DEMO_DISCLAIMER = (
    "Research demonstration only - not a benchmark evaluation. Demo output is "
    "computed by the frozen Paper 1 detectors; it is not research evidence, "
    "contains no gold, and neither enrichment nor human annotation is "
    "fabricated."
)

#: Reverse of ``SIGNAL_TO_CODE`` (1:1 — each signal maps to a distinct code).
CODE_TO_SIGNAL: dict[str, str] = {code: signal for signal, code in SIGNAL_TO_CODE.items()}

_DETECTOR_MODES = ("baseline", "reasoning", "combined")


@dataclass(frozen=True)
class DemoSpan:
    """A detected ambiguity span with the display fields for the report."""

    text: str
    start: int
    end: int
    code: str
    family: str
    family_name: str
    confidence: float
    metadata_resolution: bool
    clarification_required: bool
    assumption_risk: str
    resolution_channel: str
    source: str
    explanation: str


@dataclass(frozen=True)
class DemoSignal:
    """One fired screening signal (a hint, never a label)."""

    id: str
    name: str
    families: tuple[str, ...]
    evidence: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class DemoAnalysis:
    """The human-readable demo result for one question."""

    question: str
    database_id: str
    verdict: AmbiguityVerdict
    ambiguous: bool
    detector_mode: str
    detector_source: str
    spans: tuple[DemoSpan, ...]
    signals: tuple[DemoSignal, ...]
    confidence: float
    interpretations: tuple[str, ...]
    llm_backend_status: str
    metadata_status: str
    clarification_required: bool
    warnings: tuple[str, ...]


def analyze_question(
    question: str,
    database_schema: DatabaseSchema,
    optional_metadata: DatabaseSchema | None = None,
) -> AmbiguityAnalysis:
    """Return the deterministic baseline ambiguity analysis of ``question``.

    This is the clean, pipeline-facing interface the thesis stages will consume
    (``analyze_question(question, database_schema, optional_metadata) ->
    AmbiguityAnalysis``). It always runs the deterministic baseline
    (``SignalAnnotator`` over the candidate signals) and returns the standard
    contract; spans carry no confidence claim (``confidence=0.0``). It reads
    only the question text and ``database_schema`` — never gold (ADR-009).

    ``optional_metadata`` is accepted for interface compatibility but is not
    used by the deterministic baseline (metadata-grounded detection is
    deferred, ADR-015). For the reasoning leg and the rich demo report use
    :func:`analyze_demo`.
    """
    if not question.strip():
        raise ValueError("question must not be empty")
    hits = evaluate_question(question, database_schema)
    annotator = SignalAnnotator()
    record = annotator.annotate(
        question_id="demo-question",
        question_text=question,
        database_id=database_schema.database_id,
        signals=(asdict(hit) for hit in hits),
    )
    spans = [
        AmbiguitySpan(
            type=span.ambiguity_type,
            start=span.start,
            end=span.end,
            snippet=question[span.start : span.end],
            confidence=0.0,
        )
        for span in record.question.spans
    ]
    if not spans:
        return AmbiguityAnalysis(
            database_id=database_schema.database_id,
            verdict=AmbiguityVerdict.UNAMBIGUOUS,
            confidence=0.0,
        )
    detected_types: list[AmbiguityType] = []
    for span in spans:
        if span.type not in detected_types:
            detected_types.append(span.type)
    return AmbiguityAnalysis(
        database_id=database_schema.database_id,
        verdict=AmbiguityVerdict.AMBIGUOUS,
        detected_types=detected_types,
        ambiguous_spans=spans,
        confidence=0.0,
    )


def analyze_demo(
    question: str,
    database_schema: DatabaseSchema,
    optional_metadata: DatabaseSchema | None = None,
    *,
    mode: str = "baseline",
    llm_backend: Any | None = None,
    session_id: str | None = None,
) -> DemoAnalysis:
    """Run the interactive demo analysis for ``question`` against ``schema``.

    ``mode`` selects the enabled legs:

    - ``baseline`` (default) — deterministic ``SignalAnnotator`` only.
    - ``reasoning`` — ``ReasoningBasedDetector`` via ``llm_backend``; when no
      real backend is injected the demo reports the leg as unavailable and
      falls back to the baseline with an explicit warning (never silently).
    - ``combined`` — baseline plus reasoning (when available), merged with
      conflict reporting.

    The metadata leg is always reported N/A unless ``optional_metadata`` is a
    content-bearing ``EnrichedSchema``; no metadata-grounded prediction is
    fabricated (ADR-015). The demo never reads gold and writes no labels.
    """
    mode = mode.lower()
    if mode not in _DETECTOR_MODES:
        raise ValueError(
            f"unknown demo mode {mode!r}; choose from {', '.join(_DETECTOR_MODES)} "
            "(the metadata leg is N/A — no legitimate enrichment, ADR-015)"
        )
    if not question.strip():
        raise ValueError("question must not be empty")

    analysis = analyze_question(question, database_schema, optional_metadata)
    hits = evaluate_question(question, database_schema)

    baseline_spans = [_demo_span(span, BASELINE_SOURCE) for span in analysis.ambiguous_spans]
    reasoning_spans: list[DemoSpan] = []
    warnings: list[str] = []
    detector_sources = [BASELINE_SOURCE]
    llm_status = REASONING_UNAVAILABLE
    if mode in ("reasoning", "combined"):
        if llm_backend is None:
            warnings.append(REASONING_UNAVAILABLE)
        else:
            try:
                reasoning = _reasoning_analysis(
                    question, database_schema, llm_backend, session_id=session_id
                )
            except (AmbiguityResolutionError, PipelineError, LLMError) as exc:
                llm_status = f"failed — {exc}"
                warnings.append(
                    "reasoning leg failed and was excluded from the demo result: "
                    f"{exc}"
                )
            else:
                llm_status = "configured — real LLM backend provided by the caller"
                detector_sources.append(REASONING_SOURCE)
                reasoning_spans = [
                    _demo_span(span, REASONING_SOURCE)
                    for span in reasoning.ambiguous_spans
                ]

    if mode == "baseline":
        spans = baseline_spans
        mode_label = "baseline"
    elif mode == "reasoning" and reasoning_spans:
        spans = reasoning_spans
        mode_label = "reasoning"
    elif mode == "combined":
        spans, conflicts = _merge_span_views(baseline_spans, reasoning_spans)
        warnings.extend(conflicts)
        if conflicts:
            warnings.append(
                "combined mode: overlapping spans with different codes across "
                "detectors are reported as conflicts, never silently resolved"
            )
        mode_label = (
            "combined (baseline + reasoning)" if reasoning_spans else "combined (baseline only)"
        )
    else:
        spans = baseline_spans
        mode_label = "baseline (reasoning requested but unavailable)"

    strict_codes = {span.code for span in baseline_spans}
    produced_signals = {sig for code, sig in CODE_TO_SIGNAL.items() if code in strict_codes}
    signals = tuple(
        DemoSignal(
            id=hit.signal,
            name=hit.name,
            families=SIGNALS_BY_ID[hit.signal].families,
            evidence=hit.evidence,
            note=_signal_note(hit.signal, produced_signals),
        )
        for hit in hits
    )

    verdict = AmbiguityVerdict.AMBIGUOUS if spans else AmbiguityVerdict.UNAMBIGUOUS
    return DemoAnalysis(
        question=question,
        database_id=database_schema.database_id,
        verdict=verdict,
        ambiguous=verdict == AmbiguityVerdict.AMBIGUOUS,
        detector_mode=mode_label,
        detector_source=" + ".join(detector_sources),
        spans=tuple(spans),
        signals=signals,
        confidence=max((span.confidence for span in spans), default=0.0),
        interpretations=(),
        llm_backend_status=llm_status,
        metadata_status=_metadata_status(optional_metadata),
        clarification_required=any(span.clarification_required for span in spans),
        warnings=tuple(warnings),
    )


def render_analysis(
    analysis: DemoAnalysis, *, include_disclaimer: bool = True
) -> str:
    """Render a ``DemoAnalysis`` as a sectioned, human-readable report."""
    verdict = "AMBIGUOUS" if analysis.ambiguous else "NOT AMBIGUOUS"
    lines = [
        "=" * 72,
        "PAPER 1 DEMO - AMBIGUITY ANALYSIS",
        "=" * 72,
        f"question : {analysis.question}",
        f"database : {analysis.database_id}",
        f"mode     : {analysis.detector_mode}",
        f"detector : {analysis.detector_source}",
        f"verdict  : {verdict} ({analysis.verdict.value})",
        f"confidence: {analysis.confidence:.2f} (heuristic display value; the "
        "deterministic baseline is not confidence-bearing)",
        "",
        "DETECTED AMBIGUITY SPANS",
        "-" * 72,
    ]
    if not analysis.spans:
        lines.append("(none detected by the enabled detectors)")
    for span in analysis.spans:
        confidence_label = (
            "heuristic, uncalibrated"
            if span.source == BASELINE_SOURCE
            else "model signal, uncalibrated"
        )
        lines.append(
            f"- [{span.code}] family {span.family} ({span.family_name}) "
            f"@{span.start}-{span.end}"
        )
        lines.append(f"    text       : {span.text!r}")
        lines.append(f"    confidence : {span.confidence:.2f} ({confidence_label})")
        lines.append(
            f"    metadata resolution: "
            f"{'applied' if span.metadata_resolution else 'not applied'} | "
            f"clarification required: {'yes' if span.clarification_required else 'no'} | "
            f"assumption risk: {span.assumption_risk}"
        )
        lines.append(
            f"    resolution channel: {span.resolution_channel} | source: {span.source}"
        )
        lines.append(f"    explanation : {span.explanation}")
    lines.extend(
        [
            "",
            "SCREENING SIGNALS (HINTS, NOT LABELS)",
            "-" * 72,
        ]
    )
    if not analysis.signals:
        lines.append("(no signals fired)")
    for signal in analysis.signals:
        families = ", ".join(signal.families)
        evidence = ", ".join(repr(item) for item in signal.evidence)
        lines.append(f"- {signal.id} {signal.name} (families {families}) evidence={evidence}")
        lines.append(f"    {signal.note}")
    lines.extend(["", "STATUS", "-" * 72])
    lines.append(f"reasoning/LLM : {analysis.llm_backend_status}")
    lines.append(f"metadata      : {analysis.metadata_status}")
    lines.append(
        "clarification : required - a downstream resolver should ask before "
        "generating SQL"
        if analysis.clarification_required
        else "clarification : not required"
    )
    lines.extend(["", "POSSIBLE INTERPRETATIONS", "-" * 72])
    if analysis.interpretations:
        lines.extend(f"- {text}" for text in analysis.interpretations)
    else:
        lines.append(
            "None produced. The deterministic baseline authors no SQL readings; "
            "interpretations require a reasoning judgment or a human annotator, "
            "neither of which is available in this demo."
        )
    lines.extend(["", "RECOMMENDATION", "-" * 72])
    lines.append(
        "Feed the AmbiguityAnalysis contract to the Paper 1 resolver for "
        "clarification or metadata lookup before SQL generation (thesis "
        "integration point). Demo output is not a benchmark result."
    )
    if analysis.warnings:
        lines.extend(["", "WARNINGS", "-" * 72])
        lines.extend(f"- {warning}" for warning in analysis.warnings)
    if include_disclaimer:
        lines.extend(["", "DISCLAIMER", "-" * 72, DEMO_DISCLAIMER])
    return "\n".join(lines)


def _demo_span(span: AmbiguitySpan, source: str) -> DemoSpan:
    """Map a contract span to its display view."""
    code = span.type.value
    family = family_of(code)
    is_baseline = source == BASELINE_SOURCE
    return DemoSpan(
        text=span.snippet or "",
        start=span.start,
        end=span.end,
        code=code,
        family=family,
        family_name=FAMILY_NAMES.get(family, family),
        confidence=BASELINE_DISPLAY_CONFIDENCE if is_baseline else span.confidence,
        metadata_resolution=False,
        clarification_required=True,
        assumption_risk="low" if is_baseline else "not recorded",
        resolution_channel="clarification",
        source=source,
        explanation=_explain_span(span, source),
    )


def _explain_span(span: AmbiguitySpan, source: str) -> str:
    """One-sentence explanation of a span, from the fired signal."""
    signal_id = CODE_TO_SIGNAL.get(span.type.value)
    signal = SIGNALS_BY_ID.get(signal_id) if signal_id else None
    base = (
        signal.description if signal is not None else f"{span.type.value} ambiguity span"
    )
    if source == BASELINE_SOURCE:
        return (
            f"{base} Detected by the deterministic SignalAnnotator "
            f"(signal {signal_id!r}, evidence {span.snippet!r})."
        )
    return (
        f"{base} Model-based judgment from the ReasoningBasedDetector over the "
        "question against the schema."
    )


def _signal_note(signal_id: str, produced_signals: set[str]) -> str:
    """Explain what one fired signal means in the demo result."""
    if signal_id in METADATA_SIGNALS:
        return (
            "screening hint only - confirming this family is metadata-grounded "
            "and requires legitimate enrichment; metadata-grounded detection is "
            "N/A here (ADR-015)"
        )
    if signal_id in produced_signals:
        return "hint backed by a strict deterministic baseline span (SignalAnnotator)"
    return "hint only — no strict baseline span; not a confirmed ambiguity"


def _metadata_status(optional_metadata: DatabaseSchema | None) -> str:
    """Report the metadata leg status from the supplied schema object."""
    if isinstance(optional_metadata, EnrichedSchema) and optional_metadata.has_enrichment:
        return (
            "present (EnrichedSchema with content) - metadata-grounded "
            "detection is deferred in the demo (ADR-015), matching the frozen "
            "batch; enrichment is not used"
        )
    return METADATA_STATUS_BASE


def _reasoning_analysis(
    question: str,
    schema: DatabaseSchema,
    backend: Any,
    *,
    session_id: str | None,
) -> AmbiguityAnalysis:
    """Run the frozen ``ReasoningBasedDetector`` for one question."""
    context = RuntimeContext(
        session=SessionState(session_id=session_id or "paper1-demo"),
        budget=Budget(),
    )
    ledger = BudgetLedger(context.budget)
    context = context.model_copy(update={"state": {BUDGET_LEDGER_KEY: ledger}})
    task = envelope_for(
        TaskEnvelope,
        "nl2sql",
        {
            "header": {
                "task_id": "paper1-demo-reasoning",
                "question": question,
                "dataset_id": schema.database_id,
                "dialect": schema.dialect or "mysql",
            },
            "payload": {
                "question": question,
                "database_id": schema.database_id,
                "schema_id": None,
                "allowed_tables": None,
            },
        },
    )
    return ReasoningBasedDetector(schema=schema, backend=backend).analyze(task, context)


def _merge_span_views(
    primary: Sequence[DemoSpan], extra: Sequence[DemoSpan]
) -> tuple[list[DemoSpan], list[str]]:
    """Union spans by (code, start, end); report cross-detector conflicts."""
    merged = list(primary)
    seen = {(span.code, span.start, span.end) for span in merged}
    conflicts: list[str] = []
    for span in extra:
        for other in merged:
            if other.code != span.code and _overlaps(
                span.start, span.end, other.start, other.end
            ):
                conflicts.append(
                    f"combined mode: {span.code}@{span.start}-{span.end} "
                    f"({span.source}) overlaps {other.code}@{other.start}-{other.end} "
                    f"({other.source})"
                )
        key = (span.code, span.start, span.end)
        if key not in seen:
            seen.add(key)
            merged.append(span)
    return merged, conflicts


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Whether two half-open character intervals overlap (IoU > 0)."""
    return a_start < b_end and b_start < a_end


__all__ = [
    "BASELINE_DISPLAY_CONFIDENCE",
    "BASELINE_SOURCE",
    "DEMO_DISCLAIMER",
    "DEMO_VERSION",
    "FAMILY_NAMES",
    "METADATA_STATUS_BASE",
    "REASONING_SOURCE",
    "REASONING_UNAVAILABLE",
    "DemoAnalysis",
    "DemoSignal",
    "DemoSpan",
    "analyze_demo",
    "analyze_question",
    "render_analysis",
]
