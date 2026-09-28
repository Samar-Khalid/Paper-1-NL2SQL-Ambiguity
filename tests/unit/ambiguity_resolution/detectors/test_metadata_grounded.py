"""Tests for the metadata-grounded ambiguity detector (docs/14 §4A)."""
import pytest

from eaa.ambiguity_resolution.detectors.metadata_grounded import (
    BUSINESS_RULE_CONFIDENCE,
    DOMAIN_VALUE_CONFIDENCE,
    FISCAL_CONVENTION_CONFIDENCE,
    GRANULARITY_CONFIDENCE,
    METADATA_GROUNDED_TYPES,
    SYNONYM_MATCH_CONFIDENCE,
    TABLE_SELECTION_CONFIDENCE,
    UNIT_CONVENTION_CONFIDENCE,
    MetadataGroundedDetector,
)
from eaa.ambiguity_resolution.errors import AmbiguityResolutionError
from eaa.core.contracts.ambiguity import AmbiguityType, AmbiguityVerdict
from eaa.core.contracts.base import Payload
from eaa.core.contracts.runtime import RuntimeContext, SessionState
from eaa.core.contracts.schema import (
    ColumnSchema,
    ColumnSemantics,
    DatabaseSchema,
    EnrichmentData,
    TableSchema,
)
from eaa.core.contracts.task import TaskEnvelope, TaskHeader
from eaa.core.interfaces.ambiguity import AmbiguityResolver
from eaa.core.registry import envelope_for
from eaa.metadata import enrich_schema

pytestmark = pytest.mark.unit


def _task(question: str) -> TaskEnvelope:
    return envelope_for(
        TaskEnvelope,
        "nl2sql",
        {
            "header": {
                "task_id": "t1",
                "question": question,
                "dataset_id": "dw",
                "dialect": "mysql",
            },
            "payload": {
                "question": question,
                "database_id": "dw",
                "schema_id": None,
                "allowed_tables": None,
            },
        },
    )


def _context() -> RuntimeContext:
    return RuntimeContext(session=SessionState(session_id="s1"))


def _spans_consistent(question: str, analysis) -> None:
    """Every span must index the question and carry a legal confidence."""
    for span in analysis.ambiguous_spans:
        assert span.start >= 0 and span.end > span.start
        assert 0.0 <= span.confidence <= 1.0
        assert question[span.start : span.end] == span.snippet


def test_grounded_types_are_the_seven_enrichment_types() -> None:
    """Only L2/R1/V1/V2/V3/T2/K2 belong to the metadata-grounded family."""
    assert set(METADATA_GROUNDED_TYPES) == {
        AmbiguityType.SYNONYM_COLLISION,
        AmbiguityType.TABLE_SELECTION,
        AmbiguityType.VALUE_ENTITY_LITERAL,
        AmbiguityType.UNIT_SCALE_CURRENCY,
        AmbiguityType.GRANULARITY,
        AmbiguityType.CALENDAR_FISCAL,
        AmbiguityType.BUSINESS_RULE,
    }


def test_detector_satisfies_resolver_protocol(dw_schema) -> None:
    """The detector is structurally an ``AmbiguityResolver`` (analyze + resolve)."""
    assert isinstance(MetadataGroundedDetector(dw_schema), AmbiguityResolver)


def test_synonym_collision_l2(dw_schema) -> None:
    """A business synonym pins the column it aliases (L2)."""
    question = "What was total net sales?"
    detector = MetadataGroundedDetector(dw_schema)
    analysis = detector.analyze(_task(question), _context())
    assert analysis.verdict == AmbiguityVerdict.UNDERDETERMINED
    assert analysis.detected_types == [AmbiguityType.SYNONYM_COLLISION]
    assert len(analysis.ambiguous_spans) == 1
    span = analysis.ambiguous_spans[0]
    assert span.type == AmbiguityType.SYNONYM_COLLISION
    assert span.snippet == "net sales"
    assert span.confidence == SYNONYM_MATCH_CONFIDENCE
    _spans_consistent(question, analysis)


def test_table_selection_r1(dw_schema) -> None:
    """A mention contained in exactly one enriched table description pins it."""
    question = "Revenue split by quarter"
    detector = MetadataGroundedDetector(dw_schema)
    analysis = detector.analyze(_task(question), _context())
    assert analysis.verdict == AmbiguityVerdict.UNDERDETERMINED
    assert analysis.detected_types == [AmbiguityType.TABLE_SELECTION]
    span = analysis.ambiguous_spans[0]
    assert span.type == AmbiguityType.TABLE_SELECTION
    assert span.snippet == "quarter"
    assert span.confidence == TABLE_SELECTION_CONFIDENCE
    _spans_consistent(question, analysis)


def test_value_entity_literal_v1(dw_schema) -> None:
    """A literal matching one column's domain value pins that column (V1)."""
    question = "How many orders are open?"
    detector = MetadataGroundedDetector(dw_schema)
    analysis = detector.analyze(_task(question), _context())
    assert analysis.verdict == AmbiguityVerdict.UNDERDETERMINED
    assert analysis.detected_types == [AmbiguityType.VALUE_ENTITY_LITERAL]
    span = analysis.ambiguous_spans[0]
    assert span.type == AmbiguityType.VALUE_ENTITY_LITERAL
    assert span.snippet == "open"
    assert span.confidence == DOMAIN_VALUE_CONFIDENCE
    _spans_consistent(question, analysis)


def test_unit_scale_currency_v2(dw_schema) -> None:
    """The asked unit resolves against the unit declared on a column (V2)."""
    question = "What was revenue in millions?"
    detector = MetadataGroundedDetector(dw_schema)
    analysis = detector.analyze(_task(question), _context())
    assert analysis.verdict == AmbiguityVerdict.UNDERDETERMINED
    assert analysis.detected_types == [AmbiguityType.UNIT_SCALE_CURRENCY]
    span = analysis.ambiguous_spans[0]
    assert span.type == AmbiguityType.UNIT_SCALE_CURRENCY
    assert span.snippet == "millions"
    assert span.confidence == UNIT_CONVENTION_CONFIDENCE
    _spans_consistent(question, analysis)


def test_unit_dollar_symbol_v2(dw_schema) -> None:
    """A currency symbol resolves against a currency-declared unit (V2)."""
    question = "What was revenue in $?"
    detector = MetadataGroundedDetector(dw_schema)
    analysis = detector.analyze(_task(question), _context())
    assert analysis.verdict == AmbiguityVerdict.UNDERDETERMINED
    span = analysis.ambiguous_spans[0]
    assert span.type == AmbiguityType.UNIT_SCALE_CURRENCY
    assert span.snippet == "$"
    _spans_consistent(question, analysis)


def test_granularity_v3(dw_schema) -> None:
    """A 'by <level>' mention pins one enriched hierarchy column (V3)."""
    question = "What was revenue by region?"
    detector = MetadataGroundedDetector(dw_schema)
    analysis = detector.analyze(_task(question), _context())
    assert analysis.verdict == AmbiguityVerdict.UNDERDETERMINED
    assert analysis.detected_types == [AmbiguityType.GRANULARITY]
    span = analysis.ambiguous_spans[0]
    assert span.type == AmbiguityType.GRANULARITY
    assert span.snippet == "region"
    assert span.confidence == GRANULARITY_CONFIDENCE
    _spans_consistent(question, analysis)


def test_calendar_fiscal_t2(dw_schema) -> None:
    """A fiscal reference resolves against the declared fiscal convention (T2)."""
    question = "How many orders in Q4?"
    detector = MetadataGroundedDetector(dw_schema)
    analysis = detector.analyze(_task(question), _context())
    assert analysis.verdict == AmbiguityVerdict.UNDERDETERMINED
    assert analysis.detected_types == [AmbiguityType.CALENDAR_FISCAL]
    span = analysis.ambiguous_spans[0]
    assert span.type == AmbiguityType.CALENDAR_FISCAL
    assert span.snippet == "Q4"
    assert span.confidence == FISCAL_CONVENTION_CONFIDENCE
    _spans_consistent(question, analysis)


def test_business_rule_k2(dw_schema) -> None:
    """A rule word defined by one enriched description pins the rule (K2)."""
    question = "How many active customers?"
    detector = MetadataGroundedDetector(dw_schema)
    analysis = detector.analyze(_task(question), _context())
    assert analysis.verdict == AmbiguityVerdict.UNDERDETERMINED
    assert analysis.detected_types == [AmbiguityType.BUSINESS_RULE]
    span = analysis.ambiguous_spans[0]
    assert span.type == AmbiguityType.BUSINESS_RULE
    assert span.snippet == "active"
    assert span.confidence == BUSINESS_RULE_CONFIDENCE
    _spans_consistent(question, analysis)


def test_multiple_ambiguities_multi_label(dw_schema) -> None:
    """Several grounded types are reported on one question (docs/13 §6.4)."""
    question = "What was net sales by region in Q4 for active customers?"
    analysis = MetadataGroundedDetector(dw_schema).analyze(
        _task(question), _context()
    )
    assert analysis.verdict == AmbiguityVerdict.UNDERDETERMINED
    assert analysis.detected_types == [
        AmbiguityType.SYNONYM_COLLISION,
        AmbiguityType.GRANULARITY,
        AmbiguityType.CALENDAR_FISCAL,
        AmbiguityType.BUSINESS_RULE,
    ]
    assert {
        (span.type, span.snippet) for span in analysis.ambiguous_spans
    } == {
        (AmbiguityType.SYNONYM_COLLISION, "net sales"),
        (AmbiguityType.GRANULARITY, "region"),
        (AmbiguityType.CALENDAR_FISCAL, "Q4"),
        (AmbiguityType.BUSINESS_RULE, "active"),
    }
    assert analysis.confidence == SYNONYM_MATCH_CONFIDENCE
    _spans_consistent(question, analysis)


def test_same_span_multi_label() -> None:
    """Two types can label the same span (V1 + K2 on 'open', docs/13 §6.4)."""
    base = DatabaseSchema(
        database_id="acct",
        tables=[
            TableSchema(
                name="accounts",
                columns=[
                    ColumnSchema(name="account_id", data_type="int", primary_key=True),
                    ColumnSchema(name="status", data_type="varchar"),
                ],
            )
        ],
    )
    schema = enrich_schema(
        base,
        EnrichmentData(
            database_id="acct",
            column_semantics={
                "accounts": {
                    "status": ColumnSemantics(
                        domain_values=["Open", "Closed"],
                        description="open status means the account is active",
                    )
                }
            },
        ),
    )
    question = "Show accounts with open status."
    analysis = MetadataGroundedDetector(schema).analyze(
        _task(question), _context()
    )
    assert analysis.verdict == AmbiguityVerdict.UNDERDETERMINED
    pairs = {(span.type, span.snippet) for span in analysis.ambiguous_spans}
    assert (AmbiguityType.VALUE_ENTITY_LITERAL, "open") in pairs
    assert (AmbiguityType.BUSINESS_RULE, "open") in pairs
    _spans_consistent(question, analysis)


def test_negative_unambiguous(dw_schema) -> None:
    """A precise question with no grounded mention stays unambiguous."""
    question = "How many customers exist?"
    analysis = MetadataGroundedDetector(dw_schema).analyze(
        _task(question), _context()
    )
    assert analysis.verdict == AmbiguityVerdict.UNAMBIGUOUS
    assert analysis.detected_types == []
    assert analysis.ambiguous_spans == []
    assert analysis.confidence == 0.0


def test_metadata_absent_never_detects(dw_base_schema) -> None:
    """Without enrichment the same question yields no detection (docs/15 §6)."""
    question = "What was net sales by region in Q4 for active customers?"
    detector = MetadataGroundedDetector(dw_base_schema)
    analysis = detector.analyze(_task(question), _context())
    assert analysis.verdict == AmbiguityVerdict.UNAMBIGUOUS
    assert analysis.ambiguous_spans == []


def test_enriched_schema_without_content_is_metadata_absent(dw_base_schema) -> None:
    """An EnrichedSchema carrying no enrichment content detects nothing."""
    from eaa.core.contracts.schema import EnrichedSchema

    empty_enriched = EnrichedSchema(**dw_base_schema.model_dump())
    analysis = MetadataGroundedDetector(empty_enriched).analyze(
        _task("What was net sales?"), _context()
    )
    assert analysis.verdict == AmbiguityVerdict.UNAMBIGUOUS


def test_missing_question_raises(dw_schema) -> None:
    """A payload without a question is rejected."""
    class _NoQuestion(Payload):
        pass

    task = TaskEnvelope(
        type_key="test.no_question",
        header=TaskHeader(task_id="t0", question="q"),
        payload=_NoQuestion(),
    )
    with pytest.raises(AmbiguityResolutionError):
        MetadataGroundedDetector(dw_schema).analyze(task, _context())


def test_deterministic_output(dw_schema) -> None:
    """The same question and schema always produce the same analysis."""
    question = "What was net sales by region in Q4 for active customers?"
    detector = MetadataGroundedDetector(dw_schema)
    first = detector.analyze(_task(question), _context())
    second = detector.analyze(_task(question), _context())
    assert first.model_dump() == second.model_dump()


def test_resolve_is_out_of_scope(dw_schema) -> None:
    """Resolution is not part of the detection slice."""
    detector = MetadataGroundedDetector(dw_schema)
    with pytest.raises(NotImplementedError):
        detector.resolve(
            detector.analyze(_task("How many active customers?"), _context()),
            _task("How many active customers?"),
            _context(),
        )


def test_database_id_ties_analysis_to_schema(dw_schema) -> None:
    """The analysis records the schema it consulted."""
    analysis = MetadataGroundedDetector(dw_schema).analyze(
        _task("How many active customers?"), _context()
    )
    assert analysis.database_id == "dw"
