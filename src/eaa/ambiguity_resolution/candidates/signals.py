"""Deterministic Surface B candidate-selection signals (docs/19 §5.1).

Candidate discovery for the Surface B pool uses **transparent, deterministic,
structural/textual heuristics** over the question text and (where available) the
warehouse schema. Each signal is a named rule that returns the concrete
*evidence* it matched (tokens, phrases, or schema entities) — it is a
discovery/screening hint, **never a gold label** (docs/13, docs/19). Signals
that fire indicate a question may exhibit one of the ambiguity families when a
human screens it; no signal claims an actual ambiguity.

Gold leakage boundary (hard rule, ADR-009): these heuristics read only the
question text and the ``DatabaseSchema``. They never consume gold SQL, gold
tables, join keys, column mappings, domain knowledge, subtask annotations, or
the official benchmark category labels. The detector implementations
(``eaa.ambiguity_resolution.detectors``) are the *consumers* being evaluated
and are deliberately not called here, so the candidate pool cannot be
contaminated by detector output.

The text helpers (``split_terms``, ``significant_terms``, ``normalize_phrase``,
``singularize``) are reused from the detectors' generic matching utilities.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from eaa.core.contracts.schema import DatabaseSchema

from ..detectors.text_matching import (
    normalize_phrase,
    significant_terms,
    singularize,
    split_terms,
)

#: Version of the candidate artifact and of the signal catalog.
CANDIDATE_SCHEMA_VERSION = "surface-b-candidate-v1"

# -- evidence model ---------------------------------------------------------


@dataclass(frozen=True)
class SignalHit:
    """One fired signal plus the concrete evidence that triggered it."""

    signal: str
    name: str
    evidence: tuple[str, ...]


# -- schema term index (used by the schema-grounded signals) ----------------


class _SchemaTermIndex:
    """Normalized single-word keys of the schema, mapped to their tables.

    Built once per database so the schema-grounded signals are cheap across the
    whole pool. Only normalized single-word keys participate (a column named
    ``customer_id`` contributes ``customer``, ``id``); multiword keys cannot be
    matched by a single question token and are ignored, which keeps the rules
    transparent.
    """

    def __init__(self, schema: DatabaseSchema | None) -> None:
        self.column_keys: dict[str, set[str]] = {}
        self.table_keys: dict[str, str] = {}
        if schema is None:
            return
        for table in schema.tables:
            table_key = singularize(normalize_phrase(table.name))
            self.table_keys[table_key] = table.name
            for column in table.columns:
                key = singularize(normalize_phrase(column.name))
                if not key:
                    continue
                self.column_keys.setdefault(key, set()).add(table.name)


# -- textual matchers -------------------------------------------------------


def _tokens(question: str) -> set[str]:
    return {term.text.lower() for term in split_terms(question)}


def _phrase_hits(question: str, phrases: tuple[str, ...]) -> list[str]:
    lower = question.lower()
    hits: list[str] = []
    for phrase in phrases:
        if re.search(r"\b" + re.escape(phrase) + r"\b", lower):
            hits.append(phrase)
    return hits


def _match_quantifier_scope(
    question: str, index: _SchemaTermIndex | None
) -> tuple[str, ...]:
    triggers = frozenset(
        {"every", "each", "all", "any", "no", "never", "both", "either", "neither", "most", "some"}
    )
    hits = sorted(_tokens(question) & triggers)
    hits.extend(_phrase_hits(question, ("not both", "at least one of")))
    return tuple(sorted(set(hits)))


def _match_attachment(question: str, index: _SchemaTermIndex | None) -> tuple[str, ...]:
    prepositions = frozenset({"by", "for", "with"})
    present = sorted(_tokens(question) & prepositions)
    if len(present) < 2:
        return ()
    return tuple(present)


def _match_shared_term(question: str, index: _SchemaTermIndex | None) -> tuple[str, ...]:
    if index is None:
        return ()
    hits: list[str] = []
    for term in significant_terms(question):
        key = singularize(term.text.lower())
        tables = index.column_keys.get(key)
        if tables is not None and len(tables) >= 2:
            hits.append(f"{key} ({len(tables)} tables: {', '.join(sorted(tables))})")
    return tuple(sorted(set(hits)))


def _match_multi_entity(question: str, index: _SchemaTermIndex | None) -> tuple[str, ...]:
    if index is None:
        return ()
    keys = {singularize(term.text.lower()) for term in significant_terms(question)}
    referenced: set[str] = set()
    for key, tables in index.column_keys.items():
        if len(tables) == 1 and key in keys:
            referenced.update(tables)
    for key, name in index.table_keys.items():
        if key in keys:
            referenced.add(name)
    if len(referenced) < 2:
        return ()
    return tuple(sorted(referenced))


def _match_aggregation(question: str, index: _SchemaTermIndex | None) -> tuple[str, ...]:
    triggers = frozenset(
        {
            "total", "sum", "average", "avg", "mean", "count", "maximum",
            "minimum", "max", "min", "percentage", "percent", "ratio", "rate",
        }
    )
    hits = sorted(_tokens(question) & triggers)
    hits.extend(_phrase_hits(question, ("how many", "number of")))
    return tuple(sorted(set(hits)))


def _match_top_n(question: str, index: _SchemaTermIndex | None) -> tuple[str, ...]:
    triggers = frozenset(
        {
            "top", "best", "worst", "highest", "lowest", "largest", "smallest",
            "greatest", "most", "least", "leading", "rank", "ranked", "ranking",
            "first", "last", "better", "superior",
        }
    )
    return tuple(sorted(_tokens(question) & triggers))


def _match_existence_negation(
    question: str, index: _SchemaTermIndex | None
) -> tuple[str, ...]:
    triggers = frozenset(
        {
            "not", "no", "without", "never", "except", "excluding", "none",
            "neither", "whether", "exists", "exist",
        }
    )
    hits = sorted(_tokens(question) & triggers)
    hits.extend(_phrase_hits(question, ("at least", "at most", "did not", "does not", "has never")))
    return tuple(sorted(set(hits)))


def _match_relative_temporal(
    question: str, index: _SchemaTermIndex | None
) -> tuple[str, ...]:
    triggers = frozenset(
        {
            "current", "recent", "latest", "previous", "today", "yesterday",
            "ytd", "since", "until", "upcoming",
        }
    )
    hits = sorted(_tokens(question) & triggers)
    hits.extend(_phrase_hits(question, ("year to date", "as of", "to date", "so far")))
    hits.extend(
        re.findall(
            r"\bthis (?:year|month|quarter|week|day)\b|\blast (?:year|month|quarter|week|day)\b",
            question.lower(),
        )
    )
    return tuple(sorted(set(hits)))


def _match_calendar_fiscal(
    question: str, index: _SchemaTermIndex | None
) -> tuple[str, ...]:
    triggers = frozenset({"fiscal", "calendar", "fy", "quarter", "annual"})
    hits = sorted(_tokens(question) & triggers)
    hits.extend(re.findall(r"\bq[1-4]\b", question.lower()))
    hits.extend(_phrase_hits(question, ("fiscal year", "calendar year")))
    return tuple(sorted(set(hits)))


def _match_value_literal(question: str, index: _SchemaTermIndex | None) -> tuple[str, ...]:
    hits = re.findall(r"[\"']([^\"']+)[\"']", question)
    hits.extend(re.findall(r"(?<![\w])\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?\b", question))
    hits.extend(
        re.findall(
            r"\b(?:january|february|march|april|may|june|july|august|september|"
            r"october|november|december)\s+\d{4}\b",
            question.lower(),
        )
    )
    hits.extend(re.findall(r"\b(?:19\d{2}|20\d{2})\b", question))
    return tuple(sorted(set(hits)))


def _match_unit_scale(question: str, index: _SchemaTermIndex | None) -> tuple[str, ...]:
    triggers = frozenset(
        {
            "million", "millions", "thousand", "thousands", "billion", "billions",
            "usd", "dollar", "dollars", "euro", "euros", "cents", "percent",
            "pct", "sqft", "miles", "tons", "gallons", "inches", "pounds",
            "gb", "mb", "m", "bn", "k",
        }
    )
    hits = sorted(_tokens(question) & triggers)
    hits.extend(
        _phrase_hits(
            question,
            ("in thousands", "in millions", "in billions", "square feet", "square meters"),
        )
    )
    return tuple(sorted(set(hits)))


def _match_granularity(question: str, index: _SchemaTermIndex | None) -> tuple[str, ...]:
    terms = split_terms(question)
    hits: list[str] = []
    for i in range(len(terms) - 1):
        if terms[i].text.lower() in ("by", "per"):
            level = terms[i + 1].text.lower()
            if len(level) >= 3:
                hits.append(f"{terms[i].text.lower()} {level}")
    hits.extend(_phrase_hits(question, ("level of detail",)))
    return tuple(sorted(set(hits)))


def _match_business_rule(question: str, index: _SchemaTermIndex | None) -> tuple[str, ...]:
    triggers = frozenset(
        {
            "active", "current", "valid", "qualified", "vip", "premium",
            "approved", "enabled", "open", "closed", "cancelled", "canceled",
            "standard", "regular", "eligible",
        }
    )
    return tuple(sorted(_tokens(question) & triggers))


def _match_external_knowledge(
    question: str, index: _SchemaTermIndex | None
) -> tuple[str, ...]:
    hits = re.findall(r"\b[A-Z]{2,8}\b", question)
    hits.extend(_phrase_hits(question, ("known as", "often called", "commonly referred to")))
    return tuple(sorted(set(hits)))


def _match_channel(question: str, index: _SchemaTermIndex | None) -> tuple[str, ...]:
    triggers = frozenset(
        {
            "export", "download", "email", "spreadsheet", "csv", "dashboard",
            "report", "print", "alert", "alerts", "notification", "mobile",
        }
    )
    return tuple(sorted(_tokens(question) & triggers))


def _match_chart_type(question: str, index: _SchemaTermIndex | None) -> tuple[str, ...]:
    triggers = frozenset(
        {
            "chart", "charts", "graph", "graphs", "plot", "diagram",
            "histogram", "visualize", "visualization", "viz", "scatter",
            "heatmap",
        }
    )
    hits = sorted(_tokens(question) & triggers)
    hits.extend(
        _phrase_hits(question, ("bar chart", "pie chart", "line chart", "line graph"))
    )
    return tuple(sorted(set(hits)))


# -- catalog ----------------------------------------------------------------


@dataclass(frozen=True)
class Signal:
    """One named, transparent candidate-selection rule.

    ``families`` lists the ambiguity families the signal may touch, as a
    screening hint only — it is not a label.
    """

    id: str
    name: str
    families: tuple[str, ...]
    description: str
    match: Callable[[str, _SchemaTermIndex | None], tuple[str, ...]]


SIGNALS: tuple[Signal, ...] = (
    Signal(
        "s1",
        "quantifier-scope",
        ("S",),
        "Quantifier or negation words (every/each/any/neither) that may take two scopes (S1).",
        _match_quantifier_scope,
    ),
    Signal(
        "s2",
        "attachment",
        ("S",),
        "Attachment prepositions (by/for/with) that may attach to more than one referent (S2).",
        _match_attachment,
    ),
    Signal(
        "r1",
        "shared-term-across-tables",
        ("R",),
        "A question term names a column present in multiple tables (table-selection risk, R1).",
        _match_shared_term,
    ),
    Signal(
        "r2",
        "multi-entity",
        ("R",),
        "The question references entities from two or more tables, a join-path risk (R2).",
        _match_multi_entity,
    ),
    Signal(
        "c1",
        "aggregation-metric",
        ("C",),
        "Aggregation or metric words (total/sum/average/count) whose operand is not pinned (C1).",
        _match_aggregation,
    ),
    Signal(
        "c2",
        "top-n-ranking",
        ("C",),
        "Ranking words (top/best/highest/least) whose ordering or tie handling is undefined (C2).",
        _match_top_n,
    ),
    Signal(
        "c3",
        "existence-negation",
        ("C",),
        "Negation or existence words (not/without/never) with an undefined filter boundary (C3).",
        _match_existence_negation,
    ),
    Signal(
        "t1",
        "relative-temporal",
        ("T",),
        "Relative time references (current/last quarter/recent) with no pinned convention (T1).",
        _match_relative_temporal,
    ),
    Signal(
        "t2",
        "calendar-fiscal",
        ("T",),
        "Calendar vs fiscal references (fiscal/fy/Q1/quarter) whose convention is not pinned (T2).",
        _match_calendar_fiscal,
    ),
    Signal(
        "v1",
        "value-literal",
        ("V",),
        "Literals (quoted values, numbers, years) whose unit or entity is not pinned (V1).",
        _match_value_literal,
    ),
    Signal(
        "v2",
        "unit-scale",
        ("V",),
        "Unit or scale words (millions/usd/k/percent...) whose unit convention is not pinned (V2).",
        _match_unit_scale,
    ),
    Signal(
        "v3",
        "granularity",
        ("V",),
        "'by/per <level>' references whose aggregation level is not pinned (V3).",
        _match_granularity,
    ),
    Signal(
        "k1",
        "external-knowledge",
        ("K",),
        "Acronyms or undefined terms that assume external-world knowledge (K1).",
        _match_external_knowledge,
    ),
    Signal(
        "k2",
        "business-rule",
        ("K",),
        "Business-rule words (active/valid/vip...) whose definition is not in the question (K2).",
        _match_business_rule,
    ),
    Signal(
        "i2",
        "channel-encoding",
        ("I",),
        "Output channel or encoding words (export/dashboard/csv...) that are ambiguous (I2).",
        _match_channel,
    ),
    Signal(
        "i3",
        "chart-type",
        ("I",),
        "Visualization words (chart/graph/plot...) whose chart type is ambiguous (I3).",
        _match_chart_type,
    ),
)

SIGNALS_BY_ID: dict[str, Signal] = {signal.id: signal for signal in SIGNALS}


class SignalScorer:
    """Evaluate the full signal catalog against one question.

    The schema is indexed once per database (``_SchemaTermIndex``), so scoring
    a whole pool reuses a single index per database. ``schema=None`` disables
    the schema-grounded signals and keeps the textual ones.
    """

    def __init__(self, schema: DatabaseSchema | None) -> None:
        self._schema = schema
        self._index = _SchemaTermIndex(schema)

    def score(self, question: str) -> tuple[SignalHit, ...]:
        """Return the fired signals for ``question``, in catalog order."""
        hits: list[SignalHit] = []
        for signal in SIGNALS:
            evidence = signal.match(question, self._index)
            if evidence:
                hits.append(SignalHit(signal.id, signal.name, evidence))
        return tuple(hits)


def evaluate_question(
    question: str, schema: DatabaseSchema | None
) -> tuple[SignalHit, ...]:
    """Return the signals that fire for ``question`` against ``schema``."""
    return SignalScorer(schema).score(question)


__all__ = [
    "CANDIDATE_SCHEMA_VERSION",
    "SIGNALS",
    "SIGNALS_BY_ID",
    "Signal",
    "SignalHit",
    "SignalScorer",
    "evaluate_question",
]
