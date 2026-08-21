"""AI-annotation machinery for the batch-1 run (docs/13 §7, docs/19).

The annotation protocol requires two independent annotators, agreement
statistics, and adjudication (docs/13 §7). In this environment no human
annotators or external LLM API exist, so the run records **AI-generated
annotations**: Annotator A is a deterministic, rule-based ``SignalAnnotator``
(an independent mechanism derived from the gold-free candidate signals); the
judgment passes (Annotator B and the adjudicator) are performed by the
executing research model and recorded as data. Provenance marks every record
``ai-annotation`` and never claims human authorship.

This module provides only the *machinery*:

- exact character-offset resolution for hand-authored span phrases;
- building and validating ``annotation-schema-v1`` records/JSON from simple
  span specs;
- the deterministic ``SignalAnnotator`` (Annotator A);
- Cohen's κ agreement between two annotators over the protocol's three
  agreement dimensions (span presence per type, answerability, channel).

It never reads gold SQL, gold tables, join keys, or column mappings
(ADR-009): span phrases and SQL readings are supplied by the annotating
judge from the question text and the ``DatabaseSchema`` only.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Literal, cast

from eaa.core.contracts.ambiguity import AmbiguityType

from .models import (
    AnnotatedQuestion,
    AnnotationRecord,
    AnnotationSpan,
    Answerability,
    AnswerabilityLabel,
    AssumptionRisk,
    Interpretation,
    ResolutionChannel,
)

#: Per-signal code Annotator A derives for each fired signal (families the
#: reasoning detector owns; metadata signals fire no strict span for A).
SIGNAL_TO_TYPE: dict[str, AmbiguityType] = {
    "s1": AmbiguityType.QUANTIFIER_SCOPE,  # S1
    "s2": AmbiguityType.ATTACHMENT,  # S2
    "r2": AmbiguityType.JOIN_PATH,  # R2
    "c1": AmbiguityType.AGGREGATION_METRIC,  # C1
    "c2": AmbiguityType.TOP_N_RANKING,  # C2
    "c3": AmbiguityType.EXISTENCE_NEGATION,  # C3
    "t1": AmbiguityType.RELATIVE_TEMPORAL,  # T1
    "k1": AmbiguityType.EXTERNAL_KNOWLEDGE,  # K1
    "i2": AmbiguityType.CHANNEL_ENCODING,  # I2
    "i3": AmbiguityType.CHART_TYPE,  # I3
}

#: Signal -> code used for A's classification agreement comparison.
SIGNAL_TO_CODE: dict[str, str] = {key: value.value for key, value in SIGNAL_TO_TYPE.items()}

#: Signals that only fire for metadata-grounded types; Annotator A (which
#: owns only the reasoning codes) records no strict span for them.
METADATA_SIGNALS: frozenset[str] = frozenset({"r1", "v1", "v2", "v3", "t2", "k2"})


def find_phrase_offsets(text: str, phrase: str) -> tuple[int, int] | None:
    """Return the half-open offsets of the first case-insensitive occurrence.

    ``start``/``end`` are Python string indices (UTF-16 code units), matching
    the ``annotation-schema-v1`` convention (docs/13 §5). ``None`` when the
    phrase does not occur.
    """
    match = re.search(re.escape(phrase), text, flags=re.IGNORECASE)
    if match is None:
        return None
    return match.start(), match.end()


def _to_span(spec: Mapping[str, object], question_text: str, question_id: str) -> AnnotationSpan:
    """Turn one span spec into a validated ``AnnotationSpan``.

    ``spec`` must carry ``type`` (code or ``AmbiguityType``), ``phrase``
    (exact question substring), and the label flags; offsets are derived from
    ``phrase`` so hand-authored content cannot drift from the text.
    """
    raw_type = spec["type"]
    ambiguity_type = (
        raw_type if isinstance(raw_type, AmbiguityType) else AmbiguityType(str(raw_type))
    )
    phrase = str(spec["phrase"])
    offsets = find_phrase_offsets(question_text, phrase)
    if offsets is None:
        raise ValueError(
            f"{question_id}: span phrase {phrase!r} not found in question text"
        )
    start, end = offsets
    return AnnotationSpan(
        span_id=str(spec.get("span_id", f"sp{start}")),
        text=question_text[start:end],
        start=start,
        end=end,
        ambiguity_type=ambiguity_type,
        metadata_resolution=bool(spec.get("metadata_resolution", False)),
        clarification_required=bool(spec.get("clarification_required", True)),
        assumption_risk=AssumptionRisk(str(spec.get("assumption_risk", "low"))),
        resolution_channel=ResolutionChannel(str(spec.get("resolution_channel", "clarification"))),
    )


def build_record(
    *,
    question_id: str,
    question_text: str,
    database_id: str,
    answerability: str = "answerable",
    confidence: float = 1.0,
    spans: Sequence[Mapping[str, object]] = (),
    readings: Mapping[str, Mapping[str, str]] | None = None,
    notes: str | None = None,
) -> AnnotationRecord:
    """Build a validated ``AnnotationRecord`` from span specs and readings.

    ``readings`` maps ``sql_reading_A``/``sql_reading_B`` to
    ``{"sql": ..., "note": ...}``. The result is validated by the frozen
    loader contract via ``AnnotationDatasetLoader``-style construction, so
    malformed authoring fails loudly.
    """
    question = AnnotatedQuestion(
        question_id=question_id,
        question_text=question_text,
        database_id=database_id,
        answerability=Answerability(
            label=AnswerabilityLabel(answerability), confidence=confidence
        ),
        spans=[_to_span(spec, question_text, question_id) for spec in spans],
    )
    interpretations = None
    if readings:
        interpretations = cast(
            dict[Literal["sql_reading_A", "sql_reading_B"], Interpretation],
            {
                key: Interpretation(sql=value["sql"], note=value.get("note"))
                for key, value in readings.items()
            },
        )
    return AnnotationRecord(
        schema_version="annotation-schema-v1",
        question=question,
        interpretations=interpretations,
        notes=notes,
    )


class SignalAnnotator:
    """Deterministic rule-based Annotator A (docs/19 §5.1 signals -> spans).

    The signal catalog maps each fired signal to the ambiguity code it hints
    at; Annotator A records one strict span per fired reasoning signal whose
    evidence phrase occurs in the question. It writes no interpretations (a
    rule cannot author SQL), marks every question answerable, and never reads
    gold. Its labels are a mechanism-independent view used for agreement and
    as a secondary detector reference.
    """

    name = "signal-annotator-v1"

    def annotate(
        self,
        *,
        question_id: str,
        question_text: str,
        database_id: str,
        signals: Iterable[Mapping[str, object]],
    ) -> AnnotationRecord:
        """Produce Annotator A's label for one question."""
        spans: list[AnnotationSpan] = []
        seen: set[tuple[str, str, int, int]] = set()
        for hit in signals:
            signal = str(hit.get("signal"))
            code = SIGNAL_TO_CODE.get(signal)
            if code is None:
                continue
            evidence = hit.get("evidence")
            items: Iterable[object] = (
                evidence if isinstance(evidence, Iterable) else ()
            )
            phrase = next(
                (str(item) for item in items if item),
                None,
            )
            if phrase is None:
                continue
            offsets = find_phrase_offsets(question_text, phrase)
            if offsets is None:
                continue
            start, end = offsets
            if (code, phrase, start, end) in seen:
                continue
            seen.add((code, phrase, start, end))
            spans.append(
                AnnotationSpan(
                    span_id=f"a-{signal}-{start}",
                    text=question_text[start:end],
                    start=start,
                    end=end,
                    ambiguity_type=SIGNAL_TO_TYPE[signal],
                    metadata_resolution=False,
                    clarification_required=True,
                    assumption_risk=AssumptionRisk.LOW,
                    resolution_channel=ResolutionChannel.CLARIFICATION,
                )
            )
        question = AnnotatedQuestion(
            question_id=question_id,
            question_text=question_text,
            database_id=database_id,
            answerability=Answerability(
                label=AnswerabilityLabel.ANSWERABLE, confidence=1.0
            ),
            spans=spans,
        )
        return AnnotationRecord(
            schema_version="annotation-schema-v1",
            question=question,
            interpretations=None,
            notes="annotator-a: deterministic signal-based annotation (no SQL readings)",
        )


def span_sets(records: Iterable[AnnotationRecord]) -> dict[str, list[AnnotationSpan]]:
    """Index records by question id (spans only)."""
    return {record.question.question_id: record.question.spans for record in records}


def agreement_kappa(
    a: dict[str, list[AnnotationSpan]],
    b: dict[str, list[AnnotationSpan]],
    *,
    dimension: str = "span_presence_per_type",
) -> float:
    """Cohen's κ between two annotators over one protocol dimension.

    ``span_presence_per_type``: for every (question, code) pair, whether each
    annotator recorded at least one span of that code. ``answerability`` and
    ``channel`` compare the corresponding labels. Returns ``1.0`` when the
    observed agreement is perfect and expected agreement is degenerate.
    """
    if dimension == "span_presence_per_type":
        question_ids = sorted(set(a) | set(b))
        codes = sorted(
            {
                span.ambiguity_type.value
                for spans in list(a.values()) + list(b.values())
                for span in spans
            }
        )
        a_binary = {
            (qid, code): any(span.ambiguity_type.value == code for span in a.get(qid, ()))
            for qid in question_ids
            for code in codes
        }
        b_binary = {
            (qid, code): any(span.ambiguity_type.value == code for span in b.get(qid, ()))
            for qid in question_ids
            for code in codes
        }
        pairs = [(a_binary[key], b_binary[key]) for key in a_binary]
    else:
        raise ValueError(f"unknown agreement dimension {dimension!r}")

    return _cohen_kappa(pairs)


def _cohen_kappa(pairs: Sequence[tuple[bool, bool]]) -> float:
    """Cohen's κ over (annotator-a, annotator-b) boolean judgment pairs."""
    if not pairs:
        return 1.0
    table = Counter(pairs)
    n = len(pairs)
    observed = (
        table[(True, True)] + table[(False, False)]
    ) / n
    a_positive = sum(a for a, _ in pairs) / n
    b_positive = sum(b for _, b in pairs) / n
    expected = a_positive * b_positive + (1 - a_positive) * (1 - b_positive)
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1 - expected)


def kappa_report(
    a: dict[str, list[AnnotationSpan]],
    b: dict[str, list[AnnotationSpan]],
    *,
    per_family: bool = True,
) -> dict[str, float]:
    """Return overall and (optionally) per-family span-presence κ."""
    report: dict[str, float] = {
        "overall_span_presence_per_type": agreement_kappa(a, b)
    }
    if per_family:
        families = sorted(
            {
                span.ambiguity_type.value[0]
                for spans in list(a.values()) + list(b.values())
                for span in spans
            }
        )
        for family in families:
            a_family = {
                qid: [span for span in spans if span.ambiguity_type.value[0] == family]
                for qid, spans in a.items()
            }
            b_family = {
                qid: [span for span in spans if span.ambiguity_type.value[0] == family]
                for qid, spans in b.items()
            }
            report[f"family_{family}"] = agreement_kappa(a_family, b_family)
    return report


__all__ = [
    "METADATA_SIGNALS",
    "SIGNAL_TO_CODE",
    "SIGNAL_TO_TYPE",
    "SignalAnnotator",
    "agreement_kappa",
    "build_record",
    "find_phrase_offsets",
    "kappa_report",
    "span_sets",
]
