"""Metadata-grounded ambiguity detector (docs/14 §4A, M1.5 slice 2.8).

This is the first evidence family of the ambiguity detector: it establishes,
with deterministic lookups, the **metadata-closable band** — spans whose
reading the enterprise enrichment pins to a single interpretation, i.e.
underspecifications rather than strict ambiguities (docs/13 §4, Step 2). It
implements ``AmbiguityResolver.analyze`` (ADR-014) and emits exactly the
seven taxonomy types that enrichment can close: ``SYNONYM_COLLISION`` (L2),
``TABLE_SELECTION`` (R1), ``VALUE_ENTITY_LITERAL`` (V1),
``UNIT_SCALE_CURRENCY`` (V2), ``GRANULARITY`` (V3), ``CALENDAR_FISCAL`` (T2),
and ``BUSINESS_RULE`` (K2). No structural, computational, intent, or
unanswerability detection is implemented here.

The detector reads only the task question (from the ``TaskEnvelope`` payload)
and the injected ``DatabaseSchema`` / ``EnrichedSchema`` (docs/14 §2.1). It
never touches gold SQL, labels, adapter internals, or metadata sidecar files,
and it performs no resolution, clarification, or answerability judgment —
those belong to later slices. Against a plain ``DatabaseSchema`` (no
enrichment) every lookup is empty and the analysis is ``unambiguous``.

Confidence values are fixed, deterministic constants per evidence kind
(metadata-grounded claims are verifiable lookups, so they score high): synonym
match 0.95, table-selection description match 0.90, domain-value literal 0.95,
unit/scale/currency convention 0.90, granularity alias 0.85, fiscal convention
0.90, business-rule definition 0.85. The analysis verdict is
``underdetermined`` when spans are found: the question text underdetermines the
reading and the enrichment closes it (docs/15 §3.1 counts ``underdetermined``
as ambiguity detected); overall confidence is the strongest per-span signal.
"""
from __future__ import annotations

import re

from eaa.core.contracts.ambiguity import (
    AmbiguityAnalysis,
    AmbiguitySpan,
    AmbiguityType,
    AmbiguityVerdict,
    ClarifiedQuestion,
)
from eaa.core.contracts.runtime import RuntimeContext
from eaa.core.contracts.schema import DatabaseSchema
from eaa.core.contracts.task import TaskEnvelope

from ..errors import AmbiguityResolutionError
from .schema_index import SchemaIndex
from .text_matching import (
    find_phrase,
    find_substring,
    normalize_phrase,
    significant_terms,
    singularize,
    split_terms,
)

SYNONYM_MATCH_CONFIDENCE = 0.95
TABLE_SELECTION_CONFIDENCE = 0.90
DOMAIN_VALUE_CONFIDENCE = 0.95
UNIT_CONVENTION_CONFIDENCE = 0.90
GRANULARITY_CONFIDENCE = 0.85
FISCAL_CONVENTION_CONFIDENCE = 0.90
BUSINESS_RULE_CONFIDENCE = 0.85

METADATA_GROUNDED_TYPES: tuple[AmbiguityType, ...] = (
    AmbiguityType.SYNONYM_COLLISION,  # L2
    AmbiguityType.TABLE_SELECTION,  # R1
    AmbiguityType.VALUE_ENTITY_LITERAL,  # V1
    AmbiguityType.UNIT_SCALE_CURRENCY,  # V2
    AmbiguityType.GRANULARITY,  # V3
    AmbiguityType.CALENDAR_FISCAL,  # T2
    AmbiguityType.BUSINESS_RULE,  # K2
)

UNIT_TRIGGER_TOKENS = frozenset(
    {
        "million", "millions", "thousand", "thousands", "billion", "billions",
        "k", "m", "bn", "usd", "dollar", "dollars", "eur", "euro", "euros",
    }
)

BUSINESS_RULE_TRIGGERS = frozenset(
    {
        "active", "current", "valid", "qualified", "regular", "premium",
        "vip", "approved", "enabled", "standard", "open", "closed",
        "cancelled",
    }
)

RULE_DEFINITION_MARKERS = frozenset(
    {
        "means", "defined", "refers to", "within", "last", "days", "months",
        "years", "threshold", "balance", "score", "status",
    }
)


class MetadataGroundedDetector:
    """Deterministic metadata-grounded ambiguity detector.

    Parameters
    ----------
    schema:
        The resolved schema for the database being analyzed. An
        ``EnrichedSchema`` with content enables metadata-grounded lookups; a
        plain ``DatabaseSchema`` yields an ``unambiguous`` analysis.
    """

    def __init__(self, schema: DatabaseSchema) -> None:
        self._schema = schema
        self._index = SchemaIndex(schema)
        self._literal_singular = frozenset(
            singularize(name) for name in self._index.literal_names
        )

    def analyze(
        self, task: TaskEnvelope, context: RuntimeContext
    ) -> AmbiguityAnalysis:
        """Detect metadata-closable ambiguity in the task question.

        Parameters
        ----------
        task:
            The task whose payload carries the question to analyze.
        context:
            Runtime state; the detector is stateless and ignores it.

        Returns
        -------
        AmbiguityAnalysis:
            ``underdetermined`` with the metadata-grounded spans when at least
            one lookup resolves a mention, otherwise ``unambiguous``.

        Raises
        ------
        AmbiguityResolutionError:
            If the task payload carries no question text.
        """
        question = getattr(task.payload, "question", None)
        if not isinstance(question, str) or not question.strip():
            raise AmbiguityResolutionError(
                "metadata-grounded detection requires a question in the task payload"
            )

        if not self._index.has_enrichment:
            return AmbiguityAnalysis(
                database_id=self._schema.database_id,
                verdict=AmbiguityVerdict.UNAMBIGUOUS,
                confidence=0.0,
            )

        spans: list[AmbiguitySpan] = (
            self._detect_synonym_collision(question)
            + self._detect_table_selection(question)
            + self._detect_value_literal(question)
            + self._detect_unit_scale_currency(question)
            + self._detect_granularity(question)
            + self._detect_calendar_fiscal(question)
            + self._detect_business_rule(question)
        )

        if not spans:
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
            verdict=AmbiguityVerdict.UNDERDETERMINED,
            detected_types=detected_types,
            ambiguous_spans=spans,
            confidence=max(span.confidence for span in spans),
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
            "resolution is out of scope for the metadata-grounded detector "
            "slice; MetadataGroundedDetector implements detection (analyze) only"
        )

    def _detect_synonym_collision(self, question: str) -> list[AmbiguitySpan]:
        """L2: a synonym/business term pins exactly one column.

        The span is the surface mention that the enrichment aliases; when the
        alias is ambiguous (more than one column) or literal the rule stays
        silent, leaving persistent ambiguity to the reasoning family.
        """
        spans: list[AmbiguitySpan] = []
        aliases = sorted(
            self._index.column_aliases.items(),
            key=lambda item: len(split_terms(item[0])),
            reverse=True,
        )
        for alias, refs in aliases:
            if len(refs) != 1 or alias in self._index.literal_names:
                continue
            span = find_phrase(question, alias)
            if span is None:
                continue
            start, end = span
            if self._contained(
                spans, AmbiguityType.SYNONYM_COLLISION, start, end
            ):
                continue
            self._add_span(
                spans,
                AmbiguitySpan(
                    type=AmbiguityType.SYNONYM_COLLISION,
                    start=start,
                    end=end,
                    snippet=question[start:end],
                    confidence=SYNONYM_MATCH_CONFIDENCE,
                ),
            )
        return spans

    def _detect_table_selection(self, question: str) -> list[AmbiguitySpan]:
        """R1: a question term appears in exactly one enriched table description.

        A direct table/column reference is skipped; only a mention that the
        enrichment pins to a single table is reported.
        """
        spans: list[AmbiguitySpan] = []
        for term in significant_terms(question):
            key = singularize(term.text.lower())
            if key in self._literal_singular:
                continue
            matching = [
                name
                for name, terms in self._index.table_description_terms.items()
                if key in terms
            ]
            if len(matching) != 1:
                continue
            if self._contained(
                spans, AmbiguityType.TABLE_SELECTION, term.start, term.end
            ):
                continue
            self._add_span(
                spans,
                AmbiguitySpan(
                    type=AmbiguityType.TABLE_SELECTION,
                    start=term.start,
                    end=term.end,
                    snippet=term.text,
                    confidence=TABLE_SELECTION_CONFIDENCE,
                ),
            )
        return spans

    def _detect_value_literal(self, question: str) -> list[AmbiguitySpan]:
        """V1: a literal in the question matches one column's domain value."""
        spans: list[AmbiguitySpan] = []
        for value, refs in self._index.domain_values.items():
            if len(refs) != 1:
                continue
            span = find_phrase(question, value)
            if span is None:
                continue
            start, end = span
            if self._contained(
                spans, AmbiguityType.VALUE_ENTITY_LITERAL, start, end
            ):
                continue
            self._add_span(
                spans,
                AmbiguitySpan(
                    type=AmbiguityType.VALUE_ENTITY_LITERAL,
                    start=start,
                    end=end,
                    snippet=question[start:end],
                    confidence=DOMAIN_VALUE_CONFIDENCE,
                ),
            )
        return spans

    def _detect_unit_scale_currency(self, question: str) -> list[AmbiguitySpan]:
        """V2: the question's unit matches a unit declared on a column."""
        spans: list[AmbiguitySpan] = []
        resolvable = {singularize(token) for token in self._index.unit_terms}
        if not resolvable:
            return spans
        for term in split_terms(question):
            key = term.text.lower()
            if key not in UNIT_TRIGGER_TOKENS:
                continue
            if singularize(key) not in resolvable:
                continue
            if self._contained(
                spans, AmbiguityType.UNIT_SCALE_CURRENCY, term.start, term.end
            ):
                continue
            self._add_span(
                spans,
                AmbiguitySpan(
                    type=AmbiguityType.UNIT_SCALE_CURRENCY,
                    start=term.start,
                    end=term.end,
                    snippet=term.text,
                    confidence=UNIT_CONVENTION_CONFIDENCE,
                ),
            )
        dollar = find_substring(question, "$")
        if dollar is not None and self._index.unit_mentions_currency:
            start, end = dollar
            if not self._contained(
                spans, AmbiguityType.UNIT_SCALE_CURRENCY, start, end
            ):
                self._add_span(
                    spans,
                    AmbiguitySpan(
                        type=AmbiguityType.UNIT_SCALE_CURRENCY,
                        start=start,
                        end=end,
                        snippet="$",
                        confidence=UNIT_CONVENTION_CONFIDENCE,
                    ),
                )
        return spans

    def _detect_granularity(self, question: str) -> list[AmbiguitySpan]:
        """V3: a "by <level>" mention pins one enriched hierarchy column."""
        spans: list[AmbiguitySpan] = []
        terms = split_terms(question)
        for index in range(len(terms) - 1):
            if terms[index].text.lower() != "by":
                continue
            level_term = terms[index + 1]
            key = singularize(level_term.text.lower())
            refs = self._index.hierarchy_columns.get(key)
            if not refs or len(set(refs)) != 1:
                continue
            if self._contained(
                spans, AmbiguityType.GRANULARITY, level_term.start, level_term.end
            ):
                continue
            self._add_span(
                spans,
                AmbiguitySpan(
                    type=AmbiguityType.GRANULARITY,
                    start=level_term.start,
                    end=level_term.end,
                    snippet=level_term.text,
                    confidence=GRANULARITY_CONFIDENCE,
                ),
            )
        return spans

    def _detect_calendar_fiscal(self, question: str) -> list[AmbiguitySpan]:
        """T2: a fiscal reference resolves against a declared fiscal convention."""
        spans: list[AmbiguitySpan] = []
        if not self._index.fiscal_entities:
            return spans
        for term in split_terms(question):
            key = term.text.lower()
            trigger = (
                key == "fiscal"
                or re.fullmatch(r"q[1-4]", key) is not None
                or re.fullmatch(r"fy\d{0,6}", key) is not None
            )
            if not trigger:
                continue
            if self._contained(
                spans, AmbiguityType.CALENDAR_FISCAL, term.start, term.end
            ):
                continue
            self._add_span(
                spans,
                AmbiguitySpan(
                    type=AmbiguityType.CALENDAR_FISCAL,
                    start=term.start,
                    end=term.end,
                    snippet=term.text,
                    confidence=FISCAL_CONVENTION_CONFIDENCE,
                ),
            )
        return spans

    def _detect_business_rule(self, question: str) -> list[AmbiguitySpan]:
        """K2: a rule word is defined by exactly one enriched description."""
        spans: list[AmbiguitySpan] = []
        if not self._index.rule_descriptions:
            return spans
        for term in significant_terms(question):
            key = term.text.lower()
            if key not in BUSINESS_RULE_TRIGGERS:
                continue
            entities = [
                entity
                for entity, text in self._index.rule_descriptions
                if key in normalize_phrase(text)
                and any(
                    marker in normalize_phrase(text)
                    for marker in RULE_DEFINITION_MARKERS
                )
            ]
            if len(entities) != 1:
                continue
            if self._contained(
                spans, AmbiguityType.BUSINESS_RULE, term.start, term.end
            ):
                continue
            self._add_span(
                spans,
                AmbiguitySpan(
                    type=AmbiguityType.BUSINESS_RULE,
                    start=term.start,
                    end=term.end,
                    snippet=term.text,
                    confidence=BUSINESS_RULE_CONFIDENCE,
                ),
            )
        return spans

    @staticmethod
    def _add_span(spans: list[AmbiguitySpan], span: AmbiguitySpan) -> None:
        """Append ``span`` unless an identical (type, start, end) already exists."""
        for existing in spans:
            if (existing.type, existing.start, existing.end) == (
                span.type,
                span.start,
                span.end,
            ):
                return
        spans.append(span)

    @staticmethod
    def _contained(
        spans: list[AmbiguitySpan], type_: AmbiguityType, start: int, end: int
    ) -> bool:
        """Whether a same-type span already covers ``[start, end)``."""
        for existing in spans:
            if (
                existing.type == type_
                and existing.start <= start
                and existing.end >= end
            ):
                return True
        return False


__all__ = [
    "BUSINESS_RULE_CONFIDENCE",
    "BUSINESS_RULE_TRIGGERS",
    "DOMAIN_VALUE_CONFIDENCE",
    "FISCAL_CONVENTION_CONFIDENCE",
    "GRANULARITY_CONFIDENCE",
    "METADATA_GROUNDED_TYPES",
    "MetadataGroundedDetector",
    "RULE_DEFINITION_MARKERS",
    "SYNONYM_MATCH_CONFIDENCE",
    "TABLE_SELECTION_CONFIDENCE",
    "UNIT_CONVENTION_CONFIDENCE",
    "UNIT_TRIGGER_TOKENS",
]
